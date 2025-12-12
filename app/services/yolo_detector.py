"""
EKAIA Puerto - YOLO Detection Service v2
Real-time vehicle and license plate detection with GPU acceleration
Enhanced with image preprocessing for glare/overexposure handling
"""
import torch
import cv2
import numpy as np
from typing import List, Optional
from ultralytics import YOLO
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Detection result"""
    class_id: int
    class_name: str
    confidence: float
    bbox: List[float]
    bbox_normalized: List[float]
    parent_vehicle: Optional['Detection'] = None


class YOLODetector:
    """YOLO detector with preprocessing for challenging lighting"""

    CLASS_NAMES = {0: "vehicle", 1: "plate"}

    def __init__(
        self,
        model_path: str,
        device: str = "cuda:0",
        confidence: float = 0.4,
        iou_threshold: float = 0.45,
        plate_in_vehicle_only: bool = True,
        min_overlap_ratio: float = 0.3,
        enable_preprocessing: bool = True
    ):
        self.device = device
        self.confidence = confidence
        self.iou_threshold = iou_threshold
        self.plate_in_vehicle_only = plate_in_vehicle_only
        self.min_overlap_ratio = min_overlap_ratio
        self.enable_preprocessing = enable_preprocessing

        logger.info(f"Loading YOLO model from {model_path} on {device}")
        self.model = YOLO(model_path)
        
        if device != "cpu" and torch.cuda.is_available():
            self.model.to(device)
            logger.info(f"Model loaded on GPU: {torch.cuda.get_device_name(0)}")
        else:
            self.device = "cpu"
            logger.info("Running on CPU")

        self._warmup()

    def _warmup(self):
        try:
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self.model.predict(dummy, conf=self.confidence, device=self.device, verbose=False)
            logger.info("Model warmup complete")
        except Exception as e:
            logger.warning(f"Warmup failed: {e}")

    def _preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """Enhance frame for better detection in varying light conditions"""
        if not self.enable_preprocessing:
            return frame
        
        # Convert to LAB for brightness handling
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # CLAHE for contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_clahe = clahe.apply(l)
        
        lab_clahe = cv2.merge([l_clahe, a, b])
        enhanced = cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)
        
        return enhanced

    def _reduce_glare(self, frame: np.ndarray) -> np.ndarray:
        """Reduce headlight glare for night detection"""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        
        # Find overexposed areas
        _, bright_mask = cv2.threshold(v, 250, 255, cv2.THRESH_BINARY)
        
        # Expand mask to cover glare halo
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        bright_mask = cv2.dilate(bright_mask, kernel, iterations=2)
        
        # Reduce brightness in glare areas
        v_reduced = v.copy()
        v_reduced[bright_mask > 0] = np.clip(v[bright_mask > 0] * 0.5, 0, 255).astype(np.uint8)
        
        hsv_fixed = cv2.merge([h, s, v_reduced])
        return cv2.cvtColor(hsv_fixed, cv2.COLOR_HSV2BGR)

    def _calculate_overlap_ratio(self, plate_bbox: List[float], vehicle_bbox: List[float]) -> float:
        px1, py1, px2, py2 = plate_bbox
        vx1, vy1, vx2, vy2 = vehicle_bbox

        ix1 = max(px1, vx1)
        iy1 = max(py1, vy1)
        ix2 = min(px2, vx2)
        iy2 = min(py2, vy2)

        if ix1 >= ix2 or iy1 >= iy2:
            return 0.0

        intersection_area = (ix2 - ix1) * (iy2 - iy1)
        plate_area = (px2 - px1) * (py2 - py1)

        return intersection_area / plate_area if plate_area > 0 else 0.0

    def _calculate_iou(self, box1: List[float], box2: List[float]) -> float:
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        if x1 >= x2 or y1 >= y2:
            return 0.0
        
        intersection = (x2 - x1) * (y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0

    def _filter_plates_in_vehicles(self, all_detections: List[Detection]) -> List[Detection]:
        vehicles = [d for d in all_detections if d.class_id == 0]
        plates = [d for d in all_detections if d.class_id == 1]
        
        if not vehicles:
            return vehicles
        
        filtered_plates = []
        
        for plate in plates:
            best_vehicle = None
            best_overlap = 0.0
            
            for vehicle in vehicles:
                overlap = self._calculate_overlap_ratio(plate.bbox, vehicle.bbox)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_vehicle = vehicle
            
            if best_overlap >= self.min_overlap_ratio:
                plate.parent_vehicle = best_vehicle
                filtered_plates.append(plate)
        
        return vehicles + filtered_plates

    def _run_inference(self, frame: np.ndarray) -> List[Detection]:
        """Run model inference on a frame"""
        results = self.model.predict(
            frame,
            conf=self.confidence,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
            stream=False
        )[0]

        detections = []
        h, w = frame.shape[:2]

        for box in results.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            bbox = box.xyxy[0].cpu().numpy().tolist()

            x1, y1, x2, y2 = bbox
            bbox_norm = [x1/w, y1/h, x2/w, y2/h]

            detection = Detection(
                class_id=class_id,
                class_name=self.CLASS_NAMES.get(class_id, "unknown"),
                confidence=confidence,
                bbox=bbox,
                bbox_normalized=bbox_norm
            )
            detections.append(detection)

        return detections

    def detect(self, frame: np.ndarray, filter_plates: bool = None) -> List[Detection]:
        """Run detection with multiple preprocessing attempts"""
        if filter_plates is None:
            filter_plates = self.plate_in_vehicle_only

        # First try: preprocessed frame
        processed = self._preprocess_frame(frame)
        detections = self._run_inference(processed)
        
        plates_found = [d for d in detections if d.class_id == 1]
        
        # Second try: if no plates, try with glare reduction
        if len(plates_found) == 0:
            deglared = self._reduce_glare(frame)
            deglared_processed = self._preprocess_frame(deglared)
            extra_detections = self._run_inference(deglared_processed)
            
            # Add new detections
            existing_bboxes = [d.bbox for d in detections]
            for det in extra_detections:
                is_duplicate = False
                for existing in existing_bboxes:
                    if self._calculate_iou(det.bbox, existing) > 0.5:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    detections.append(det)
        
        # Third try: original frame without preprocessing
        plates_found = [d for d in detections if d.class_id == 1]
        if len(plates_found) == 0:
            orig_detections = self._run_inference(frame)
            existing_bboxes = [d.bbox for d in detections]
            for det in orig_detections:
                is_duplicate = False
                for existing in existing_bboxes:
                    if self._calculate_iou(det.bbox, existing) > 0.5:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    detections.append(det)

        if filter_plates:
            detections = self._filter_plates_in_vehicles(detections)

        return detections

    def detect_plates(self, frame: np.ndarray) -> List[Detection]:
        all_detections = self.detect(frame, filter_plates=True)
        return [d for d in all_detections if d.class_id == 1]

    def detect_vehicles(self, frame: np.ndarray) -> List[Detection]:
        all_detections = self.detect(frame, filter_plates=False)
        return [d for d in all_detections if d.class_id == 0]

    def detect_all_unfiltered(self, frame: np.ndarray) -> List[Detection]:
        return self.detect(frame, filter_plates=False)

    def draw_detections(self, frame: np.ndarray, detections: List[Detection], show_conf: bool = True) -> np.ndarray:
        annotated = frame.copy()
        colors = {0: (0, 255, 0), 1: (0, 255, 255)}

        for det in detections:
            x1, y1, x2, y2 = map(int, det.bbox)
            color = colors.get(det.class_id, (255, 255, 255))

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            label = f"{det.class_name}"
            if show_conf:
                label += f" {det.confidence:.2f}"

            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 10), (x1 + tw, y1), color, -1)
            cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)

        return annotated


_detector_instance = None


def get_detector(
    model_path: str, 
    device: str = "cuda:0", 
    confidence: float = 0.4,
    plate_in_vehicle_only: bool = True
) -> YOLODetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = YOLODetector(
            model_path, 
            device, 
            confidence,
            plate_in_vehicle_only=plate_in_vehicle_only,
            min_overlap_ratio=0.3,
            enable_preprocessing=True
        )
    return _detector_instance
"""
EKAIA Puerto - Detection Endpoints
Vehicle and plate detection with OCR
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional
import logging
import cv2
import numpy as np

from app.services import (
    VehicleTracker,
    get_detector,
    get_detection_cooldown,
    get_ocr_service,
    get_stream_manager,
)
from app.models import DatabaseManager
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["detection"])

settings = get_settings()
db_manager = DatabaseManager(settings.database_url)


# Dependency
async def get_db():
    async for session in db_manager.get_session():
        yield session


class DetectionResponse(BaseModel):
    """Detection API response"""
    camera: str
    detections: List[dict]
    plates_detected: List[dict]
    timestamp: str


class PlateDetection(BaseModel):
    """Plate detection with OCR"""
    plate_text: Optional[str]
    confidence: float
    ocr_confidence: float
    bbox: List[float]


@router.post("/detect/{camera_name}")
async def detect_on_camera(
    camera_name: str,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """
    Run detection on specific camera
    Args:
        camera_name: 'entrada' or 'salida'
    Returns:
        Detection results with OCR
    """
    if camera_name not in ["entrada", "salida"]:
        raise HTTPException(status_code=400, detail="Invalid camera name")

    # Get stream
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream(camera_name)

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail=f"Stream {camera_name} not available")

    # Get frame
    frame = stream.get_latest_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available")

    # Get services
    detector = get_detector(settings.yolo_model_path, settings.yolo_device, settings.yolo_confidence)
    ocr = get_ocr_service(use_gpu=settings.ocr_gpu)
    cooldown = get_detection_cooldown()
    tracker = VehicleTracker(db)

    # Detect
    detections = detector.detect(frame)
    plate_detections = [d for d in detections if d.class_id == 1]

    plates_with_ocr = []

    # Process each plate
    for plate_det in plate_detections:
        # Extract OCR
        plate_text, ocr_conf = ocr.extract_from_bbox(frame, plate_det.bbox)

        plate_info = {
            "plate_text": plate_text,
            "confidence": plate_det.confidence,
            "ocr_confidence": ocr_conf,
            "bbox": plate_det.bbox
        }
        plates_with_ocr.append(plate_info)

        # Register in tracker if valid and not throttled
        if plate_text and ocr_conf > 0.6 and cooldown.allow(plate_text, camera_name):
            if camera_name == "entrada":
                await tracker.register_entry(plate_text, plate_det.confidence)
            elif camera_name == "salida":
                await tracker.register_exit(plate_text, plate_det.confidence)

            await tracker.log_detection(
                camera=camera_name,
                plate=plate_text,
                confidence=plate_det.confidence,
                bbox=plate_det.bbox,
                ocr_text=plate_text
            )

    return {
        "camera": camera_name,
        "detections": [
            {
                "class": d.class_name,
                "confidence": d.confidence,
                "bbox": d.bbox
            } for d in detections
        ],
        "plates_detected": plates_with_ocr,
        "timestamp": stream.last_frame_time
    }


@router.get("/vehicles/inside")
async def get_vehicles_inside(db: AsyncSession = Depends(get_db)):
    """Get all vehicles currently inside the port"""
    tracker = VehicleTracker(db)
    vehicles = await tracker.get_vehicles_inside()
    return {"vehicles": [v.to_dict() for v in vehicles]}


@router.get("/vehicles/recent-exits")
async def get_recent_exits(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get recent vehicle exits"""
    tracker = VehicleTracker(db)
    vehicles = await tracker.get_recent_exits(limit)
    return {"exits": [v.to_dict() for v in vehicles]}


@router.get("/vehicles/history/{plate}")
async def get_vehicle_history(plate: str, db: AsyncSession = Depends(get_db)):
    """Get history for specific plate"""
    tracker = VehicleTracker(db)
    history = await tracker.get_vehicle_history(plate)
    return {"plate": plate, "history": [v.to_dict() for v in history]}


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Get current statistics"""
    tracker = VehicleTracker(db)
    stats = await tracker.get_stats()
    return stats

"""
EKAIA Puerto - Vehicle Tracker with Detection Buffer
Accumulates multiple plate readings and selects the best one
Handles fast-moving vehicles with prediction
"""
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class PlateReading:
    """Single plate reading"""
    text: str
    confidence: float
    ocr_confidence: float
    timestamp: float
    bbox: List[float]
    frame_id: int = 0


@dataclass 
class TrackedVehicle:
    """Vehicle being tracked with multiple plate readings"""
    track_id: str
    first_seen: float
    last_seen: float
    readings: List[PlateReading] = field(default_factory=list)
    best_plate: Optional[str] = None
    best_confidence: float = 0.0
    positions: List[Tuple[float, float]] = field(default_factory=list)  # centroids
    velocity: Tuple[float, float] = (0.0, 0.0)  # pixels per second
    crossed_tripwire: bool = False
    registered: bool = False
    
    def add_reading(self, reading: PlateReading):
        """Add a plate reading and update best plate"""
        self.readings.append(reading)
        self.last_seen = reading.timestamp
        
        # Update best plate using weighted scoring
        self._update_best_plate()
        
        # Update position tracking
        cx = (reading.bbox[0] + reading.bbox[2]) / 2
        cy = (reading.bbox[1] + reading.bbox[3]) / 2
        self.positions.append((cx, cy))
        
        # Calculate velocity if we have enough positions
        if len(self.positions) >= 2:
            self._update_velocity()
    
    def _update_best_plate(self):
        """Select best plate from all readings using voting + confidence"""
        if not self.readings:
            return
        
        # Count occurrences of each plate text
        plate_scores: Dict[str, float] = defaultdict(float)
        plate_counts: Dict[str, int] = defaultdict(int)
        
        for reading in self.readings:
            if reading.text:
                # Score = detection_conf * ocr_conf * recency_weight
                recency = 1.0 - (time.time() - reading.timestamp) / 10.0  # decay over 10s
                recency = max(0.5, min(1.0, recency))
                
                score = reading.confidence * reading.ocr_confidence * recency
                plate_scores[reading.text] += score
                plate_counts[reading.text] += 1
        
        if not plate_scores:
            return
        
        # Find best plate (highest total score with count bonus)
        best_plate = None
        best_score = 0.0
        
        for plate, score in plate_scores.items():
            # Bonus for multiple consistent readings
            count_bonus = min(plate_counts[plate] * 0.1, 0.5)
            final_score = score + count_bonus
            
            if final_score > best_score:
                best_score = final_score
                best_plate = plate
        
        self.best_plate = best_plate
        self.best_confidence = best_score
        
        logger.debug(f"Track {self.track_id}: best plate = {best_plate} (score={best_score:.2f}, readings={len(self.readings)})")
    
    def _update_velocity(self):
        """Calculate velocity from recent positions"""
        if len(self.positions) < 2:
            return
        
        # Use last 5 positions
        recent = self.positions[-5:]
        if len(recent) < 2:
            return
        
        # Calculate average velocity
        dt = (self.last_seen - self.first_seen) / max(1, len(recent) - 1)
        if dt <= 0:
            return
        
        dx = recent[-1][0] - recent[0][0]
        dy = recent[-1][1] - recent[0][1]
        
        self.velocity = (dx / dt, dy / dt)
    
    def predict_position(self, dt: float) -> Tuple[float, float]:
        """Predict position after dt seconds"""
        if not self.positions:
            return (0, 0)
        
        last_pos = self.positions[-1]
        return (
            last_pos[0] + self.velocity[0] * dt,
            last_pos[1] + self.velocity[1] * dt
        )
    
    def get_reading_count(self) -> int:
        return len(self.readings)
    
    def get_unique_plates(self) -> List[str]:
        """Get list of unique plate texts detected"""
        return list(set(r.text for r in self.readings if r.text))


class DetectionBuffer:
    """
    Buffer that accumulates detections and tracks vehicles
    Handles fast-moving vehicles by:
    1. Tracking objects across frames
    2. Accumulating multiple OCR readings
    3. Selecting best plate via voting
    4. Predicting positions for fast vehicles
    """
    
    def __init__(
        self,
        max_age: float = 5.0,           # Max seconds to keep track alive
        min_readings: int = 2,           # Min readings before confirming plate
        iou_threshold: float = 0.3,      # IOU for matching detections
        max_tracks: int = 50             # Max concurrent tracks
    ):
        self.max_age = max_age
        self.min_readings = min_readings
        self.iou_threshold = iou_threshold
        self.max_tracks = max_tracks
        
        self.tracks: Dict[str, TrackedVehicle] = {}
        self.next_track_id = 0
        self.frame_count = 0
        
        # Confirmed plates (ready for registration)
        self.confirmed_plates: List[Tuple[str, str, float]] = []  # (track_id, plate, confidence)
    
    def _calculate_iou(self, bbox1: List[float], bbox2: List[float]) -> float:
        """Calculate Intersection over Union"""
        x1_1, y1_1, x2_1, y2_1 = bbox1
        x1_2, y1_2, x2_2, y2_2 = bbox2
        
        xi1 = max(x1_1, x1_2)
        yi1 = max(y1_1, y1_2)
        xi2 = min(x2_1, x2_2)
        yi2 = min(y2_1, y2_2)
        
        if xi1 >= xi2 or yi1 >= yi2:
            return 0.0
        
        inter_area = (xi2 - xi1) * (yi2 - yi1)
        
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        
        union_area = area1 + area2 - inter_area
        
        if union_area <= 0:
            return 0.0
        
        return inter_area / union_area
    
    def _find_matching_track(self, bbox: List[float]) -> Optional[str]:
        """Find existing track that matches this detection"""
        best_track_id = None
        best_iou = self.iou_threshold
        
        current_time = time.time()
        
        for track_id, track in self.tracks.items():
            if not track.positions:
                continue
            
            # Get last known position as bbox estimate
            last_reading = track.readings[-1] if track.readings else None
            if not last_reading:
                continue
            
            # Use prediction for fast vehicles
            dt = current_time - track.last_seen
            if dt > 0 and track.velocity != (0, 0):
                # Predict where the vehicle should be
                pred_cx, pred_cy = track.predict_position(dt)
                
                # Create predicted bbox (same size, new center)
                old_bbox = last_reading.bbox
                w = old_bbox[2] - old_bbox[0]
                h = old_bbox[3] - old_bbox[1]
                pred_bbox = [pred_cx - w/2, pred_cy - h/2, pred_cx + w/2, pred_cy + h/2]
                
                iou = self._calculate_iou(bbox, pred_bbox)
            else:
                iou = self._calculate_iou(bbox, last_reading.bbox)
            
            if iou > best_iou:
                best_iou = iou
                best_track_id = track_id
        
        return best_track_id
    
    def _create_track(self, bbox: List[float]) -> str:
        """Create new track"""
        track_id = f"track_{self.next_track_id}"
        self.next_track_id += 1
        
        current_time = time.time()
        self.tracks[track_id] = TrackedVehicle(
            track_id=track_id,
            first_seen=current_time,
            last_seen=current_time
        )
        
        logger.debug(f"Created new track: {track_id}")
        return track_id
    
    def add_detection(
        self,
        bbox: List[float],
        plate_text: Optional[str],
        detection_confidence: float,
        ocr_confidence: float
    ) -> str:
        """
        Add detection to buffer
        Returns track_id
        """
        self.frame_count += 1
        current_time = time.time()
        
        # Find or create track
        track_id = self._find_matching_track(bbox)
        
        if track_id is None:
            track_id = self._create_track(bbox)
        
        # Add reading to track
        reading = PlateReading(
            text=plate_text,
            confidence=detection_confidence,
            ocr_confidence=ocr_confidence,
            timestamp=current_time,
            bbox=bbox,
            frame_id=self.frame_count
        )
        
        self.tracks[track_id].add_reading(reading)
        
        # Check if plate is confirmed
        track = self.tracks[track_id]
        if (track.best_plate and 
            track.get_reading_count() >= self.min_readings and
            not track.registered):
            
            self.confirmed_plates.append((
                track_id,
                track.best_plate,
                track.best_confidence
            ))
            logger.info(f"✅ Plate confirmed: {track.best_plate} (track={track_id}, readings={track.get_reading_count()})")
        
        return track_id
    
    def get_confirmed_plates(self) -> List[Tuple[str, str, float]]:
        """Get and clear confirmed plates"""
        plates = self.confirmed_plates.copy()
        self.confirmed_plates.clear()
        return plates
    
    def mark_registered(self, track_id: str):
        """Mark track as registered in database"""
        if track_id in self.tracks:
            self.tracks[track_id].registered = True
    
    def mark_crossed_tripwire(self, track_id: str):
        """Mark track as having crossed tripwire"""
        if track_id in self.tracks:
            self.tracks[track_id].crossed_tripwire = True
    
    def get_track(self, track_id: str) -> Optional[TrackedVehicle]:
        """Get track by ID"""
        return self.tracks.get(track_id)
    
    def cleanup(self):
        """Remove old tracks"""
        current_time = time.time()
        expired = []
        
        for track_id, track in self.tracks.items():
            age = current_time - track.last_seen
            if age > self.max_age:
                expired.append(track_id)
        
        for track_id in expired:
            track = self.tracks[track_id]
            if track.best_plate and not track.registered:
                logger.warning(f"Track {track_id} expired without registration: {track.best_plate}")
            del self.tracks[track_id]
        
        # Limit total tracks
        if len(self.tracks) > self.max_tracks:
            # Remove oldest tracks
            sorted_tracks = sorted(
                self.tracks.items(),
                key=lambda x: x[1].last_seen
            )
            for track_id, _ in sorted_tracks[:len(self.tracks) - self.max_tracks]:
                del self.tracks[track_id]
    
    def get_stats(self) -> dict:
        """Get buffer statistics"""
        return {
            "active_tracks": len(self.tracks),
            "total_frames": self.frame_count,
            "pending_confirmations": len(self.confirmed_plates),
            "tracks": {
                tid: {
                    "best_plate": t.best_plate,
                    "readings": t.get_reading_count(),
                    "registered": t.registered,
                    "crossed": t.crossed_tripwire
                }
                for tid, t in self.tracks.items()
            }
        }


# Singleton instances per camera
_buffers: Dict[str, DetectionBuffer] = {}


def get_detection_buffer(camera: str) -> DetectionBuffer:
    """Get or create detection buffer for camera"""
    if camera not in _buffers:
        _buffers[camera] = DetectionBuffer()
    return _buffers[camera]
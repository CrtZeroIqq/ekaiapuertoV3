"""
EKAIA Puerto - Tripwire Service
Detects when vehicles cross a defined line (entry/exit validation)
"""
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class TripwireLine:
    """Defines a tripwire line with two points"""
    name: str
    p1: Tuple[int, int]  # Start point (x1, y1)
    p2: Tuple[int, int]  # End point (x2, y2)
    direction: str = "down"  # Valid crossing direction: "down", "up", "left", "right", "both"
    
    def get_line_params(self) -> Tuple[float, float, float]:
        """Get line equation coefficients: ax + by + c = 0"""
        x1, y1 = self.p1
        x2, y2 = self.p2
        a = y2 - y1
        b = x1 - x2
        c = x2 * y1 - x1 * y2
        return a, b, c
    
    def point_side(self, point: Tuple[int, int]) -> float:
        """
        Determine which side of the line a point is on
        Returns: positive = one side, negative = other side, 0 = on line
        """
        a, b, c = self.get_line_params()
        x, y = point
        return a * x + b * y + c


@dataclass
class TrackedObject:
    """Tracks an object's position history for line crossing detection"""
    track_id: str
    positions: List[Tuple[int, int]] = field(default_factory=list)
    last_seen: float = 0
    crossed: bool = False
    plate_text: Optional[str] = None
    
    def add_position(self, centroid: Tuple[int, int]):
        self.positions.append(centroid)
        self.last_seen = time.time()
        # Keep only last 30 positions
        if len(self.positions) > 30:
            self.positions = self.positions[-30:]
    
    def get_centroid(self) -> Optional[Tuple[int, int]]:
        if self.positions:
            return self.positions[-1]
        return None
    
    def get_previous_centroid(self) -> Optional[Tuple[int, int]]:
        if len(self.positions) >= 2:
            return self.positions[-2]
        return None


class TripwireDetector:
    """
    Detects when tracked objects cross defined tripwire lines
    """
    
    def __init__(self):
        self.lines: Dict[str, TripwireLine] = {}
        self.tracked_objects: Dict[str, Dict[str, TrackedObject]] = defaultdict(dict)
        self.crossing_cooldown: Dict[str, float] = {}  # plate -> last_crossing_time
        self.cooldown_seconds: float = 30.0  # Prevent double counting
        
    def add_line(self, camera: str, name: str, p1: Tuple[int, int], p2: Tuple[int, int], direction: str = "down"):
        """Add a tripwire line for a camera"""
        key = f"{camera}_{name}"
        self.lines[key] = TripwireLine(name=name, p1=p1, p2=p2, direction=direction)
        logger.info(f"✅ Tripwire added: {key} from {p1} to {p2}, direction={direction}")
    
    def remove_line(self, camera: str, name: str):
        """Remove a tripwire line"""
        key = f"{camera}_{name}"
        if key in self.lines:
            del self.lines[key]
            logger.info(f"🗑️ Tripwire removed: {key}")
    
    def get_line(self, camera: str, name: str) -> Optional[TripwireLine]:
        """Get a specific tripwire line"""
        key = f"{camera}_{name}"
        return self.lines.get(key)
    
    def get_lines_for_camera(self, camera: str) -> Dict[str, TripwireLine]:
        """Get all tripwire lines for a camera"""
        return {k: v for k, v in self.lines.items() if k.startswith(f"{camera}_")}
    
    def bbox_to_centroid(self, bbox: List[float]) -> Tuple[int, int]:
        """Convert bounding box to bottom-center point (better for vehicle tracking)"""
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2)
        cy = int(y2)  # Bottom of bbox (wheels position)
        return (cx, cy)
    
    def update_track(self, camera: str, track_id: str, bbox: List[float], plate_text: Optional[str] = None):
        """Update tracked object position"""
        centroid = self.bbox_to_centroid(bbox)
        
        if track_id not in self.tracked_objects[camera]:
            self.tracked_objects[camera][track_id] = TrackedObject(track_id=track_id)
        
        obj = self.tracked_objects[camera][track_id]
        obj.add_position(centroid)
        if plate_text:
            obj.plate_text = plate_text
    
    def check_crossing(self, camera: str, track_id: str, line_name: str = "main") -> Optional[dict]:
        """
        Check if a tracked object has crossed the tripwire line
        Returns crossing info if crossed, None otherwise
        """
        key = f"{camera}_{line_name}"
        line = self.lines.get(key)
        
        if not line:
            return None
        
        if camera not in self.tracked_objects or track_id not in self.tracked_objects[camera]:
            return None
        
        obj = self.tracked_objects[camera][track_id]
        
        # Need at least 2 positions to detect crossing
        current = obj.get_centroid()
        previous = obj.get_previous_centroid()
        
        if not current or not previous:
            return None
        
        # Already crossed in this track session
        if obj.crossed:
            return None
        
        # Check if crossed line
        side_current = line.point_side(current)
        side_previous = line.point_side(previous)
        
        # Crossed if signs are different (and neither is 0)
        if side_current * side_previous < 0:
            # Validate direction
            valid_crossing = False
            
            if line.direction == "both":
                valid_crossing = True
            elif line.direction == "down":
                # Crossing from negative to positive Y (top to bottom)
                valid_crossing = current[1] > previous[1]
            elif line.direction == "up":
                valid_crossing = current[1] < previous[1]
            elif line.direction == "right":
                valid_crossing = current[0] > previous[0]
            elif line.direction == "left":
                valid_crossing = current[0] < previous[0]
            
            if valid_crossing:
                # Check cooldown for this plate
                plate = obj.plate_text
                if plate:
                    cooldown_key = f"{camera}_{plate}"
                    last_crossing = self.crossing_cooldown.get(cooldown_key, 0)
                    if time.time() - last_crossing < self.cooldown_seconds:
                        logger.debug(f"⏳ Cooldown active for {plate} on {camera}")
                        return None
                    self.crossing_cooldown[cooldown_key] = time.time()
                
                obj.crossed = True
                
                crossing_info = {
                    "camera": camera,
                    "line": line_name,
                    "track_id": track_id,
                    "plate_text": obj.plate_text,
                    "crossing_point": current,
                    "direction": line.direction,
                    "timestamp": time.time()
                }
                
                logger.info(f"🚗 CROSSING DETECTED: {crossing_info}")
                return crossing_info
        
        return None
    
    def process_detection(
        self, 
        camera: str, 
        track_id: str, 
        bbox: List[float], 
        plate_text: Optional[str] = None,
        line_name: str = "main"
    ) -> Optional[dict]:
        """
        Process a detection and check for line crossing
        Combines update_track and check_crossing
        """
        self.update_track(camera, track_id, bbox, plate_text)
        return self.check_crossing(camera, track_id, line_name)
    
    def cleanup_old_tracks(self, max_age_seconds: float = 60.0):
        """Remove tracks that haven't been seen recently"""
        current_time = time.time()
        for camera in list(self.tracked_objects.keys()):
            for track_id in list(self.tracked_objects[camera].keys()):
                obj = self.tracked_objects[camera][track_id]
                if current_time - obj.last_seen > max_age_seconds:
                    del self.tracked_objects[camera][track_id]
    
    def reset_track(self, camera: str, track_id: str):
        """Reset a track (allow new crossing detection)"""
        if camera in self.tracked_objects and track_id in self.tracked_objects[camera]:
            del self.tracked_objects[camera][track_id]
    
    def get_stats(self) -> dict:
        """Get tripwire statistics"""
        return {
            "lines": {k: {"p1": v.p1, "p2": v.p2, "direction": v.direction} for k, v in self.lines.items()},
            "active_tracks": {camera: len(tracks) for camera, tracks in self.tracked_objects.items()},
            "total_tracks": sum(len(tracks) for tracks in self.tracked_objects.values())
        }


# Singleton instance
_tripwire_instance: Optional[TripwireDetector] = None


def get_tripwire_detector() -> TripwireDetector:
    """Get or create tripwire detector singleton"""
    global _tripwire_instance
    if _tripwire_instance is None:
        _tripwire_instance = TripwireDetector()
    return _tripwire_instance
"""
EKAIA Puerto - Detection Endpoints
Optimized for fast-moving vehicles with detection buffer and high FPS
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional, Tuple
import logging
import time
import threading
import asyncio

from app.services import (
    VehicleTracker,
    get_detector,
    get_ocr_service,
    get_stream_manager,
)
from app.services.tripwire import get_tripwire_detector
from app.services.detection_buffer import get_detection_buffer, DetectionBuffer
from app.models import DatabaseManager
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["detection"])

settings = get_settings()
db_manager = DatabaseManager(settings.database_url)


# ============================================
# TRIPWIRE CONFIGURATION
# ============================================
def setup_tripwire_lines():
    """Configure tripwire lines for each camera"""
    tripwire = get_tripwire_detector()
    
    # Solo línea de entrada
    tripwire.add_line(
        camera="entrada",
        name="main",
        p1=(80, 430),
        p2=(550, 460),
        direction="down"
    )
    
    logger.info("✅ Tripwire lines configured")
    _update_stream_tripwires()


def _update_stream_tripwires():
    """Update stream overlays with tripwire lines"""
    tripwire = get_tripwire_detector()
    stream_manager = get_stream_manager()
    
    for camera in ["entrada", "salida"]:
        lines = tripwire.get_lines_for_camera(camera)
        line_data = [
            {"p1": v.p1, "p2": v.p2, "name": v.name, "direction": v.direction}
            for k, v in lines.items()
        ]
        stream_manager.update_stream_tripwire(camera, line_data)


# Initialize on module load
setup_tripwire_lines()


# ============================================
# HIGH-SPEED DETECTION LOOP
# ============================================
class DetectionLoop:
    """
    High-speed detection loop optimized for fast vehicles
    - 30 FPS detection rate
    - Detection buffer for plate accumulation
    - Async database registration
    """
    
    def __init__(self):
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.detection_interval = 0.033  # ~30 FPS
        self._detector = None
        self._ocr = None
        self._db_queue: List[Tuple[str, str, float, str]] = []  # (camera, plate, conf, track_id)
        self._db_lock = threading.Lock()
    
    def start(self):
        """Start detection loop"""
        if self.is_running:
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._detection_loop, daemon=True)
        self.thread.start()
        
        # Start DB writer thread
        self._db_thread = threading.Thread(target=self._db_writer_loop, daemon=True)
        self._db_thread.start()
        
        logger.info("🔍 Detection loop started (30 FPS)")
    
    def stop(self):
        """Stop detection loop"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("🛑 Detection loop stopped")
    
    def _get_detector(self):
        """Lazy load detector"""
        if self._detector is None:
            try:
                self._detector = get_detector(
                    settings.yolo_model_path,
                    settings.yolo_device,
                    settings.yolo_confidence
                )
            except Exception as e:
                logger.error(f"Failed to load detector: {e}")
        return self._detector
    
    def _get_ocr(self):
        """Lazy load OCR"""
        if self._ocr is None:
            try:
                self._ocr = get_ocr_service(use_gpu=settings.ocr_gpu)
            except Exception as e:
                logger.warning(f"OCR not available: {e}")
        return self._ocr
    
    def _queue_db_registration(self, camera: str, plate: str, confidence: float, track_id: str):
        """Queue plate for database registration"""
        with self._db_lock:
            self._db_queue.append((camera, plate, confidence, track_id))
    
    def _db_writer_loop(self):
        """Background thread for database writes"""
        while self.is_running:
            try:
                # Get pending registrations
                with self._db_lock:
                    if not self._db_queue:
                        time.sleep(0.1)
                        continue
                    pending = self._db_queue.copy()
                    self._db_queue.clear()
                
                # Process registrations
                for camera, plate, confidence, track_id in pending:
                    self._register_plate(camera, plate, confidence, track_id)
                
            except Exception as e:
                logger.error(f"DB writer error: {e}")
                time.sleep(1)
    
    def _register_plate(self, camera: str, plate: str, confidence: float, track_id: str):
        """Register plate in database"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def _async_register():
                async for session in db_manager.get_session():
                    tracker = VehicleTracker(session)
                    
                    if camera == "entrada":
                        await tracker.register_entry(plate, confidence)
                        logger.info(f"🚗 ENTRADA registrada: {plate} (track={track_id})")
                    elif camera == "salida":
                        await tracker.register_exit(plate, confidence)
                        logger.info(f"🚗 SALIDA registrada: {plate} (track={track_id})")
                    
                    # Also log detection
                    await tracker.log_detection(
                        camera=camera,
                        plate=plate,
                        confidence=confidence,
                        bbox=[],
                        ocr_text=plate
                    )
                    break
            
            loop.run_until_complete(_async_register())
            loop.close()
            
            # Mark as registered in buffer
            buffer = get_detection_buffer(camera)
            buffer.mark_registered(track_id)
            
        except Exception as e:
            logger.error(f"Failed to register plate {plate}: {e}")
    
    def _detection_loop(self):
        """Main high-speed detection loop"""
        stream_manager = get_stream_manager()
        tripwire = get_tripwire_detector()
        
        frame_count = 0
        last_cleanup = time.time()
        
        while self.is_running:
            loop_start = time.time()
            
            try:
                for camera_name in ["entrada", "salida"]:
                    stream = stream_manager.get_stream(camera_name)
                    
                    if not stream or not stream.is_alive():
                        continue
                    
                    frame = stream.get_latest_frame()
                    if frame is None:
                        continue
                    
                    # Get detection buffer for this camera
                    buffer = get_detection_buffer(camera_name)
                    
                    # Run YOLO detection
                    detector = self._get_detector()
                    if not detector:
                        continue
                    
                    detections = detector.detect(frame)
                    
                    # Process detections
                    overlay_detections = []
                    
                    for det in detections:
                        plate_text = None
                        ocr_conf = 0.0
                        
                        # Run OCR on plates
                        if det.class_id == 1:
                            ocr = self._get_ocr()
                            if ocr:
                                try:
                                    plate_text, ocr_conf = ocr.extract_from_bbox(frame, det.bbox)
                                except Exception as e:
                                    logger.debug(f"OCR error: {e}")
                            
                            # Add to detection buffer
                            if plate_text or det.confidence > 0.7:
                                track_id = buffer.add_detection(
                                    bbox=det.bbox,
                                    plate_text=plate_text,
                                    detection_confidence=det.confidence,
                                    ocr_confidence=ocr_conf
                                )
                                
                                # Check tripwire crossing
                                crossing = tripwire.process_detection(
                                    camera=camera_name,
                                    track_id=track_id,
                                    bbox=det.bbox,
                                    plate_text=plate_text,
                                    line_name="main"
                                )
                                
                                if crossing:
                                    buffer.mark_crossed_tripwire(track_id)
                        
                        overlay_detections.append({
                            "bbox": det.bbox,
                            "class": det.class_name,
                            "confidence": det.confidence,
                            "plate_text": plate_text
                        })
                    
                    # Update stream overlay
                    stream.update_detections(overlay_detections)
                    
                    # Process confirmed plates from buffer
                    confirmed = buffer.get_confirmed_plates()
                    for track_id, plate, confidence in confirmed:
                        track = buffer.get_track(track_id)
                        
                        # Register if crossed tripwire OR if no tripwire for this camera
                        has_tripwire = bool(tripwire.get_lines_for_camera(camera_name))
                        
                        if not has_tripwire or (track and track.crossed_tripwire):
                            self._queue_db_registration(camera_name, plate, confidence, track_id)
                        elif track and not track.crossed_tripwire:
                            logger.debug(f"Plate {plate} confirmed but hasn't crossed tripwire yet")
                
                # Periodic cleanup
                if time.time() - last_cleanup > 5.0:
                    for camera in ["entrada", "salida"]:
                        get_detection_buffer(camera).cleanup()
                    tripwire.cleanup_old_tracks(max_age_seconds=30)
                    last_cleanup = time.time()
                
                frame_count += 1
                
            except Exception as e:
                logger.error(f"Detection loop error: {e}")
            
            # Maintain frame rate
            elapsed = time.time() - loop_start
            sleep_time = max(0, self.detection_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)


# Global detection loop
_detection_loop: Optional[DetectionLoop] = None


def get_detection_loop() -> DetectionLoop:
    """Get or create detection loop singleton"""
    global _detection_loop
    if _detection_loop is None:
        _detection_loop = DetectionLoop()
    return _detection_loop


def start_detection_loop():
    """Start the background detection loop"""
    loop = get_detection_loop()
    loop.start()


def stop_detection_loop():
    """Stop the background detection loop"""
    loop = get_detection_loop()
    loop.stop()


# Dependency
async def get_db():
    async for session in db_manager.get_session():
        yield session


# ============================================
# API ENDPOINTS
# ============================================

class TripwireConfig(BaseModel):
    camera: str
    name: str = "main"
    p1: Tuple[int, int]
    p2: Tuple[int, int]
    direction: str = "down"


@router.post("/detection/start")
async def start_detection():
    """Start continuous detection loop"""
    start_detection_loop()
    return {"status": "started", "message": "Detection loop running at 30 FPS"}


@router.post("/detection/stop")
async def stop_detection():
    """Stop continuous detection loop"""
    stop_detection_loop()
    return {"status": "stopped"}


@router.get("/detection/status")
async def detection_status():
    """Get detection loop status"""
    loop = get_detection_loop()
    
    buffers_stats = {}
    for camera in ["entrada", "salida"]:
        buffer = get_detection_buffer(camera)
        buffers_stats[camera] = buffer.get_stats()
    
    return {
        "running": loop.is_running,
        "fps": round(1.0 / loop.detection_interval),
        "buffers": buffers_stats
    }


@router.post("/tripwire/configure")
async def configure_tripwire(config: TripwireConfig):
    """Configure tripwire line"""
    tripwire = get_tripwire_detector()
    tripwire.add_line(
        camera=config.camera,
        name=config.name,
        p1=config.p1,
        p2=config.p2,
        direction=config.direction
    )
    _update_stream_tripwires()
    
    return {
        "status": "configured",
        "camera": config.camera,
        "line": config.name,
        "p1": config.p1,
        "p2": config.p2,
        "direction": config.direction
    }


@router.get("/tripwire/config")
async def get_tripwire_config():
    """Get current tripwire configuration"""
    tripwire = get_tripwire_detector()
    return tripwire.get_stats()


@router.delete("/tripwire/{camera}/{line_name}")
async def remove_tripwire(camera: str, line_name: str = "main"):
    """Remove a tripwire line"""
    tripwire = get_tripwire_detector()
    tripwire.remove_line(camera, line_name)
    _update_stream_tripwires()
    return {"status": "removed", "camera": camera, "line": line_name}


@router.get("/vehicles/inside")
async def get_vehicles_inside(db: AsyncSession = Depends(get_db)):
    """Get all vehicles currently inside"""
    tracker = VehicleTracker(db)
    vehicles = await tracker.get_vehicles_inside()
    return {"vehicles": [v.to_dict() for v in vehicles]}


@router.get("/vehicles/recent-exits")
async def get_recent_exits(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Get recent exits"""
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
    
    # Add detection stats
    loop = get_detection_loop()
    stats["detection"] = {
        "running": loop.is_running,
        "fps": round(1.0 / loop.detection_interval)
    }
    
    # Add buffer stats
    stats["buffers"] = {}
    for camera in ["entrada", "salida"]:
        buffer = get_detection_buffer(camera)
        stats["buffers"][camera] = buffer.get_stats()
    
    # Add tripwire stats
    tripwire = get_tripwire_detector()
    stats["tripwire"] = tripwire.get_stats()
    
    return stats
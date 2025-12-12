from .yolo_detector import YOLODetector, get_detector, Detection
from .ocr_service import LicensePlateOCR, get_ocr_service
from .tracker import VehicleTracker
from .rtsp_stream import RTSPStream, StreamManager, get_stream_manager
from .detection_cooldown import SmartDetectionCooldown, get_detection_cooldown
from .tripwire import TripwireDetector, get_tripwire_detector
from .detection_buffer import DetectionBuffer, get_detection_buffer
from .memory_manager import (
    MemoryManager,
    get_memory_manager,
    start_memory_manager,
    stop_memory_manager,
)
from app.models import DatabaseManager
from app.config import get_settings

settings = get_settings()
db_manager = DatabaseManager(settings.database_url)

async def get_db_session():
    """Dependency para obtener sesion de BD"""
    async for session in db_manager.get_session():
        yield session
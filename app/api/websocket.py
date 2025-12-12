"""
EKAIA Puerto - WebSocket Endpoint
Real-time detection updates with smart cooldown
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.services import (
    VehicleTracker,
    get_detector,
    get_ocr_service,
    get_stream_manager,
)
from app.services.detection_cooldown import get_detection_cooldown
from app.models import DatabaseManager
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

settings = get_settings()
db_manager = DatabaseManager(settings.database_url)

# Chile timezone
CHILE_TZ = timezone(timedelta(hours=-3))


class ConnectionManager:
    """Manages WebSocket connections"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
                dead_connections.append(connection)

        for conn in dead_connections:
            try:
                self.active_connections.remove(conn)
            except:
                pass


manager = ConnectionManager()


async def get_db():
    async for session in db_manager.get_session():
        yield session


@router.websocket("/ws/realtime")
async def websocket_realtime(websocket: WebSocket):
    """Real-time detection websocket with smart cooldown"""
    await manager.connect(websocket)

    try:
        # Get services
        detector = None
        ocr = None
        
        try:
            detector = get_detector(settings.yolo_model_path, settings.yolo_device, settings.yolo_confidence)
        except Exception as e:
            logger.error(f"Failed to get detector: {e}")
        
        try:
            ocr = get_ocr_service(use_gpu=settings.ocr_gpu)
        except Exception as e:
            logger.error(f"Failed to get OCR: {e}")
        
        stream_manager = get_stream_manager()
        cooldown = get_detection_cooldown()

        while True:
            try:
                async for db in get_db():
                    tracker = VehicleTracker(db)

                    results = {
                        "timestamp": datetime.now(CHILE_TZ).isoformat(),
                        "cameras": {},
                        "detection": None,
                        "stats": None
                    }

                    for camera_name in ["entrada", "salida"]:
                        stream = stream_manager.get_stream(camera_name)
                        camera_result = {
                            "connected": False,
                            "detections_count": 0,
                            "plates": []
                        }

                        if stream and stream.is_alive():
                            camera_result["connected"] = True
                            frame = stream.get_latest_frame()

                            if frame is not None and detector is not None:
                                detections = detector.detect(frame)
                                camera_result["detections_count"] = len(detections)
                                
                                plate_detections = [d for d in detections if d.class_id == 1]

                                for plate_det in plate_detections:
                                    plate_text = None
                                    ocr_conf = 0.0
                                    
                                    if ocr:
                                        try:
                                            plate_text, ocr_conf = ocr.extract_from_bbox(frame, plate_det.bbox)
                                        except Exception as e:
                                            logger.debug(f"OCR error: {e}")

                                    if plate_text and len(plate_text) >= 5:
                                        # Use smart cooldown
                                        should_register, canonical_plate = cooldown.add_detection(
                                            plate_text, 
                                            camera_name, 
                                            plate_det.confidence
                                        )
                                        
                                        plate_info = {
                                            "text": canonical_plate or plate_text,
                                            "confidence": round(plate_det.confidence, 3),
                                            "ocr_confidence": round(ocr_conf, 3)
                                        }
                                        camera_result["plates"].append(plate_info)
                                        
                                        if should_register and canonical_plate:
                                            # Send detection event
                                            results["detection"] = {
                                                "camera": camera_name,
                                                "plate": canonical_plate,
                                                "confidence": round(plate_det.confidence, 3),
                                                "ocr_confidence": round(ocr_conf, 3),
                                                "timestamp": datetime.now(CHILE_TZ).isoformat()
                                            }
                                            
                                            # Register in database
                                            try:
                                                if camera_name == "entrada":
                                                    await tracker.register_entry(canonical_plate, plate_det.confidence)
                                                    logger.info(f"ENTRADA registrada: {canonical_plate}")
                                                elif camera_name == "salida":
                                                    await tracker.register_exit(canonical_plate, plate_det.confidence)
                                                    logger.info(f"SALIDA registrada: {canonical_plate}")
                                            except Exception as e:
                                                logger.error(f"Failed to register: {e}")

                        results["cameras"][camera_name] = camera_result

                    # Get stats - always refresh
                    try:
                        stats = await tracker.get_stats()
                        results["stats"] = stats
                    except Exception as e:
                        logger.error(f"Failed to get stats: {e}")
                        results["stats"] = {
                            "vehicles_inside": 0,
                            "entries_today": 0,
                            "exits_today": 0,
                            "avg_duration_minutes": 0,
                            "current_vehicles": []
                        }

                    await websocket.send_json(results)
                    break

            except Exception as e:
                logger.error(f"WebSocket loop error: {e}")

            await asyncio.sleep(1.5)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@router.websocket("/ws/stats")
async def websocket_stats(websocket: WebSocket):
    """Stats-only websocket"""
    await manager.connect(websocket)

    try:
        while True:
            try:
                async for db in get_db():
                    tracker = VehicleTracker(db)
                    stats = await tracker.get_stats()

                    await websocket.send_json({
                        "timestamp": datetime.now(CHILE_TZ).isoformat(),
                        "stats": stats
                    })

                    break
            except Exception as e:
                logger.error(f"Stats error: {e}")

            await asyncio.sleep(5)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
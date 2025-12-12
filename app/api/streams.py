"""
EKAIA Puerto - Stream Endpoints
MJPEG streaming from RTSP cameras
"""
from fastapi import APIRouter, Response, HTTPException
from fastapi.responses import StreamingResponse
import logging

from app.services import get_stream_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stream", tags=["streams"])


@router.get("/entrada")
async def stream_entrada():
    """
    Stream from entrance camera (192.168.88.107)
    Returns MJPEG stream
    """
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream("entrada")

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail="Entrance stream not available")

    return StreamingResponse(
        stream.generate_jpeg_stream(quality=85),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/salida")
async def stream_salida():
    """
    Stream from exit camera (192.168.88.108)
    Returns MJPEG stream
    """
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream("salida")

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail="Exit stream not available")

    return StreamingResponse(
        stream.generate_jpeg_stream(quality=85),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/status")
async def stream_status():
    """Get status of all streams"""
    stream_manager = get_stream_manager()

    entrada = stream_manager.get_stream("entrada")
    salida = stream_manager.get_stream("salida")

    return {
        "entrada": {
            "connected": entrada.is_alive() if entrada else False,
            "last_frame": entrada.last_frame_time if entrada else 0
        },
        "salida": {
            "connected": salida.is_alive() if salida else False,
            "last_frame": salida.last_frame_time if salida else 0
        }
    }

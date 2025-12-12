"""
EKAIA Puerto - Stream Endpoints
MJPEG streaming from RTSP cameras with adaptive compression
"""
from fastapi import APIRouter, Response, HTTPException, Query
from fastapi.responses import StreamingResponse
import logging
from typing import Optional

from app.services import get_stream_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stream", tags=["streams"])


@router.get("/entrada")
async def stream_entrada(
    quality: int = Query(default=85, ge=10, le=100, description="JPEG quality (10-100)"),
    scale: float = Query(default=1.0, ge=0.25, le=1.0, description="Scale factor (0.25-1.0)"),
    fps: Optional[int] = Query(default=None, ge=1, le=30, description="Max FPS (1-30)")
):
    """
    Stream from entrance camera (192.168.88.107)

    Parameters:
    - quality: JPEG quality 10-100 (default 85)
      * 100: Max quality, ~5 Mbps
      * 85: High quality, ~3 Mbps (default)
      * 60: Medium quality, ~1.5 Mbps
      * 40: Low quality, ~800 Kbps
      * 20: Very low, ~400 Kbps
    - scale: Resolution scale 0.25-1.0 (default 1.0)
      * 1.0: Original resolution (default)
      * 0.75: 75% scale, ~50% bandwidth
      * 0.5: Half resolution, ~25% bandwidth
      * 0.25: Quarter resolution, minimal bandwidth
    - fps: Max FPS limit (default: unlimited)
      * Lower FPS = lower bandwidth
      * Recommended: 10-15 for remote access

    Examples:
    - Remote access: ?quality=60&scale=0.75&fps=15
    - Local network: ?quality=85 (default)
    - Low bandwidth: ?quality=40&scale=0.5&fps=10
    """
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream("entrada")

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail="Entrance stream not available")

    return StreamingResponse(
        stream.generate_jpeg_stream(quality=quality, scale=scale, max_fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/salida")
async def stream_salida(
    quality: int = Query(default=85, ge=10, le=100, description="JPEG quality (10-100)"),
    scale: float = Query(default=1.0, ge=0.25, le=1.0, description="Scale factor (0.25-1.0)"),
    fps: Optional[int] = Query(default=None, ge=1, le=30, description="Max FPS (1-30)")
):
    """
    Stream from exit camera (192.168.88.108)

    Same parameters as /entrada endpoint
    """
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream("salida")

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail="Exit stream not available")

    return StreamingResponse(
        stream.generate_jpeg_stream(quality=quality, scale=scale, max_fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/entrada/low")
async def stream_entrada_low():
    """Preset: Low bandwidth entrance stream (quality=40, scale=0.5, fps=10)"""
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream("entrada")

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail="Entrance stream not available")

    return StreamingResponse(
        stream.generate_jpeg_stream(quality=40, scale=0.5, max_fps=10),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/salida/low")
async def stream_salida_low():
    """Preset: Low bandwidth exit stream (quality=40, scale=0.5, fps=10)"""
    stream_manager = get_stream_manager()
    stream = stream_manager.get_stream("salida")

    if not stream or not stream.is_alive():
        raise HTTPException(status_code=503, detail="Exit stream not available")

    return StreamingResponse(
        stream.generate_jpeg_stream(quality=40, scale=0.5, max_fps=10),
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

"""
EKAIA Puerto - System Monitoring and Control API
Endpoints para monitoreo de recursos y gestión del sistema
"""
from fastapi import APIRouter, HTTPException
import logging
import psutil
import torch
from typing import Optional

from app.services import get_memory_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/resources")
async def get_system_resources():
    """
    Obtener uso actual de recursos del sistema

    Returns:
        - CPU usage (%)
        - RAM usage (%)
        - GPU usage (%) si está disponible
        - Disk usage (%)
        - Network stats
    """
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        # RAM
        memory = psutil.virtual_memory()
        memory_info = {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "available_gb": round(memory.available / (1024 ** 3), 2),
            "used_gb": round(memory.used / (1024 ** 3), 2),
            "percent": memory.percent,
        }

        # GPU (si está disponible)
        gpu_info = None
        if torch.cuda.is_available():
            device = torch.cuda.get_device_properties(0)
            total_memory = device.total_memory / (1024 ** 3)  # GB
            allocated_memory = torch.cuda.memory_allocated(0) / (1024 ** 3)
            cached_memory = torch.cuda.memory_reserved(0) / (1024 ** 3)

            gpu_info = {
                "name": torch.cuda.get_device_name(0),
                "total_memory_gb": round(total_memory, 2),
                "allocated_gb": round(allocated_memory, 2),
                "cached_gb": round(cached_memory, 2),
                "free_gb": round(total_memory - allocated_memory, 2),
                "percent": round((allocated_memory / total_memory) * 100, 1),
            }

        # Disk
        disk = psutil.disk_usage('/')
        disk_info = {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "percent": disk.percent,
        }

        # Network
        net_io = psutil.net_io_counters()
        network_info = {
            "bytes_sent_gb": round(net_io.bytes_sent / (1024 ** 3), 2),
            "bytes_recv_gb": round(net_io.bytes_recv / (1024 ** 3), 2),
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
        }

        return {
            "cpu": {
                "percent": cpu_percent,
                "cores": cpu_count,
            },
            "memory": memory_info,
            "gpu": gpu_info,
            "disk": disk_info,
            "network": network_info,
        }

    except Exception as e:
        logger.error(f"Error getting system resources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/stats")
async def get_memory_stats():
    """
    Obtener estadísticas del memory manager

    Returns:
        - Última limpieza
        - Total de limpiezas
        - Memoria liberada
        - Estado actual
    """
    try:
        manager = get_memory_manager()
        stats = manager.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting memory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/cleanup")
async def force_memory_cleanup():
    """
    Forzar limpieza de memoria inmediata

    Útil cuando se detecta uso alto de memoria manualmente
    """
    try:
        manager = get_memory_manager()
        await manager.force_cleanup()
        return {
            "status": "success",
            "message": "Memory cleanup completed",
            "stats": manager.get_stats(),
        }
    except Exception as e:
        logger.error(f"Error forcing memory cleanup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/detailed")
async def detailed_health_check():
    """
    Health check detallado del sistema completo

    Incluye:
    - Streams RTSP
    - Detection loop
    - Memory manager
    - Recursos del sistema
    """
    from app.services import get_stream_manager

    stream_manager = get_stream_manager()
    entrada = stream_manager.get_stream("entrada")
    salida = stream_manager.get_stream("salida")

    try:
        from app.api.detection import get_detection_loop
        detection_loop = get_detection_loop()
        detection_running = detection_loop.is_running if detection_loop else False
    except:
        detection_running = False

    try:
        memory_manager = get_memory_manager()
        memory_running = memory_manager.is_running
    except:
        memory_running = False

    # Recursos básicos
    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory_percent = psutil.virtual_memory().percent

    gpu_percent = None
    if torch.cuda.is_available():
        total = torch.cuda.get_device_properties(0).total_memory
        allocated = torch.cuda.memory_allocated(0)
        gpu_percent = round((allocated / total) * 100, 1)

    return {
        "status": "healthy",
        "services": {
            "streams": {
                "entrada": {
                    "running": entrada.is_alive() if entrada else False,
                    "last_frame": entrada.last_frame_time if entrada else 0,
                },
                "salida": {
                    "running": salida.is_alive() if salida else False,
                    "last_frame": salida.last_frame_time if salida else 0,
                },
            },
            "detection_loop": {
                "running": detection_running,
            },
            "memory_manager": {
                "running": memory_running,
            },
        },
        "resources": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "gpu_percent": gpu_percent,
        },
    }


@router.get("/performance")
async def get_performance_metrics():
    """
    Métricas de rendimiento del sistema

    Incluye:
    - FPS actual de detección
    - Latencia promedio
    - Throughput de frames
    """
    try:
        from app.api.detection import get_detection_loop
        detection_loop = get_detection_loop()

        if not detection_loop or not detection_loop.is_running:
            return {
                "status": "not_running",
                "message": "Detection loop is not running",
            }

        # Aquí podrías agregar más métricas de performance
        # Por ejemplo, contar FPS real, latencia, etc.

        return {
            "status": "running",
            "detection_loop": {
                "running": True,
                # Añadir métricas adicionales aquí si están disponibles
            },
        }

    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

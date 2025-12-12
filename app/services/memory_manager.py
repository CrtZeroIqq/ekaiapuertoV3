"""
EKAIA Puerto - Memory Manager
Automatic memory management and cleanup to prevent server saturation
"""
import asyncio
import logging
import psutil
import gc
from datetime import datetime, timedelta
from typing import Optional
import torch

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages system memory and performs automatic cleanup"""

    def __init__(
        self,
        cleanup_interval: int = 300,  # 5 minutos
        memory_threshold: float = 80.0,  # 80% uso de memoria
        gpu_memory_threshold: float = 90.0,  # 90% uso GPU
        old_logs_days: int = 30,  # Eliminar logs > 30 días
    ):
        self.cleanup_interval = cleanup_interval
        self.memory_threshold = memory_threshold
        self.gpu_memory_threshold = gpu_memory_threshold
        self.old_logs_days = old_logs_days
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = {
            "last_cleanup": None,
            "total_cleanups": 0,
            "memory_freed_mb": 0,
            "gpu_memory_freed_mb": 0,
        }

    def get_stats(self) -> dict:
        """Obtener estadísticas del memory manager"""
        return {
            **self._stats,
            "current_memory_percent": psutil.virtual_memory().percent,
            "current_gpu_memory_percent": self._get_gpu_memory_percent(),
            "is_running": self.is_running,
        }

    def _get_gpu_memory_percent(self) -> Optional[float]:
        """Obtener porcentaje de uso de memoria GPU"""
        try:
            if torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory
                allocated = torch.cuda.memory_allocated(0)
                return (allocated / total) * 100
            return None
        except Exception as e:
            logger.debug(f"Error getting GPU memory: {e}")
            return None

    async def _cleanup_memory(self):
        """Ejecutar cleanup de memoria"""
        logger.info("Starting memory cleanup...")
        initial_memory = psutil.virtual_memory().used / (1024 ** 2)  # MB

        # 1. Garbage collection de Python
        collected = gc.collect()
        logger.info(f"Garbage collected: {collected} objects")

        # 2. Limpiar cache de GPU si está disponible
        if torch.cuda.is_available():
            initial_gpu = torch.cuda.memory_allocated(0) / (1024 ** 2)  # MB
            torch.cuda.empty_cache()
            final_gpu = torch.cuda.memory_allocated(0) / (1024 ** 2)  # MB
            gpu_freed = initial_gpu - final_gpu
            self._stats["gpu_memory_freed_mb"] += gpu_freed
            logger.info(f"GPU cache cleared: {gpu_freed:.2f} MB freed")

        # 3. Forzar liberación de memoria del sistema
        final_memory = psutil.virtual_memory().used / (1024 ** 2)  # MB
        memory_freed = initial_memory - final_memory
        self._stats["memory_freed_mb"] += memory_freed

        self._stats["last_cleanup"] = datetime.now().isoformat()
        self._stats["total_cleanups"] += 1

        logger.info(f"Memory cleanup complete: {memory_freed:.2f} MB freed")

    async def _cleanup_old_database_logs(self, db_session):
        """Eliminar logs antiguos de la base de datos"""
        try:
            from app.models.database import DetectionLog
            cutoff_date = datetime.now() - timedelta(days=self.old_logs_days)

            # Contar logs a eliminar
            old_logs_count = await db_session.execute(
                f"SELECT COUNT(*) FROM detection_logs WHERE timestamp < '{cutoff_date}'"
            )
            count = old_logs_count.scalar() if old_logs_count else 0

            if count > 0:
                # Eliminar logs antiguos
                await db_session.execute(
                    f"DELETE FROM detection_logs WHERE timestamp < '{cutoff_date}'"
                )
                await db_session.commit()
                logger.info(f"Deleted {count} old detection logs (older than {self.old_logs_days} days)")
            else:
                logger.debug("No old logs to delete")

        except Exception as e:
            logger.error(f"Error cleaning up database logs: {e}")

    async def _check_and_cleanup(self):
        """Verificar uso de memoria y limpiar si es necesario"""
        # Verificar memoria RAM
        memory_percent = psutil.virtual_memory().percent
        if memory_percent >= self.memory_threshold:
            logger.warning(f"Memory usage high: {memory_percent:.1f}% - Starting cleanup")
            await self._cleanup_memory()

        # Verificar memoria GPU
        gpu_percent = self._get_gpu_memory_percent()
        if gpu_percent and gpu_percent >= self.gpu_memory_threshold:
            logger.warning(f"GPU memory usage high: {gpu_percent:.1f}% - Starting cleanup")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("GPU cache cleared")

        # Cleanup periódico ligero (cada intervalo)
        if self._stats["total_cleanups"] % 4 == 0:  # Cada 4 intervalos (20 min si interval=5min)
            gc.collect()
            logger.debug("Periodic light cleanup executed")

    async def _cleanup_loop(self):
        """Loop principal de cleanup automático"""
        logger.info(f"Memory manager started (interval: {self.cleanup_interval}s)")

        while self.is_running:
            try:
                await self._check_and_cleanup()
                await asyncio.sleep(self.cleanup_interval)

            except asyncio.CancelledError:
                logger.info("Memory manager cancelled")
                break
            except Exception as e:
                logger.error(f"Error in memory manager loop: {e}")
                await asyncio.sleep(self.cleanup_interval)

    def start(self):
        """Iniciar el memory manager"""
        if self.is_running:
            logger.warning("Memory manager already running")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info("Memory manager started")

    async def stop(self):
        """Detener el memory manager"""
        if not self.is_running:
            return

        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Memory manager stopped")

    async def force_cleanup(self):
        """Forzar cleanup inmediato (útil para endpoint manual)"""
        logger.info("Force cleanup requested")
        await self._cleanup_memory()


# Global memory manager instance
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Obtener instancia global del memory manager"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(
            cleanup_interval=300,  # 5 minutos
            memory_threshold=80.0,  # 80%
            gpu_memory_threshold=90.0,  # 90%
            old_logs_days=30,
        )
    return _memory_manager


def start_memory_manager():
    """Iniciar el memory manager global"""
    manager = get_memory_manager()
    manager.start()


async def stop_memory_manager():
    """Detener el memory manager global"""
    manager = get_memory_manager()
    await manager.stop()

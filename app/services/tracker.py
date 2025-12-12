"""
EKAIA Puerto - Vehicle Tracking Service
Manages vehicle entry/exit and duration tracking
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy import select, and_, or_, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import VehicleRecord, DetectionLog, VehicleStatus

# Chile timezone (UTC-3)
CHILE_TZ = timezone(timedelta(hours=-3))


def get_chile_now() -> datetime:
    """Get current time in Chile without timezone info for DB storage"""
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def get_today_start_chile() -> datetime:
    """Get start of today in Chile time"""
    now = get_chile_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class VehicleTracker:
    """Manages vehicle tracking logic"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def log_detection(
        self,
        camera: str,
        plate: str,
        confidence: float,
        bbox: list,
        ocr_text: Optional[str] = None
    ) -> DetectionLog:
        """Log raw detection for debugging"""
        log = DetectionLog(
            camera=camera,
            plate=plate,
            confidence=confidence,
            bbox=str(bbox),
            ocr_text=ocr_text
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def register_entry(
        self,
        plate: str,
        confidence: float,
        camera: str = "entrada"
    ) -> VehicleRecord:
        """Register vehicle entry"""
        now = get_chile_now()
        
        # Check if vehicle is already inside
        stmt = select(VehicleRecord).where(
            and_(
                VehicleRecord.plate == plate,
                VehicleRecord.status == VehicleStatus.INSIDE
            )
        ).order_by(VehicleRecord.entry_time.desc())

        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.entry_time = now
            existing.entry_confidence = confidence
            existing.updated_at = now
            record = existing
        else:
            record = VehicleRecord(
                plate=plate,
                entry_time=now,
                entry_camera=camera,
                entry_confidence=confidence,
                status=VehicleStatus.INSIDE
            )
            self.db.add(record)

        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def register_exit(
        self,
        plate: str,
        confidence: float,
        camera: str = "salida"
    ) -> Optional[VehicleRecord]:
        """Register vehicle exit"""
        now = get_chile_now()
        
        # Find active record for this plate
        stmt = select(VehicleRecord).where(
            and_(
                VehicleRecord.plate == plate,
                VehicleRecord.status == VehicleStatus.INSIDE
            )
        ).order_by(VehicleRecord.entry_time.desc())

        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            # No entry found - create exit-only record
            record = VehicleRecord(
                plate=plate,
                exit_time=now,
                exit_camera=camera,
                exit_confidence=confidence,
                status=VehicleStatus.EXITED
            )
            self.db.add(record)
        else:
            record.exit_time = now
            record.exit_camera = camera
            record.exit_confidence = confidence
            record.status = VehicleStatus.EXITED

            if record.entry_time:
                delta = record.exit_time - record.entry_time
                record.duration_minutes = delta.total_seconds() / 60

            record.updated_at = now

        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_vehicles_inside(self) -> List[VehicleRecord]:
        """Get all vehicles currently inside"""
        stmt = select(VehicleRecord).where(
            VehicleRecord.status == VehicleStatus.INSIDE
        ).order_by(VehicleRecord.entry_time.desc())

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_recent_exits(self, limit: int = 50) -> List[VehicleRecord]:
        """Get recent exits"""
        stmt = select(VehicleRecord).where(
            VehicleRecord.status == VehicleStatus.EXITED
        ).order_by(VehicleRecord.exit_time.desc()).limit(limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_vehicle_history(self, plate: str, limit: int = 10) -> List[VehicleRecord]:
        """Get history for specific plate"""
        stmt = select(VehicleRecord).where(
            VehicleRecord.plate == plate
        ).order_by(VehicleRecord.created_at.desc()).limit(limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_entries_today(self) -> int:
        """Get count of entries today - compatible with UTC and Chile time"""
        # Get today boundaries in Chile time
        today_start = get_today_start_chile()
        
        # Also check UTC equivalent (3 hours later)
        utc_today_start = today_start + timedelta(hours=3)
        
        # Query entries from either timezone
        stmt = select(func.count(VehicleRecord.id)).where(
            and_(
                VehicleRecord.entry_time.isnot(None),
                or_(
                    VehicleRecord.entry_time >= today_start,
                    VehicleRecord.entry_time >= utc_today_start
                )
            )
        )
        
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_exits_today(self) -> int:
        """Get count of exits today"""
        today_start = get_today_start_chile()
        utc_today_start = today_start + timedelta(hours=3)
        
        stmt = select(func.count(VehicleRecord.id)).where(
            and_(
                VehicleRecord.status == VehicleStatus.EXITED,
                VehicleRecord.exit_time.isnot(None),
                or_(
                    VehicleRecord.exit_time >= today_start,
                    VehicleRecord.exit_time >= utc_today_start
                )
            )
        )
        
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_stats(self) -> dict:
        """Get current statistics"""
        vehicles_inside = await self.get_vehicles_inside()
        
        # Get counts
        entries_today = await self.get_entries_today()
        exits_today = await self.get_exits_today()
        
        # Calculate average duration for exited vehicles today
        today_start = get_today_start_chile()
        utc_today_start = today_start + timedelta(hours=3)

        stmt = select(VehicleRecord).where(
            and_(
                VehicleRecord.status == VehicleStatus.EXITED,
                VehicleRecord.duration_minutes.isnot(None),
                or_(
                    VehicleRecord.exit_time >= today_start,
                    VehicleRecord.exit_time >= utc_today_start
                )
            )
        )

        result = await self.db.execute(stmt)
        exited_with_duration = list(result.scalars().all())

        avg_duration = 0
        if exited_with_duration:
            avg_duration = sum(v.duration_minutes for v in exited_with_duration) / len(exited_with_duration)

        return {
            "vehicles_inside": len(vehicles_inside),
            "entries_today": entries_today,
            "exits_today": exits_today,
            "avg_duration_minutes": round(avg_duration, 2),
            "current_vehicles": [v.to_dict() for v in vehicles_inside]
        }
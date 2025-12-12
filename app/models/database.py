"""
EKAIA Puerto - Database Models
SQLAlchemy models for vehicle tracking
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Float, Enum, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import enum

Base = declarative_base()


class VehicleStatus(str, enum.Enum):
    """Vehicle status enum"""
    INSIDE = "inside"
    EXITED = "exited"
    UNKNOWN = "unknown"


class VehicleRecord(Base):
    """Vehicle entry/exit tracking"""
    __tablename__ = "vehicle_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plate = Column(String(20), nullable=False, index=True)

    # Timestamps
    entry_time = Column(DateTime, nullable=True, index=True)
    exit_time = Column(DateTime, nullable=True)

    # Duration in minutes
    duration_minutes = Column(Float, nullable=True)

    # Status
    status = Column(Enum(VehicleStatus), default=VehicleStatus.UNKNOWN, index=True)

    # Camera IDs
    entry_camera = Column(String(50), default="entrada")
    exit_camera = Column(String(50), default="salida")

    # Detection confidence
    entry_confidence = Column(Float, nullable=True)
    exit_confidence = Column(Float, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<VehicleRecord(plate={self.plate}, status={self.status})>"

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "id": self.id,
            "plate": self.plate,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "duration_minutes": self.duration_minutes,
            "status": self.status.value,
            "entry_camera": self.entry_camera,
            "exit_camera": self.exit_camera,
            "entry_confidence": self.entry_confidence,
            "exit_confidence": self.exit_confidence,
        }


class DetectionLog(Base):
    """Raw detection logs for debugging"""
    __tablename__ = "detection_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera = Column(String(50), nullable=False, index=True)
    plate = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)
    ocr_text = Column(String(100), nullable=True)
    bbox = Column(String(200), nullable=True)  # JSON string [x1,y1,x2,y2]
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<DetectionLog(camera={self.camera}, plate={self.plate}, time={self.timestamp})>"


# Database engine setup
class DatabaseManager:
    """Async database manager"""

    def __init__(self, database_url: str):
        self.engine = create_async_engine(
            database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def init_db(self):
        """Create tables if they don't exist"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_session(self) -> AsyncSession:
        """Get async session"""
        async with self.async_session() as session:
            yield session

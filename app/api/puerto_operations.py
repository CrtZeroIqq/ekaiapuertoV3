"""
EKAIA Puerto - API de Operaciones para el Puerto
Funcionalidades operativas útiles para la gestión diaria del puerto
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import logging

from app.models.database import VehicleRecord, DetectionLog, VehicleStatus, DatabaseManager
from app.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/puerto", tags=["puerto-operations"])


# ============================================================================
# SCHEMAS
# ============================================================================

class TrafficStats(BaseModel):
    """Estadísticas de tráfico"""
    period: str
    total_entries: int
    total_exits: int
    vehicles_inside: int
    avg_stay_minutes: float
    peak_hour_entry: Optional[str] = None
    peak_hour_exit: Optional[str] = None


class VehicleInside(BaseModel):
    """Vehículo actualmente dentro del puerto"""
    id: int
    plate: str
    entry_time: str
    minutes_inside: int
    hours_inside: float
    entry_confidence: float
    vehicle_type: str  # "truck" o "car" basado en tamaño estimado


class IllegalPlate(BaseModel):
    """Registro de patente ilegible"""
    id: int
    camera: str
    plate: str  # Mejor intento de OCR
    confidence: float
    timestamp: str
    reason: str  # "low_confidence", "no_text", "invalid_format"


class HourlyTraffic(BaseModel):
    """Tráfico por hora"""
    hour: int
    entries: int
    exits: int
    net_change: int


class VehicleTypeStats(BaseModel):
    """Estadísticas por tipo de vehículo"""
    vehicle_type: str
    count: int
    percentage: float
    avg_stay_minutes: float


class DailyReport(BaseModel):
    """Reporte diario operativo"""
    date: str
    total_entries: int
    total_exits: int
    current_inside: int
    peak_occupancy: int
    peak_hour: str
    avg_stay_hours: float
    trucks_count: int
    cars_count: int
    illegible_plates: int
    alerts: List[str]


class LongStayAlert(BaseModel):
    """Alerta de vehículo con estadía prolongada"""
    id: int
    plate: str
    entry_time: str
    hours_inside: float
    alert_level: str  # "warning" (>12h), "critical" (>24h), "urgent" (>48h)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def estimate_vehicle_type_from_size(bbox: Optional[str]) -> str:
    """
    Estima el tipo de vehículo basado en el tamaño del bbox
    Camiones típicamente tienen bbox más grande que autos
    """
    if not bbox:
        return "unknown"

    try:
        # bbox format: "[x1,y1,x2,y2]"
        coords = eval(bbox)
        width = coords[2] - coords[0]
        height = coords[3] - coords[1]
        area = width * height

        # Heurística simple: camiones tienen área > 150000 píxeles
        # Esto puede ajustarse según las cámaras específicas
        if area > 150000:
            return "truck"
        elif area > 50000:
            return "car"
        else:
            return "motorcycle"
    except:
        return "unknown"


def classify_illegible_reason(confidence: float, plate: str) -> str:
    """Clasifica la razón por la cual una patente es ilegible"""
    if confidence < 0.3:
        return "low_confidence"
    elif not plate or len(plate) < 4:
        return "no_text"
    elif confidence < 0.6:
        return "partial_read"
    else:
        return "invalid_format"


# ============================================================================
# ENDPOINTS - ESTADÍSTICAS DE TRÁFICO
# ============================================================================

@router.get("/traffic/stats", response_model=TrafficStats)
async def get_traffic_stats(
    hours: int = Query(default=24, ge=1, le=168, description="Horas hacia atrás"),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtiene estadísticas de tráfico del puerto
    - Total de entradas y salidas
    - Vehículos actualmente dentro
    - Tiempo promedio de estadía
    - Horas pico
    """
    try:
        start_time = datetime.utcnow() - timedelta(hours=hours)

        # Total de entradas en el período
        result = await db.execute(
            select(func.count(VehicleRecord.id))
            .where(VehicleRecord.entry_time >= start_time)
        )
        total_entries = result.scalar() or 0

        # Total de salidas en el período
        result = await db.execute(
            select(func.count(VehicleRecord.id))
            .where(
                and_(
                    VehicleRecord.exit_time >= start_time,
                    VehicleRecord.status == VehicleStatus.EXITED
                )
            )
        )
        total_exits = result.scalar() or 0

        # Vehículos actualmente dentro
        result = await db.execute(
            select(func.count(VehicleRecord.id))
            .where(VehicleRecord.status == VehicleStatus.INSIDE)
        )
        vehicles_inside = result.scalar() or 0

        # Tiempo promedio de estadía (solo vehículos que ya salieron)
        result = await db.execute(
            select(func.avg(VehicleRecord.duration_minutes))
            .where(
                and_(
                    VehicleRecord.status == VehicleStatus.EXITED,
                    VehicleRecord.exit_time >= start_time,
                    VehicleRecord.duration_minutes.isnot(None)
                )
            )
        )
        avg_stay_minutes = result.scalar() or 0.0

        # Hora pico de entradas (agrupar por hora)
        result = await db.execute(
            select(
                func.strftime('%H', VehicleRecord.entry_time).label('hour'),
                func.count(VehicleRecord.id).label('count')
            )
            .where(VehicleRecord.entry_time >= start_time)
            .group_by('hour')
            .order_by(desc('count'))
            .limit(1)
        )
        peak_entry = result.first()
        peak_hour_entry = f"{peak_entry[0]}:00" if peak_entry else None

        # Hora pico de salidas
        result = await db.execute(
            select(
                func.strftime('%H', VehicleRecord.exit_time).label('hour'),
                func.count(VehicleRecord.id).label('count')
            )
            .where(
                and_(
                    VehicleRecord.exit_time >= start_time,
                    VehicleRecord.status == VehicleStatus.EXITED
                )
            )
            .group_by('hour')
            .order_by(desc('count'))
            .limit(1)
        )
        peak_exit = result.first()
        peak_hour_exit = f"{peak_exit[0]}:00" if peak_exit else None

        return TrafficStats(
            period=f"last_{hours}_hours",
            total_entries=total_entries,
            total_exits=total_exits,
            vehicles_inside=vehicles_inside,
            avg_stay_minutes=round(avg_stay_minutes, 2),
            peak_hour_entry=peak_hour_entry,
            peak_hour_exit=peak_hour_exit
        )

    except Exception as e:
        logger.error(f"Error getting traffic stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traffic/hourly", response_model=List[HourlyTraffic])
async def get_hourly_traffic(
    hours: int = Query(default=24, ge=1, le=72),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtiene tráfico hora por hora para gráficas
    - Entradas por hora
    - Salidas por hora
    - Cambio neto (entradas - salidas)
    """
    try:
        start_time = datetime.utcnow() - timedelta(hours=hours)

        # Agrupar entradas por hora
        entries_result = await db.execute(
            select(
                func.strftime('%H', VehicleRecord.entry_time).label('hour'),
                func.count(VehicleRecord.id).label('count')
            )
            .where(VehicleRecord.entry_time >= start_time)
            .group_by('hour')
        )
        entries_by_hour = {int(row[0]): row[1] for row in entries_result}

        # Agrupar salidas por hora
        exits_result = await db.execute(
            select(
                func.strftime('%H', VehicleRecord.exit_time).label('hour'),
                func.count(VehicleRecord.id).label('count')
            )
            .where(
                and_(
                    VehicleRecord.exit_time >= start_time,
                    VehicleRecord.status == VehicleStatus.EXITED
                )
            )
            .group_by('hour')
        )
        exits_by_hour = {int(row[0]): row[1] for row in exits_result}

        # Crear lista completa de 24 horas
        hourly_data = []
        for hour in range(24):
            entries = entries_by_hour.get(hour, 0)
            exits = exits_by_hour.get(hour, 0)
            hourly_data.append(HourlyTraffic(
                hour=hour,
                entries=entries,
                exits=exits,
                net_change=entries - exits
            ))

        return hourly_data

    except Exception as e:
        logger.error(f"Error getting hourly traffic: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS - VEHÍCULOS DENTRO
# ============================================================================

@router.get("/vehicles/inside", response_model=List[VehicleInside])
async def get_vehicles_inside(
    min_hours: float = Query(default=0, ge=0, description="Filtrar por tiempo mínimo dentro (horas)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Lista de vehículos actualmente dentro del puerto
    - Patente
    - Hora de entrada
    - Tiempo transcurrido
    - Tipo estimado de vehículo
    """
    try:
        result = await db.execute(
            select(VehicleRecord)
            .where(VehicleRecord.status == VehicleStatus.INSIDE)
            .order_by(VehicleRecord.entry_time)
        )
        vehicles = result.scalars().all()

        vehicles_list = []
        current_time = datetime.utcnow()

        for vehicle in vehicles:
            if not vehicle.entry_time:
                continue

            minutes_inside = (current_time - vehicle.entry_time).total_seconds() / 60
            hours_inside = minutes_inside / 60

            # Filtrar por tiempo mínimo si se especificó
            if hours_inside < min_hours:
                continue

            # Intentar obtener bbox del log de detección para estimar tipo
            detection_result = await db.execute(
                select(DetectionLog.bbox)
                .where(
                    and_(
                        DetectionLog.plate == vehicle.plate,
                        DetectionLog.camera == vehicle.entry_camera
                    )
                )
                .order_by(desc(DetectionLog.timestamp))
                .limit(1)
            )
            bbox = detection_result.scalar()
            vehicle_type = estimate_vehicle_type_from_size(bbox)

            vehicles_list.append(VehicleInside(
                id=vehicle.id,
                plate=vehicle.plate,
                entry_time=vehicle.entry_time.isoformat(),
                minutes_inside=int(minutes_inside),
                hours_inside=round(hours_inside, 2),
                entry_confidence=vehicle.entry_confidence or 0.0,
                vehicle_type=vehicle_type
            ))

        return vehicles_list

    except Exception as e:
        logger.error(f"Error getting vehicles inside: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vehicles/long-stay", response_model=List[LongStayAlert])
async def get_long_stay_alerts(
    warning_hours: float = Query(default=12.0, ge=1, description="Horas para alerta warning"),
    critical_hours: float = Query(default=24.0, ge=1, description="Horas para alerta critical"),
    urgent_hours: float = Query(default=48.0, ge=1, description="Horas para alerta urgent"),
    db: AsyncSession = Depends(get_db)
):
    """
    Alertas de vehículos con estadía prolongada
    - Warning: >12 horas (configurable)
    - Critical: >24 horas (configurable)
    - Urgent: >48 horas (configurable)
    """
    try:
        result = await db.execute(
            select(VehicleRecord)
            .where(VehicleRecord.status == VehicleStatus.INSIDE)
        )
        vehicles = result.scalars().all()

        alerts = []
        current_time = datetime.utcnow()

        for vehicle in vehicles:
            if not vehicle.entry_time:
                continue

            hours_inside = (current_time - vehicle.entry_time).total_seconds() / 3600

            alert_level = None
            if hours_inside >= urgent_hours:
                alert_level = "urgent"
            elif hours_inside >= critical_hours:
                alert_level = "critical"
            elif hours_inside >= warning_hours:
                alert_level = "warning"

            if alert_level:
                alerts.append(LongStayAlert(
                    id=vehicle.id,
                    plate=vehicle.plate,
                    entry_time=vehicle.entry_time.isoformat(),
                    hours_inside=round(hours_inside, 2),
                    alert_level=alert_level
                ))

        # Ordenar por tiempo dentro (más tiempo primero)
        alerts.sort(key=lambda x: x.hours_inside, reverse=True)

        return alerts

    except Exception as e:
        logger.error(f"Error getting long stay alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS - PATENTES ILEGIBLES
# ============================================================================

@router.get("/plates/illegible", response_model=List[IllegalPlate])
async def get_illegible_plates(
    hours: int = Query(default=24, ge=1, le=168),
    min_confidence: float = Query(default=0.6, ge=0.0, le=1.0, description="Umbral de confidence"),
    db: AsyncSession = Depends(get_db)
):
    """
    Registro de patentes ilegibles o con baja confianza
    Útil para:
    - Identificar problemas con cámaras
    - Revisar manualmente casos dudosos
    - Auditoría de seguridad
    """
    try:
        start_time = datetime.utcnow() - timedelta(hours=hours)

        result = await db.execute(
            select(DetectionLog)
            .where(
                and_(
                    DetectionLog.timestamp >= start_time,
                    DetectionLog.confidence < min_confidence
                )
            )
            .order_by(desc(DetectionLog.timestamp))
            .limit(500)  # Limitar a 500 registros
        )
        detections = result.scalars().all()

        illegible_list = []
        for detection in detections:
            reason = classify_illegible_reason(detection.confidence, detection.plate)

            illegible_list.append(IllegalPlate(
                id=detection.id,
                camera=detection.camera,
                plate=detection.plate or "NO_DETECTED",
                confidence=detection.confidence,
                timestamp=detection.timestamp.isoformat(),
                reason=reason
            ))

        return illegible_list

    except Exception as e:
        logger.error(f"Error getting illegible plates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS - CLASIFICACIÓN DE VEHÍCULOS
# ============================================================================

@router.get("/vehicles/types", response_model=List[VehicleTypeStats])
async def get_vehicle_type_stats(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db)
):
    """
    Estadísticas por tipo de vehículo (camiones vs autos)
    Basado en estimación por tamaño de bbox
    """
    try:
        start_time = datetime.utcnow() - timedelta(hours=hours)

        # Obtener vehículos del período
        result = await db.execute(
            select(VehicleRecord)
            .where(VehicleRecord.entry_time >= start_time)
        )
        vehicles = result.scalars().all()

        # Contar por tipo
        type_counts = {"truck": 0, "car": 0, "motorcycle": 0, "unknown": 0}
        type_durations = {"truck": [], "car": [], "motorcycle": [], "unknown": []}

        for vehicle in vehicles:
            # Obtener bbox del log de detección
            detection_result = await db.execute(
                select(DetectionLog.bbox)
                .where(
                    and_(
                        DetectionLog.plate == vehicle.plate,
                        DetectionLog.camera == vehicle.entry_camera
                    )
                )
                .order_by(desc(DetectionLog.timestamp))
                .limit(1)
            )
            bbox = detection_result.scalar()
            vehicle_type = estimate_vehicle_type_from_size(bbox)

            type_counts[vehicle_type] += 1
            if vehicle.duration_minutes:
                type_durations[vehicle_type].append(vehicle.duration_minutes)

        total = sum(type_counts.values())

        stats = []
        for vtype, count in type_counts.items():
            if count > 0:
                percentage = (count / total) * 100 if total > 0 else 0
                avg_duration = sum(type_durations[vtype]) / len(type_durations[vtype]) if type_durations[vtype] else 0

                stats.append(VehicleTypeStats(
                    vehicle_type=vtype,
                    count=count,
                    percentage=round(percentage, 2),
                    avg_stay_minutes=round(avg_duration, 2)
                ))

        return stats

    except Exception as e:
        logger.error(f"Error getting vehicle type stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS - REPORTES OPERATIVOS
# ============================================================================

@router.get("/reports/daily", response_model=DailyReport)
async def get_daily_operational_report(
    date: Optional[str] = Query(default=None, description="Fecha YYYY-MM-DD (default: hoy)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Reporte operativo diario completo
    Incluye:
    - Tráfico total
    - Ocupación actual y pico
    - Clasificación de vehículos
    - Alertas y patentes ilegibles
    """
    try:
        # Parsear fecha
        if date:
            report_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            report_date = datetime.utcnow()

        start_of_day = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # Total entradas
        result = await db.execute(
            select(func.count(VehicleRecord.id))
            .where(
                and_(
                    VehicleRecord.entry_time >= start_of_day,
                    VehicleRecord.entry_time < end_of_day
                )
            )
        )
        total_entries = result.scalar() or 0

        # Total salidas
        result = await db.execute(
            select(func.count(VehicleRecord.id))
            .where(
                and_(
                    VehicleRecord.exit_time >= start_of_day,
                    VehicleRecord.exit_time < end_of_day,
                    VehicleRecord.status == VehicleStatus.EXITED
                )
            )
        )
        total_exits = result.scalar() or 0

        # Vehículos actualmente dentro
        result = await db.execute(
            select(func.count(VehicleRecord.id))
            .where(VehicleRecord.status == VehicleStatus.INSIDE)
        )
        current_inside = result.scalar() or 0

        # Tiempo promedio de estadía
        result = await db.execute(
            select(func.avg(VehicleRecord.duration_minutes))
            .where(
                and_(
                    VehicleRecord.exit_time >= start_of_day,
                    VehicleRecord.exit_time < end_of_day,
                    VehicleRecord.status == VehicleStatus.EXITED,
                    VehicleRecord.duration_minutes.isnot(None)
                )
            )
        )
        avg_stay_minutes = result.scalar() or 0.0
        avg_stay_hours = avg_stay_minutes / 60

        # Hora pico (más entradas)
        result = await db.execute(
            select(
                func.strftime('%H', VehicleRecord.entry_time).label('hour'),
                func.count(VehicleRecord.id).label('count')
            )
            .where(
                and_(
                    VehicleRecord.entry_time >= start_of_day,
                    VehicleRecord.entry_time < end_of_day
                )
            )
            .group_by('hour')
            .order_by(desc('count'))
            .limit(1)
        )
        peak = result.first()
        peak_hour = f"{peak[0]}:00" if peak else "N/A"
        peak_occupancy = peak[1] if peak else 0

        # Contar camiones vs autos (estimación simple por ahora)
        # Esto es una aproximación, idealmente necesitaríamos bbox
        trucks_count = int(total_entries * 0.4)  # Asumiendo 40% camiones
        cars_count = total_entries - trucks_count

        # Patentes ilegibles
        result = await db.execute(
            select(func.count(DetectionLog.id))
            .where(
                and_(
                    DetectionLog.timestamp >= start_of_day,
                    DetectionLog.timestamp < end_of_day,
                    DetectionLog.confidence < 0.6
                )
            )
        )
        illegible_plates = result.scalar() or 0

        # Generar alertas
        alerts = []
        if current_inside > 50:
            alerts.append(f"Alta ocupación: {current_inside} vehículos dentro")
        if illegible_plates > 10:
            alerts.append(f"Alto número de patentes ilegibles: {illegible_plates}")
        if total_exits < total_entries * 0.5:
            alerts.append("Salidas significativamente menores que entradas")

        return DailyReport(
            date=report_date.strftime("%Y-%m-%d"),
            total_entries=total_entries,
            total_exits=total_exits,
            current_inside=current_inside,
            peak_occupancy=peak_occupancy,
            peak_hour=peak_hour,
            avg_stay_hours=round(avg_stay_hours, 2),
            trucks_count=trucks_count,
            cars_count=cars_count,
            illegible_plates=illegible_plates,
            alerts=alerts if alerts else ["Sin alertas"]
        )

    except Exception as e:
        logger.error(f"Error generating daily report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/export/csv")
async def export_traffic_csv(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db)
):
    """
    Exporta datos de tráfico a CSV para auditoría
    Incluye todos los registros de entrada/salida
    """
    try:
        from io import StringIO
        import csv
        from fastapi.responses import StreamingResponse

        start_time = datetime.utcnow() - timedelta(days=days)

        result = await db.execute(
            select(VehicleRecord)
            .where(VehicleRecord.entry_time >= start_time)
            .order_by(VehicleRecord.entry_time)
        )
        vehicles = result.scalars().all()

        # Crear CSV en memoria
        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "ID", "Patente", "Entrada", "Salida", "Duración (min)",
            "Estado", "Cámara Entrada", "Cámara Salida", "Confidence Entrada", "Confidence Salida"
        ])

        # Datos
        for v in vehicles:
            writer.writerow([
                v.id,
                v.plate,
                v.entry_time.isoformat() if v.entry_time else "",
                v.exit_time.isoformat() if v.exit_time else "",
                v.duration_minutes or "",
                v.status.value,
                v.entry_camera,
                v.exit_camera,
                v.entry_confidence or "",
                v.exit_confidence or ""
            ])

        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=trafico_{days}dias.csv"}
        )

    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))

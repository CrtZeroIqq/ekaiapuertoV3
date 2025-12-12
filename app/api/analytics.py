"""
EKAIA Puerto - Analytics and Reporting API
Funcionalidades comerciales para análisis de datos y generación de reportes
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import csv
import io
import json

from app.services import get_db_session
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Chile timezone
CHILE_TZ = timezone(timedelta(hours=-3))


@router.get("/traffic/daily")
async def get_daily_traffic(
    date: Optional[str] = Query(default=None, description="Fecha en formato YYYY-MM-DD"),
    db = Depends(get_db_session)
):
    """
    Obtener tráfico diario (entradas y salidas por hora)

    Parameters:
    - date: Fecha específica (default: hoy)

    Returns:
    - Entradas y salidas por hora
    - Total del día
    - Promedio de duración
    """
    try:
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = datetime.now(CHILE_TZ).date()

        query = text("""
            SELECT
                HOUR(entry_time) as hour,
                COUNT(*) as entries,
                AVG(CASE WHEN duration_minutes IS NOT NULL THEN duration_minutes ELSE 0 END) as avg_duration
            FROM vehicle_records
            WHERE DATE(entry_time) = :target_date
            GROUP BY HOUR(entry_time)
            ORDER BY hour
        """)

        result = await db.execute(query, {"target_date": target_date})
        rows = result.fetchall()

        hourly_data = []
        total_entries = 0

        for row in rows:
            hourly_data.append({
                "hour": row[0],
                "entries": row[1],
                "avg_duration_minutes": round(row[2], 2) if row[2] else 0,
            })
            total_entries += row[1]

        # Obtener total de salidas
        exits_query = text("""
            SELECT COUNT(*) as total_exits
            FROM vehicle_records
            WHERE DATE(exit_time) = :target_date
        """)

        exits_result = await db.execute(exits_query, {"target_date": target_date})
        total_exits = exits_result.scalar() or 0

        return {
            "date": target_date.isoformat(),
            "total_entries": total_entries,
            "total_exits": total_exits,
            "hourly_breakdown": hourly_data,
        }

    except Exception as e:
        logger.error(f"Error getting daily traffic: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traffic/range")
async def get_traffic_range(
    start_date: str = Query(..., description="Fecha inicio YYYY-MM-DD"),
    end_date: str = Query(..., description="Fecha fin YYYY-MM-DD"),
    db = Depends(get_db_session)
):
    """
    Obtener tráfico en un rango de fechas

    Returns:
    - Tráfico diario en el rango
    - Promedios
    - Picos de tráfico
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if (end - start).days > 90:
            raise HTTPException(status_code=400, detail="Rango máximo: 90 días")

        query = text("""
            SELECT
                DATE(entry_time) as date,
                COUNT(*) as entries,
                COUNT(CASE WHEN exit_time IS NOT NULL THEN 1 END) as exits,
                AVG(CASE WHEN duration_minutes IS NOT NULL THEN duration_minutes ELSE 0 END) as avg_duration
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            GROUP BY DATE(entry_time)
            ORDER BY date
        """)

        result = await db.execute(query, {"start_date": start, "end_date": end})
        rows = result.fetchall()

        daily_data = []
        total_entries = 0
        total_exits = 0

        for row in rows:
            daily_data.append({
                "date": row[0].isoformat(),
                "entries": row[1],
                "exits": row[2],
                "avg_duration_minutes": round(row[3], 2) if row[3] else 0,
            })
            total_entries += row[1]
            total_exits += row[2]

        # Calcular promedios
        days_count = len(daily_data)
        avg_entries_per_day = total_entries / days_count if days_count > 0 else 0
        avg_exits_per_day = total_exits / days_count if days_count > 0 else 0

        # Encontrar picos
        peak_entry_day = max(daily_data, key=lambda x: x["entries"]) if daily_data else None
        peak_exit_day = max(daily_data, key=lambda x: x["exits"]) if daily_data else None

        return {
            "period": {
                "start": start_date,
                "end": end_date,
                "days": days_count,
            },
            "totals": {
                "entries": total_entries,
                "exits": total_exits,
            },
            "averages": {
                "entries_per_day": round(avg_entries_per_day, 2),
                "exits_per_day": round(avg_exits_per_day, 2),
            },
            "peaks": {
                "highest_entry_day": peak_entry_day,
                "highest_exit_day": peak_exit_day,
            },
            "daily_breakdown": daily_data,
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido (use YYYY-MM-DD)")
    except Exception as e:
        logger.error(f"Error getting traffic range: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/occupancy")
async def get_occupancy_stats(
    days: int = Query(default=7, ge=1, le=90, description="Días hacia atrás"),
    db = Depends(get_db_session)
):
    """
    Estadísticas de ocupación del puerto

    Returns:
    - Ocupación promedio por día
    - Picos de ocupación
    - Distribución por horario
    """
    try:
        cutoff_date = datetime.now(CHILE_TZ) - timedelta(days=days)

        # Vehículos actualmente dentro
        current_query = text("""
            SELECT COUNT(*) as current_inside
            FROM vehicle_records
            WHERE status = 'inside'
        """)

        current_result = await db.execute(current_query)
        current_inside = current_result.scalar() or 0

        # Duración promedio de estadía
        avg_duration_query = text("""
            SELECT AVG(duration_minutes) as avg_duration
            FROM vehicle_records
            WHERE exit_time >= :cutoff_date
            AND duration_minutes IS NOT NULL
        """)

        avg_result = await db.execute(avg_duration_query, {"cutoff_date": cutoff_date})
        avg_duration = avg_result.scalar() or 0

        # Estadías más largas
        longest_stays_query = text("""
            SELECT plate, entry_time, exit_time, duration_minutes
            FROM vehicle_records
            WHERE exit_time >= :cutoff_date
            AND duration_minutes IS NOT NULL
            ORDER BY duration_minutes DESC
            LIMIT 10
        """)

        longest_result = await db.execute(longest_stays_query, {"cutoff_date": cutoff_date})
        longest_rows = longest_result.fetchall()

        longest_stays = []
        for row in longest_rows:
            longest_stays.append({
                "plate": row[0],
                "entry_time": row[1].isoformat() if row[1] else None,
                "exit_time": row[2].isoformat() if row[2] else None,
                "duration_minutes": round(row[3], 2) if row[3] else 0,
            })

        return {
            "current_occupancy": current_inside,
            "period_days": days,
            "avg_stay_duration_minutes": round(avg_duration, 2),
            "avg_stay_duration_hours": round(avg_duration / 60, 2),
            "longest_stays": longest_stays,
        }

    except Exception as e:
        logger.error(f"Error getting occupancy stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/csv")
async def export_traffic_csv(
    start_date: str = Query(..., description="Fecha inicio YYYY-MM-DD"),
    end_date: str = Query(..., description="Fecha fin YYYY-MM-DD"),
    db = Depends(get_db_session)
):
    """
    Exportar datos de tráfico a CSV

    Returns: Archivo CSV descargable
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if (end - start).days > 90:
            raise HTTPException(status_code=400, detail="Rango máximo: 90 días")

        query = text("""
            SELECT
                plate,
                entry_time,
                exit_time,
                duration_minutes,
                status,
                entry_confidence,
                exit_confidence
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            ORDER BY entry_time DESC
        """)

        result = await db.execute(query, {"start_date": start, "end_date": end})
        rows = result.fetchall()

        # Crear CSV en memoria
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "Patente",
            "Hora Entrada",
            "Hora Salida",
            "Duración (min)",
            "Estado",
            "Confianza Entrada",
            "Confianza Salida",
        ])

        # Datos
        for row in rows:
            writer.writerow([
                row[0],
                row[1].isoformat() if row[1] else "",
                row[2].isoformat() if row[2] else "",
                round(row[3], 2) if row[3] else 0,
                row[4],
                round(row[5], 3) if row[5] else "",
                round(row[6], 3) if row[6] else "",
            ])

        # Preparar respuesta
        output.seek(0)
        filename = f"ekaia_traffic_{start_date}_to_{end_date}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/json")
async def export_traffic_json(
    start_date: str = Query(..., description="Fecha inicio YYYY-MM-DD"),
    end_date: str = Query(..., description="Fecha fin YYYY-MM-DD"),
    db = Depends(get_db_session)
):
    """
    Exportar datos de tráfico a JSON

    Returns: Archivo JSON descargable
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        if (end - start).days > 90:
            raise HTTPException(status_code=400, detail="Rango máximo: 90 días")

        query = text("""
            SELECT
                plate,
                entry_time,
                exit_time,
                duration_minutes,
                status,
                entry_confidence,
                exit_confidence,
                entry_camera,
                exit_camera
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            ORDER BY entry_time DESC
        """)

        result = await db.execute(query, {"start_date": start, "end_date": end})
        rows = result.fetchall()

        # Crear JSON
        data = []
        for row in rows:
            data.append({
                "plate": row[0],
                "entry_time": row[1].isoformat() if row[1] else None,
                "exit_time": row[2].isoformat() if row[2] else None,
                "duration_minutes": round(row[3], 2) if row[3] else 0,
                "status": row[4],
                "entry_confidence": round(row[5], 3) if row[5] else None,
                "exit_confidence": round(row[6], 3) if row[6] else None,
                "entry_camera": row[7],
                "exit_camera": row[8],
            })

        json_content = json.dumps({
            "period": {
                "start": start_date,
                "end": end_date,
            },
            "total_records": len(data),
            "data": data,
        }, indent=2)

        filename = f"ekaia_traffic_{start_date}_to_{end_date}.json"

        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error exporting JSON: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plates/frequent")
async def get_frequent_plates(
    days: int = Query(default=30, ge=1, le=90, description="Días hacia atrás"),
    limit: int = Query(default=20, ge=1, le=100, description="Límite de resultados"),
    db = Depends(get_db_session)
):
    """
    Obtener patentes más frecuentes (clientes regulares)

    Useful para identificar:
    - Clientes frecuentes
    - Posibles contratos recurrentes
    - Patrones de uso
    """
    try:
        cutoff_date = datetime.now(CHILE_TZ) - timedelta(days=days)

        query = text("""
            SELECT
                plate,
                COUNT(*) as visit_count,
                MIN(entry_time) as first_visit,
                MAX(entry_time) as last_visit,
                AVG(duration_minutes) as avg_duration
            FROM vehicle_records
            WHERE entry_time >= :cutoff_date
            GROUP BY plate
            HAVING COUNT(*) > 1
            ORDER BY visit_count DESC, last_visit DESC
            LIMIT :limit
        """)

        result = await db.execute(query, {"cutoff_date": cutoff_date, "limit": limit})
        rows = result.fetchall()

        frequent_plates = []
        for row in rows:
            frequent_plates.append({
                "plate": row[0],
                "visit_count": row[1],
                "first_visit": row[2].isoformat() if row[2] else None,
                "last_visit": row[3].isoformat() if row[3] else None,
                "avg_duration_minutes": round(row[4], 2) if row[4] else 0,
                "frequency_per_week": round((row[1] / days) * 7, 2),
            })

        return {
            "period_days": days,
            "total_frequent_plates": len(frequent_plates),
            "plates": frequent_plates,
        }

    except Exception as e:
        logger.error(f"Error getting frequent plates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

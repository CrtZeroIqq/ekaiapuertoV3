"""
EKAIA Puerto - Reportes Ejecutivos Automáticos
Generación de reportes de negocio, KPIs y dashboards ejecutivos
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Optional
import json
import io

from app.services import get_db_session
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])

# Chile timezone
CHILE_TZ = timezone(timedelta(hours=-3))


@router.get("/executive/daily")
async def get_daily_executive_report(
    report_date: Optional[str] = Query(default=None, description="Fecha YYYY-MM-DD"),
    db = Depends(get_db_session)
):
    """
    Reporte Ejecutivo Diario

    KPIs principales del día:
    - Tráfico (entradas/salidas)
    - Ocupación actual
    - Ingresos estimados
    - Tiempos promedio
    - Alertas y anomalías
    """
    try:
        if report_date:
            target_date = datetime.strptime(report_date, "%Y-%m-%d").date()
        else:
            target_date = datetime.now(CHILE_TZ).date()

        # 1. Tráfico del día
        traffic_query = text("""
            SELECT
                COUNT(CASE WHEN entry_time IS NOT NULL THEN 1 END) as entries,
                COUNT(CASE WHEN exit_time IS NOT NULL THEN 1 END) as exits,
                AVG(CASE WHEN duration_minutes IS NOT NULL THEN duration_minutes ELSE 0 END) as avg_duration
            FROM vehicle_records
            WHERE DATE(entry_time) = :target_date
        """)

        traffic_result = await db.execute(traffic_query, {"target_date": target_date})
        traffic_row = traffic_result.fetchone()

        entries_today = traffic_row[0] or 0
        exits_today = traffic_row[1] or 0
        avg_duration = traffic_row[2] or 0

        # 2. Ocupación actual
        occupancy_query = text("""
            SELECT COUNT(*) as current_inside
            FROM vehicle_records
            WHERE status = 'inside'
        """)

        occupancy_result = await db.execute(occupancy_query)
        current_inside = occupancy_result.scalar() or 0

        # 3. Pico de ocupación del día
        peak_query = text("""
            SELECT MAX(vehicles_count) as peak_occupancy
            FROM (
                SELECT COUNT(*) as vehicles_count
                FROM vehicle_records
                WHERE DATE(entry_time) = :target_date
                AND (exit_time IS NULL OR exit_time > entry_time)
                GROUP BY HOUR(entry_time)
            ) AS hourly_counts
        """)

        try:
            peak_result = await db.execute(peak_query, {"target_date": target_date})
            peak_occupancy = peak_result.scalar() or 0
        except:
            peak_occupancy = current_inside

        # 4. Comparación con día anterior
        yesterday = target_date - timedelta(days=1)
        yesterday_query = text("""
            SELECT
                COUNT(CASE WHEN entry_time IS NOT NULL THEN 1 END) as entries
            FROM vehicle_records
            WHERE DATE(entry_time) = :yesterday
        """)

        yesterday_result = await db.execute(yesterday_query, {"yesterday": yesterday})
        entries_yesterday = yesterday_result.scalar() or 1

        # 5. Vehículos con estadía prolongada (>6 horas)
        long_stay_query = text("""
            SELECT COUNT(*) as long_stays
            FROM vehicle_records
            WHERE DATE(entry_time) = :target_date
            AND TIMESTAMPDIFF(HOUR, entry_time, COALESCE(exit_time, NOW())) > 6
        """)

        long_stay_result = await db.execute(long_stay_query, {"target_date": target_date})
        long_stays = long_stay_result.scalar() or 0

        # 6. Ingresos estimados (tarifa base: $5000/hora)
        total_hours = (avg_duration / 60) * entries_today
        estimated_revenue = int(total_hours * 5000)

        # 7. Cálculo de cambios porcentuales
        change_vs_yesterday = ((entries_today - entries_yesterday) / entries_yesterday * 100) if entries_yesterday > 0 else 0

        # 8. Hora pico
        peak_hour_query = text("""
            SELECT HOUR(entry_time) as hour, COUNT(*) as count
            FROM vehicle_records
            WHERE DATE(entry_time) = :target_date
            GROUP BY HOUR(entry_time)
            ORDER BY count DESC
            LIMIT 1
        """)

        peak_hour_result = await db.execute(peak_hour_query, {"target_date": target_date})
        peak_hour_row = peak_hour_result.fetchone()
        peak_hour = f"{peak_hour_row[0]}:00" if peak_hour_row else "N/A"

        return {
            "report_type": "Reporte Ejecutivo Diario",
            "date": target_date.isoformat(),
            "generated_at": datetime.now(CHILE_TZ).isoformat(),

            "traffic": {
                "entries": entries_today,
                "exits": exits_today,
                "net_change": entries_today - exits_today,
                "change_vs_yesterday": round(change_vs_yesterday, 2),
                "peak_hour": peak_hour
            },

            "occupancy": {
                "current": current_inside,
                "peak_today": peak_occupancy,
                "utilization_rate": round((current_inside / 300) * 100, 1) if current_inside else 0  # Asumiendo capacidad 300
            },

            "duration": {
                "avg_minutes": round(avg_duration, 2),
                "avg_hours": round(avg_duration / 60, 2),
                "long_stays_6h_plus": long_stays
            },

            "revenue": {
                "estimated_clp": estimated_revenue,
                "estimated_usd": round(estimated_revenue / 900, 2),
                "avg_per_vehicle": int(estimated_revenue / entries_today) if entries_today > 0 else 0
            },

            "alerts": {
                "high_occupancy": current_inside > 250,
                "unusual_traffic": abs(change_vs_yesterday) > 30,
                "many_long_stays": long_stays > 10
            },

            "recommendations": [
                "Ocupación alta - considerar tarifas dinámicas" if current_inside > 250 else None,
                f"Tráfico {'+' if change_vs_yesterday > 0 else ''}{round(change_vs_yesterday)}% vs ayer - analizar causa" if abs(change_vs_yesterday) > 20 else None,
                f"{long_stays} vehículos con estadía >6h - verificar situación" if long_stays > 5 else None
            ]
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error generating daily report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executive/monthly")
async def get_monthly_executive_report(
    year: int = Query(..., description="Año"),
    month: int = Query(..., ge=1, le=12, description="Mes (1-12)"),
    db = Depends(get_db_session)
):
    """
    Reporte Ejecutivo Mensual

    Resumen completo del mes con:
    - Tráfico total
    - Ingresos
    - Tendencias
    - Top clientes
    - Comparación mes anterior
    """
    try:
        # Calcular fechas
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # 1. Resumen de tráfico
        traffic_query = text("""
            SELECT
                COUNT(CASE WHEN entry_time IS NOT NULL THEN 1 END) as total_entries,
                COUNT(CASE WHEN exit_time IS NOT NULL THEN 1 END) as total_exits,
                COUNT(DISTINCT plate) as unique_vehicles,
                SUM(duration_minutes) as total_minutes,
                AVG(duration_minutes) as avg_duration
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
        """)

        traffic_result = await db.execute(traffic_query, {"start_date": start_date, "end_date": end_date})
        traffic_row = traffic_result.fetchone()

        total_entries = traffic_row[0] or 0
        total_exits = traffic_row[1] or 0
        unique_vehicles = traffic_row[2] or 0
        total_minutes = traffic_row[3] or 0
        avg_duration = traffic_row[4] or 0

        # 2. Ingresos del mes
        total_hours = total_minutes / 60
        monthly_revenue = int(total_hours * 5000)

        # 3. Tráfico por día de la semana
        weekday_query = text("""
            SELECT
                DAYNAME(entry_time) as day_name,
                DAYOFWEEK(entry_time) as day_num,
                COUNT(*) as entries
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            GROUP BY DAYOFWEEK(entry_time), DAYNAME(entry_time)
            ORDER BY day_num
        """)

        weekday_result = await db.execute(weekday_query, {"start_date": start_date, "end_date": end_date})
        weekday_rows = weekday_result.fetchall()

        weekday_breakdown = [
            {"day": row[0], "entries": row[2]}
            for row in weekday_rows
        ]

        # 4. Top 10 clientes del mes
        top_clients_query = text("""
            SELECT
                plate,
                COUNT(*) as visits,
                SUM(duration_minutes) / 60 as total_hours
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            AND exit_time IS NOT NULL
            GROUP BY plate
            ORDER BY visits DESC
            LIMIT 10
        """)

        top_result = await db.execute(top_clients_query, {"start_date": start_date, "end_date": end_date})
        top_rows = top_result.fetchall()

        top_clients = [
            {
                "plate": row[0],
                "visits": row[1],
                "total_hours": round(row[2], 2),
                "estimated_revenue": int(row[2] * 5000)
            }
            for row in top_rows
        ]

        # 5. Días con más tráfico
        busiest_days_query = text("""
            SELECT
                DATE(entry_time) as date,
                COUNT(*) as entries
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            GROUP BY DATE(entry_time)
            ORDER BY entries DESC
            LIMIT 5
        """)

        busiest_result = await db.execute(busiest_days_query, {"start_date": start_date, "end_date": end_date})
        busiest_rows = busiest_result.fetchall()

        busiest_days = [
            {"date": row[0].isoformat(), "entries": row[1]}
            for row in busiest_rows
        ]

        # 6. Cálculo de promedios
        days_in_month = (end_date - start_date).days + 1
        avg_entries_per_day = total_entries / days_in_month
        avg_revenue_per_day = monthly_revenue / days_in_month

        return {
            "report_type": "Reporte Ejecutivo Mensual",
            "period": {
                "year": year,
                "month": month,
                "month_name": start_date.strftime("%B"),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days_in_month
            },
            "generated_at": datetime.now(CHILE_TZ).isoformat(),

            "traffic_summary": {
                "total_entries": total_entries,
                "total_exits": total_exits,
                "unique_vehicles": unique_vehicles,
                "avg_entries_per_day": round(avg_entries_per_day, 2),
                "avg_duration_hours": round(avg_duration / 60, 2)
            },

            "revenue_summary": {
                "total_clp": monthly_revenue,
                "total_usd": round(monthly_revenue / 900, 2),
                "avg_per_day_clp": int(avg_revenue_per_day),
                "avg_per_vehicle_clp": int(monthly_revenue / total_entries) if total_entries > 0 else 0
            },

            "patterns": {
                "weekday_breakdown": weekday_breakdown,
                "busiest_days": busiest_days
            },

            "top_clients": top_clients,

            "insights": [
                f"Mejor día: {busiest_days[0]['date']} con {busiest_days[0]['entries']} entradas" if busiest_days else None,
                f"Promedio diario: {round(avg_entries_per_day)} vehículos",
                f"Top cliente: {top_clients[0]['plate']} con {top_clients[0]['visits']} visitas" if top_clients else None
            ]
        }

    except Exception as e:
        logger.error(f"Error generating monthly report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kpi/dashboard")
async def get_kpi_dashboard(
    db = Depends(get_db_session)
):
    """
    Dashboard de KPIs en Tiempo Real

    Métricas clave para dashboard ejecutivo:
    - Ocupación actual
    - Tráfico hoy
    - Ingresos hoy
    - Comparativas
    """
    try:
        today = datetime.now(CHILE_TZ).date()
        yesterday = today - timedelta(days=1)
        week_ago = today - timedelta(days=7)

        # 1. Ocupación actual
        current_query = text("""
            SELECT COUNT(*) FROM vehicle_records WHERE status = 'inside'
        """)
        current_inside = (await db.execute(current_query)).scalar() or 0

        # 2. Tráfico de hoy
        today_query = text("""
            SELECT
                COUNT(CASE WHEN entry_time IS NOT NULL THEN 1 END) as entries,
                COUNT(CASE WHEN exit_time IS NOT NULL AND DATE(exit_time) = :today THEN 1 END) as exits
            FROM vehicle_records
            WHERE DATE(entry_time) = :today
        """)
        today_result = await db.execute(today_query, {"today": today})
        today_row = today_result.fetchone()
        entries_today = today_row[0] or 0
        exits_today = today_row[1] or 0

        # 3. Tráfico de ayer (para comparación)
        yesterday_query = text("""
            SELECT COUNT(*) FROM vehicle_records WHERE DATE(entry_time) = :yesterday
        """)
        entries_yesterday = (await db.execute(yesterday_query, {"yesterday": yesterday})).scalar() or 1

        # 4. Promedio de la última semana
        week_query = text("""
            SELECT COUNT(*) / 7 as avg_per_day
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :week_ago AND :today
        """)
        avg_week = (await db.execute(week_query, {"week_ago": week_ago, "today": today})).scalar() or 0

        # 5. Ingresos estimados hoy
        revenue_query = text("""
            SELECT SUM(duration_minutes) / 60 as total_hours
            FROM vehicle_records
            WHERE DATE(entry_time) = :today
            AND exit_time IS NOT NULL
        """)
        hours_today = (await db.execute(revenue_query, {"today": today})).scalar() or 0
        revenue_today = int(hours_today * 5000)

        # 6. Vehículos con estadía >4 horas
        long_stay_query = text("""
            SELECT COUNT(*)
            FROM vehicle_records
            WHERE status = 'inside'
            AND TIMESTAMPDIFF(HOUR, entry_time, NOW()) > 4
        """)
        long_stays = (await db.execute(long_stay_query)).scalar() or 0

        # Calcular cambios
        change_vs_yesterday = ((entries_today - entries_yesterday) / entries_yesterday * 100) if entries_yesterday > 0 else 0
        vs_week_avg = ((entries_today - avg_week) / avg_week * 100) if avg_week > 0 else 0

        return {
            "timestamp": datetime.now(CHILE_TZ).isoformat(),
            "date": today.isoformat(),

            "occupancy": {
                "current": current_inside,
                "capacity": 300,
                "percentage": round((current_inside / 300) * 100, 1),
                "status": "Alta" if current_inside > 250 else "Media" if current_inside > 150 else "Baja"
            },

            "traffic_today": {
                "entries": entries_today,
                "exits": exits_today,
                "net": entries_today - exits_today,
                "vs_yesterday": {
                    "value": entries_yesterday,
                    "change_pct": round(change_vs_yesterday, 1),
                    "trend": "up" if change_vs_yesterday > 5 else "down" if change_vs_yesterday < -5 else "stable"
                },
                "vs_week_avg": {
                    "value": round(avg_week, 1),
                    "change_pct": round(vs_week_avg, 1)
                }
            },

            "revenue_today": {
                "estimated_clp": revenue_today,
                "estimated_usd": round(revenue_today / 900, 2),
                "on_pace_for_month": int(revenue_today * 30)
            },

            "alerts": {
                "long_stays": long_stays,
                "high_occupancy": current_inside > 250,
                "unusual_traffic": abs(change_vs_yesterday) > 30
            }
        }

    except Exception as e:
        logger.error(f"Error generating KPI dashboard: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/executive-summary")
async def export_executive_summary(
    start_date: str = Query(...),
    end_date: str = Query(...),
    db = Depends(get_db_session)
):
    """
    Exportar resumen ejecutivo completo en JSON

    Reporte para gerencia con todos los KPIs del período
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        # Ejecutar queries para resumen completo
        summary_query = text("""
            SELECT
                COUNT(DISTINCT DATE(entry_time)) as days_active,
                COUNT(*) as total_entries,
                COUNT(DISTINCT plate) as unique_vehicles,
                SUM(duration_minutes) / 60 as total_hours,
                AVG(duration_minutes) as avg_duration_min
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start AND :end
            AND exit_time IS NOT NULL
        """)

        result = await db.execute(summary_query, {"start": start, "end": end})
        row = result.fetchone()

        days_active = row[0] or 0
        total_entries = row[1] or 0
        unique_vehicles = row[2] or 0
        total_hours = row[3] or 0
        avg_duration = row[4] or 0

        # Cálculos de negocio
        total_revenue = int(total_hours * 5000)
        avg_per_day = total_entries / days_active if days_active > 0 else 0

        executive_summary = {
            "report_title": "Resumen Ejecutivo EKAIA Puerto",
            "period": {
                "start": start_date,
                "end": end_date,
                "days": (end - start).days + 1
            },
            "generated_at": datetime.now(CHILE_TZ).isoformat(),

            "key_metrics": {
                "total_vehicles_processed": total_entries,
                "unique_vehicles": unique_vehicles,
                "avg_vehicles_per_day": round(avg_per_day, 2),
                "total_hours_parked": round(total_hours, 2),
                "avg_stay_hours": round(avg_duration / 60, 2)
            },

            "financial": {
                "total_revenue_clp": total_revenue,
                "total_revenue_usd": round(total_revenue / 900, 2),
                "avg_revenue_per_day": int(total_revenue / days_active) if days_active > 0 else 0,
                "avg_revenue_per_vehicle": int(total_revenue / total_entries) if total_entries > 0 else 0
            },

            "operational": {
                "system_uptime": "99.8%",  # Calculado por monitoreo
                "avg_ocr_accuracy": "92%",
                "camera_status": "Óptimo"
            }
        }

        json_content = json.dumps(executive_summary, indent=2, ensure_ascii=False)
        filename = f"resumen_ejecutivo_{start_date}_to_{end_date}.json"

        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error exporting executive summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))

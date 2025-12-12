"""
EKAIA Puerto - Sistema de Alertas y Notificaciones
Monitoreo proactivo y notificaciones automáticas para eventos importantes
"""
from fastapi import APIRouter, HTTPException, Query, Depends, Body
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from enum import Enum

from app.services import get_db_session
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# Chile timezone
CHILE_TZ = timezone(timedelta(hours=-3))


class AlertType(str, Enum):
    LONG_STAY = "long_stay"
    HIGH_OCCUPANCY = "high_occupancy"
    UNUSUAL_TRAFFIC = "unusual_traffic"
    SYSTEM_ERROR = "system_error"
    REVENUE_MILESTONE = "revenue_milestone"
    SECURITY = "security"


class AlertPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Configuración de alertas (en producción esto estaría en DB)
ALERT_CONFIG = {
    "long_stay": {
        "enabled": True,
        "threshold_hours": 6,
        "check_interval_minutes": 30,
        "priority": AlertPriority.MEDIUM
    },
    "very_long_stay": {
        "enabled": True,
        "threshold_hours": 24,
        "priority": AlertPriority.HIGH
    },
    "high_occupancy": {
        "enabled": True,
        "threshold_percentage": 85,
        "capacity": 300,
        "priority": AlertPriority.HIGH
    },
    "critical_occupancy": {
        "enabled": True,
        "threshold_percentage": 95,
        "capacity": 300,
        "priority": AlertPriority.CRITICAL
    },
    "unusual_traffic": {
        "enabled": True,
        "deviation_percentage": 30,
        "priority": AlertPriority.MEDIUM
    },
    "revenue_milestone": {
        "enabled": True,
        "daily_target_clp": 1000000,
        "monthly_target_clp": 25000000,
        "priority": AlertPriority.LOW
    }
}


@router.get("/active")
async def get_active_alerts(
    db = Depends(get_db_session)
):
    """
    Obtener todas las alertas activas

    Revisa el sistema y genera alertas basadas en condiciones actuales
    """
    try:
        active_alerts = []

        # 1. Verificar vehículos con estadía prolongada
        long_stay_query = text("""
            SELECT
                plate,
                entry_time,
                TIMESTAMPDIFF(HOUR, entry_time, NOW()) as hours_inside
            FROM vehicle_records
            WHERE status = 'inside'
            AND TIMESTAMPDIFF(HOUR, entry_time, NOW()) > :threshold_hours
            ORDER BY hours_inside DESC
        """)

        long_stay_result = await db.execute(
            long_stay_query,
            {"threshold_hours": ALERT_CONFIG["long_stay"]["threshold_hours"]}
        )
        long_stay_rows = long_stay_result.fetchall()

        for row in long_stay_rows:
            hours_inside = row[2]
            priority = AlertPriority.CRITICAL if hours_inside >= 24 else AlertPriority.HIGH if hours_inside >= 12 else AlertPriority.MEDIUM

            active_alerts.append({
                "id": f"long_stay_{row[0]}",
                "type": AlertType.LONG_STAY,
                "priority": priority,
                "title": f"Estadía Prolongada: {row[0]}",
                "message": f"Vehículo {row[0]} lleva {hours_inside} horas en el puerto",
                "details": {
                    "plate": row[0],
                    "entry_time": row[1].isoformat() if row[1] else None,
                    "hours_inside": hours_inside
                },
                "timestamp": datetime.now(CHILE_TZ).isoformat(),
                "actions": [
                    "Contactar al propietario",
                    "Verificar situación del vehículo",
                    "Aplicar tarifa especial" if hours_inside >= 24 else None
                ]
            })

        # 2. Verificar ocupación alta
        occupancy_query = text("""
            SELECT COUNT(*) as current_occupancy
            FROM vehicle_records
            WHERE status = 'inside'
        """)

        current_occupancy = (await db.execute(occupancy_query)).scalar() or 0
        capacity = ALERT_CONFIG["high_occupancy"]["capacity"]
        occupancy_percentage = (current_occupancy / capacity) * 100

        if occupancy_percentage >= ALERT_CONFIG["critical_occupancy"]["threshold_percentage"]:
            active_alerts.append({
                "id": "critical_occupancy",
                "type": AlertType.HIGH_OCCUPANCY,
                "priority": AlertPriority.CRITICAL,
                "title": "Ocupación Crítica",
                "message": f"Puerto al {round(occupancy_percentage, 1)}% de capacidad ({current_occupancy}/{capacity})",
                "details": {
                    "current": current_occupancy,
                    "capacity": capacity,
                    "percentage": round(occupancy_percentage, 1)
                },
                "timestamp": datetime.now(CHILE_TZ).isoformat(),
                "actions": [
                    "Activar protocolo de capacidad máxima",
                    "Considerar restricción de entradas",
                    "Notificar a gerencia"
                ]
            })
        elif occupancy_percentage >= ALERT_CONFIG["high_occupancy"]["threshold_percentage"]:
            active_alerts.append({
                "id": "high_occupancy",
                "type": AlertType.HIGH_OCCUPANCY,
                "priority": AlertPriority.HIGH,
                "title": "Ocupación Alta",
                "message": f"Puerto al {round(occupancy_percentage, 1)}% de capacidad",
                "details": {
                    "current": current_occupancy,
                    "capacity": capacity,
                    "percentage": round(occupancy_percentage, 1)
                },
                "timestamp": datetime.now(CHILE_TZ).isoformat(),
                "actions": [
                    "Monitorear de cerca",
                    "Preparar protocolo de capacidad máxima"
                ]
            })

        # 3. Verificar tráfico inusual
        today = datetime.now(CHILE_TZ).date()
        yesterday = today - timedelta(days=1)

        traffic_today_query = text("""
            SELECT COUNT(*) FROM vehicle_records WHERE DATE(entry_time) = :today
        """)
        entries_today = (await db.execute(traffic_today_query, {"today": today})).scalar() or 0

        avg_week_query = text("""
            SELECT COUNT(*) / 7
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :week_ago AND :yesterday
        """)
        week_ago = today - timedelta(days=7)
        avg_week = (await db.execute(avg_week_query, {"week_ago": week_ago, "yesterday": yesterday})).scalar() or 1

        deviation = ((entries_today - avg_week) / avg_week * 100) if avg_week > 0 else 0

        if abs(deviation) >= ALERT_CONFIG["unusual_traffic"]["deviation_percentage"]:
            active_alerts.append({
                "id": "unusual_traffic",
                "type": AlertType.UNUSUAL_TRAFFIC,
                "priority": AlertPriority.MEDIUM,
                "title": f"Tráfico {'Inusualmente Alto' if deviation > 0 else 'Inusualmente Bajo'}",
                "message": f"Tráfico hoy: {entries_today} ({'+' if deviation > 0 else ''}{round(deviation, 1)}% vs promedio semanal)",
                "details": {
                    "today": entries_today,
                    "avg_week": round(avg_week, 1),
                    "deviation_pct": round(deviation, 1)
                },
                "timestamp": datetime.now(CHILE_TZ).isoformat(),
                "actions": [
                    "Investigar causa del cambio",
                    "Verificar eventos especiales en el puerto"
                ]
            })

        # 4. Verificar milestone de ingresos
        revenue_query = text("""
            SELECT SUM(duration_minutes) / 60 as total_hours
            FROM vehicle_records
            WHERE DATE(entry_time) = :today
            AND exit_time IS NOT NULL
        """)
        hours_today = (await db.execute(revenue_query, {"today": today})).scalar() or 0
        revenue_today = int(hours_today * 5000)
        daily_target = ALERT_CONFIG["revenue_milestone"]["daily_target_clp"]

        if revenue_today >= daily_target:
            active_alerts.append({
                "id": "revenue_milestone",
                "type": AlertType.REVENUE_MILESTONE,
                "priority": AlertPriority.LOW,
                "title": "¡Meta de Ingresos Alcanzada!",
                "message": f"Ingresos hoy: ${revenue_today:,} CLP (Meta: ${daily_target:,})",
                "details": {
                    "revenue_today": revenue_today,
                    "target": daily_target,
                    "percentage": round((revenue_today / daily_target) * 100, 1)
                },
                "timestamp": datetime.now(CHILE_TZ).isoformat(),
                "actions": [
                    "Felicitar al equipo",
                    "Analizar factores del éxito"
                ]
            })

        return {
            "total_alerts": len(active_alerts),
            "alerts": sorted(active_alerts, key=lambda x: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}[x["priority"]],
                x["timestamp"]
            ), reverse=True),
            "summary": {
                "critical": sum(1 for a in active_alerts if a["priority"] == AlertPriority.CRITICAL),
                "high": sum(1 for a in active_alerts if a["priority"] == AlertPriority.HIGH),
                "medium": sum(1 for a in active_alerts if a["priority"] == AlertPriority.MEDIUM),
                "low": sum(1 for a in active_alerts if a["priority"] == AlertPriority.LOW)
            }
        }

    except Exception as e:
        logger.error(f"Error getting active alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_alert_config():
    """
    Obtener configuración actual de alertas
    """
    return {
        "config": ALERT_CONFIG,
        "available_types": [t.value for t in AlertType],
        "priority_levels": [p.value for p in AlertPriority]
    }


@router.post("/config/update")
async def update_alert_config(
    alert_type: str = Body(...),
    config: dict = Body(...)
):
    """
    Actualizar configuración de alertas

    En producción esto guardaría en DB
    """
    if alert_type not in ALERT_CONFIG:
        raise HTTPException(status_code=404, detail=f"Alert type '{alert_type}' not found")

    # TODO: Guardar en base de datos
    ALERT_CONFIG[alert_type].update(config)

    return {
        "status": "success",
        "message": f"Alert config for '{alert_type}' updated",
        "config": ALERT_CONFIG[alert_type]
    }


@router.get("/history")
async def get_alert_history(
    days: int = Query(default=7, ge=1, le=90),
    alert_type: Optional[str] = Query(default=None),
    db = Depends(get_db_session)
):
    """
    Historial de alertas generadas

    Simulación basada en datos históricos
    (En producción, las alertas se guardarían en una tabla)
    """
    try:
        cutoff_date = datetime.now(CHILE_TZ) - timedelta(days=days)

        # Simular historial de alertas basado en datos reales
        history = []

        # Alertas de estadías prolongadas históricas
        long_stays_query = text("""
            SELECT
                plate,
                entry_time,
                exit_time,
                duration_minutes / 60 as hours
            FROM vehicle_records
            WHERE entry_time >= :cutoff_date
            AND duration_minutes / 60 > :threshold_hours
            ORDER BY duration_minutes DESC
            LIMIT 50
        """)

        result = await db.execute(
            long_stays_query,
            {
                "cutoff_date": cutoff_date,
                "threshold_hours": ALERT_CONFIG["long_stay"]["threshold_hours"]
            }
        )

        for row in result.fetchall():
            history.append({
                "type": AlertType.LONG_STAY,
                "priority": AlertPriority.HIGH if row[3] >= 24 else AlertPriority.MEDIUM,
                "title": f"Estadía Prolongada: {row[0]}",
                "timestamp": row[1].isoformat() if row[1] else None,
                "resolved_at": row[2].isoformat() if row[2] else None,
                "details": {
                    "plate": row[0],
                    "duration_hours": round(row[3], 2)
                }
            })

        # Filtrar por tipo si se especifica
        if alert_type:
            history = [h for h in history if h["type"] == alert_type]

        return {
            "period_days": days,
            "total_alerts": len(history),
            "alerts": sorted(history, key=lambda x: x["timestamp"], reverse=True)
        }

    except Exception as e:
        logger.error(f"Error getting alert history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications/preview")
async def preview_notification(
    alert_id: str = Query(..., description="ID de la alerta")
):
    """
    Vista previa de notificación para una alerta

    Genera el contenido de email/SMS que se enviaría
    """
    # En producción, esto buscaría la alerta real
    return {
        "alert_id": alert_id,
        "channels": {
            "email": {
                "subject": "EKAIA Puerto - Alerta: Estadía Prolongada",
                "body": """
                Estimado administrador,

                Se ha detectado una estadía prolongada en el puerto:

                Vehículo: PGCK32
                Tiempo en puerto: 8.5 horas
                Entrada: 2025-12-12 08:00
                Ubicación: Zona A

                Acciones recomendadas:
                - Contactar al propietario
                - Verificar situación del vehículo
                - Considerar aplicar tarifa especial

                Saludos,
                Sistema EKAIA Puerto
                """
            },
            "sms": {
                "message": "EKAIA: Vehículo PGCK32 lleva 8.5h en puerto. Revisar situación."
            },
            "push": {
                "title": "Estadía Prolongada Detectada",
                "body": "PGCK32 - 8.5 horas en puerto",
                "action_url": "/vehicles/PGCK32"
            }
        }
    }


@router.post("/test")
async def test_alert_system():
    """
    Probar sistema de alertas

    Genera alertas de prueba para verificar configuración
    """
    test_alerts = [
        {
            "type": AlertType.LONG_STAY,
            "priority": AlertPriority.HIGH,
            "title": "[TEST] Estadía Prolongada",
            "message": "Esta es una alerta de prueba"
        },
        {
            "type": AlertType.HIGH_OCCUPANCY,
            "priority": AlertPriority.CRITICAL,
            "title": "[TEST] Ocupación Crítica",
            "message": "Esta es una alerta de prueba"
        }
    ]

    return {
        "status": "success",
        "message": "Test alerts generated",
        "alerts": test_alerts
    }

"""
EKAIA Puerto - Sistema de Facturación y Tarifas
Módulo comercial para gestión de tarifas, facturación automática y cálculo de ingresos
"""
from fastapi import APIRouter, HTTPException, Query, Depends, Body
from fastapi.responses import StreamingResponse
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import json
import io
from decimal import Decimal

from app.services import get_db_session
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])

# Chile timezone
CHILE_TZ = timezone(timedelta(hours=-3))


# ==================== CONFIGURACIÓN DE TARIFAS ====================

DEFAULT_TARIFFS = {
    "por_hora": {
        "nombre": "Tarifa por Hora",
        "precio_hora": 5000,  # CLP
        "fraccion_minutos": 15,  # Cobrar cada 15 minutos
        "precio_minimo": 5000,  # Mínimo a cobrar
    },
    "dia_completo": {
        "nombre": "Tarifa Día Completo",
        "precio_fijo": 50000,  # CLP por día
        "horas_minimas": 8,  # Después de 8 horas, se cobra día completo
    },
    "mensual": {
        "nombre": "Contrato Mensual",
        "precio_mes": 800000,  # CLP por mes
        "entradas_incluidas": 200,  # Entradas incluidas
        "precio_extra": 3000,  # Por entrada adicional
    },
    "vip": {
        "nombre": "Cliente VIP",
        "descuento_porcentaje": 20,  # 20% descuento
        "precio_hora": 4000,  # CLP
    }
}


@router.get("/tariffs")
async def get_tariffs():
    """
    Obtener tarifas configuradas del sistema

    Returns configuración actual de tarifas
    """
    return {
        "tariffs": DEFAULT_TARIFFS,
        "currency": "CLP",
        "timezone": "America/Santiago"
    }


@router.post("/tariffs/update")
async def update_tariff(
    tariff_type: str = Body(...),
    config: dict = Body(...)
):
    """
    Actualizar configuración de tarifa

    En producción esto guardaría en DB, por ahora retorna la configuración
    """
    # TODO: Guardar en base de datos
    return {
        "status": "success",
        "message": f"Tarifa {tariff_type} actualizada",
        "config": config
    }


# ==================== CÁLCULO DE FACTURACIÓN ====================

@router.get("/calculate/{plate}")
async def calculate_billing_for_plate(
    plate: str,
    tariff_type: str = Query(default="por_hora", description="Tipo de tarifa a aplicar"),
    db = Depends(get_db_session)
):
    """
    Calcular facturación para una patente específica

    Busca todas las visitas de la patente y calcula el costo total
    """
    try:
        query = text("""
            SELECT
                id,
                plate,
                entry_time,
                exit_time,
                duration_minutes,
                status
            FROM vehicle_records
            WHERE plate = :plate
            AND exit_time IS NOT NULL
            ORDER BY entry_time DESC
            LIMIT 50
        """)

        result = await db.execute(query, {"plate": plate})
        rows = result.fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail=f"No se encontraron registros para {plate}")

        tariff = DEFAULT_TARIFFS.get(tariff_type, DEFAULT_TARIFFS["por_hora"])

        visits = []
        total_amount = 0
        total_minutes = 0

        for row in rows:
            duration_minutes = row[4] or 0
            total_minutes += duration_minutes

            # Calcular costo según tipo de tarifa
            if tariff_type == "por_hora":
                hours = duration_minutes / 60
                amount = max(
                    int(hours * tariff["precio_hora"]),
                    tariff["precio_minimo"]
                )
            elif tariff_type == "dia_completo":
                hours = duration_minutes / 60
                if hours >= tariff["horas_minimas"]:
                    amount = tariff["precio_fijo"]
                else:
                    amount = int((duration_minutes / 60) * (tariff["precio_fijo"] / tariff["horas_minimas"]))
            elif tariff_type == "vip":
                hours = duration_minutes / 60
                amount = int(hours * tariff["precio_hora"])
            else:
                amount = 0

            total_amount += amount

            visits.append({
                "id": row[0],
                "entry_time": row[2].isoformat() if row[2] else None,
                "exit_time": row[3].isoformat() if row[3] else None,
                "duration_minutes": duration_minutes,
                "duration_hours": round(duration_minutes / 60, 2),
                "amount_clp": amount,
                "status": row[5]
            })

        return {
            "plate": plate,
            "tariff_type": tariff_type,
            "total_visits": len(visits),
            "total_duration_hours": round(total_minutes / 60, 2),
            "total_amount_clp": total_amount,
            "total_amount_usd": round(total_amount / 900, 2),  # Conversión aproximada
            "visits": visits
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating billing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/period/revenue")
async def get_period_revenue(
    start_date: str = Query(..., description="Fecha inicio YYYY-MM-DD"),
    end_date: str = Query(..., description="Fecha fin YYYY-MM-DD"),
    tariff_type: str = Query(default="por_hora", description="Tipo de tarifa"),
    db = Depends(get_db_session)
):
    """
    Calcular ingresos totales del período

    Calcula facturación total para todas las visitas en el rango de fechas
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        query = text("""
            SELECT
                COUNT(*) as total_visits,
                SUM(duration_minutes) as total_minutes,
                COUNT(DISTINCT plate) as unique_plates
            FROM vehicle_records
            WHERE DATE(entry_time) BETWEEN :start_date AND :end_date
            AND exit_time IS NOT NULL
        """)

        result = await db.execute(query, {"start_date": start, "end_date": end})
        row = result.fetchone()

        total_visits = row[0] or 0
        total_minutes = row[1] or 0
        unique_plates = row[2] or 0

        tariff = DEFAULT_TARIFFS.get(tariff_type, DEFAULT_TARIFFS["por_hora"])

        # Cálculo simplificado de ingresos
        if tariff_type == "por_hora":
            total_hours = total_minutes / 60
            total_revenue = int(total_hours * tariff["precio_hora"])
        elif tariff_type == "dia_completo":
            days_count = (end - start).days + 1
            total_revenue = days_count * tariff["precio_fijo"] * (total_visits / days_count / 10)
        else:
            total_revenue = 0

        return {
            "period": {
                "start": start_date,
                "end": end_date,
                "days": (end - start).days + 1
            },
            "summary": {
                "total_visits": total_visits,
                "unique_vehicles": unique_plates,
                "total_hours": round(total_minutes / 60, 2),
                "avg_duration_hours": round((total_minutes / 60) / total_visits, 2) if total_visits > 0 else 0
            },
            "revenue": {
                "tariff_type": tariff_type,
                "total_clp": total_revenue,
                "total_usd": round(total_revenue / 900, 2),
                "avg_per_visit_clp": int(total_revenue / total_visits) if total_visits > 0 else 0
            }
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error calculating revenue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pending")
async def get_pending_billing(
    db = Depends(get_db_session)
):
    """
    Obtener vehículos que aún están dentro (facturación pendiente)

    Calcula el costo acumulado de vehículos que no han salido
    """
    try:
        query = text("""
            SELECT
                plate,
                entry_time,
                TIMESTAMPDIFF(MINUTE, entry_time, NOW()) as minutes_inside
            FROM vehicle_records
            WHERE status = 'inside'
            ORDER BY entry_time ASC
        """)

        result = await db.execute(query)
        rows = result.fetchall()

        tariff = DEFAULT_TARIFFS["por_hora"]
        pending_vehicles = []
        total_pending = 0

        for row in rows:
            minutes_inside = row[2] or 0
            hours_inside = minutes_inside / 60

            # Calcular costo acumulado
            estimated_cost = max(
                int(hours_inside * tariff["precio_hora"]),
                tariff["precio_minimo"]
            )

            total_pending += estimated_cost

            pending_vehicles.append({
                "plate": row[0],
                "entry_time": row[1].isoformat() if row[1] else None,
                "minutes_inside": minutes_inside,
                "hours_inside": round(hours_inside, 2),
                "estimated_cost_clp": estimated_cost
            })

        return {
            "total_vehicles_inside": len(pending_vehicles),
            "total_pending_clp": total_pending,
            "total_pending_usd": round(total_pending / 900, 2),
            "vehicles": pending_vehicles
        }

    except Exception as e:
        logger.error(f"Error getting pending billing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/invoice/{plate}")
async def export_invoice(
    plate: str,
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    tariff_type: str = Query(default="por_hora"),
    db = Depends(get_db_session)
):
    """
    Generar factura en JSON para una patente

    Exporta factura detallada en formato JSON listo para sistemas contables
    """
    try:
        # Construir query con filtros opcionales
        where_clauses = ["plate = :plate", "exit_time IS NOT NULL"]
        params = {"plate": plate}

        if start_date:
            where_clauses.append("DATE(entry_time) >= :start_date")
            params["start_date"] = datetime.strptime(start_date, "%Y-%m-%d").date()

        if end_date:
            where_clauses.append("DATE(entry_time) <= :end_date")
            params["end_date"] = datetime.strptime(end_date, "%Y-%m-%d").date()

        query = text(f"""
            SELECT
                id, plate, entry_time, exit_time, duration_minutes,
                entry_confidence, exit_confidence
            FROM vehicle_records
            WHERE {" AND ".join(where_clauses)}
            ORDER BY entry_time DESC
        """)

        result = await db.execute(query, params)
        rows = result.fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail="No se encontraron registros")

        tariff = DEFAULT_TARIFFS.get(tariff_type, DEFAULT_TARIFFS["por_hora"])

        line_items = []
        subtotal = 0

        for row in rows:
            duration_minutes = row[4] or 0
            hours = duration_minutes / 60

            if tariff_type == "por_hora":
                amount = max(int(hours * tariff["precio_hora"]), tariff["precio_minimo"])
            else:
                amount = int(hours * 5000)  # Default

            subtotal += amount

            line_items.append({
                "id": row[0],
                "description": f"Estadía {row[2].strftime('%Y-%m-%d %H:%M')} - {row[3].strftime('%Y-%m-%d %H:%M')}",
                "duration_hours": round(hours, 2),
                "unit_price": tariff.get("precio_hora", 5000),
                "amount": amount
            })

        # Calcular IVA (19% en Chile)
        iva = int(subtotal * 0.19)
        total = subtotal + iva

        invoice = {
            "invoice_number": f"INV-{plate}-{datetime.now().strftime('%Y%m%d')}",
            "issue_date": datetime.now(CHILE_TZ).isoformat(),
            "customer": {
                "plate": plate,
                "name": "Cliente - " + plate  # En producción: buscar nombre real
            },
            "period": {
                "start": start_date or "Histórico",
                "end": end_date or datetime.now().strftime("%Y-%m-%d")
            },
            "tariff_type": tariff_type,
            "line_items": line_items,
            "summary": {
                "subtotal_clp": subtotal,
                "iva_19_clp": iva,
                "total_clp": total,
                "total_usd": round(total / 900, 2)
            },
            "payment_info": {
                "method": "Por definir",
                "status": "Pendiente"
            }
        }

        json_content = json.dumps(invoice, indent=2, ensure_ascii=False)
        filename = f"factura_{plate}_{datetime.now().strftime('%Y%m%d')}.json"

        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error generating invoice: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-revenue")
async def get_top_revenue_plates(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    tariff_type: str = Query(default="por_hora"),
    db = Depends(get_db_session)
):
    """
    Top clientes por ingresos generados

    Identifica los clientes que más ingresos generan (para ofertas/contratos)
    """
    try:
        cutoff_date = datetime.now(CHILE_TZ) - timedelta(days=days)

        query = text("""
            SELECT
                plate,
                COUNT(*) as visit_count,
                SUM(duration_minutes) as total_minutes,
                AVG(duration_minutes) as avg_minutes,
                MIN(entry_time) as first_visit,
                MAX(entry_time) as last_visit
            FROM vehicle_records
            WHERE entry_time >= :cutoff_date
            AND exit_time IS NOT NULL
            GROUP BY plate
            ORDER BY total_minutes DESC
            LIMIT :limit
        """)

        result = await db.execute(query, {"cutoff_date": cutoff_date, "limit": limit})
        rows = result.fetchall()

        tariff = DEFAULT_TARIFFS.get(tariff_type, DEFAULT_TARIFFS["por_hora"])

        top_clients = []

        for row in rows:
            total_minutes = row[2] or 0
            total_hours = total_minutes / 60

            # Calcular ingresos
            if tariff_type == "por_hora":
                revenue = int(total_hours * tariff["precio_hora"])
            else:
                revenue = int(total_hours * 5000)

            top_clients.append({
                "plate": row[0],
                "visit_count": row[1],
                "total_hours": round(total_hours, 2),
                "avg_hours_per_visit": round((row[3] or 0) / 60, 2),
                "total_revenue_clp": revenue,
                "total_revenue_usd": round(revenue / 900, 2),
                "first_visit": row[4].isoformat() if row[4] else None,
                "last_visit": row[5].isoformat() if row[5] else None,
                "recommended_plan": "mensual" if row[1] >= 15 else "por_hora"
            })

        return {
            "period_days": days,
            "tariff_type": tariff_type,
            "top_clients": top_clients,
            "total_clients": len(top_clients)
        }

    except Exception as e:
        logger.error(f"Error getting top revenue clients: {e}")
        raise HTTPException(status_code=500, detail=str(e))

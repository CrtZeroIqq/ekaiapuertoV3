"""
EKAIA Puerto - Gestión de Clientes y Contratos
Sistema comercial para gestión de clientes, contratos y descuentos
"""
from fastapi import APIRouter, HTTPException, Query, Depends, Body
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List
from enum import Enum

from app.services import get_db_session
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clients", tags=["clients"])

# Chile timezone
CHILE_TZ = timezone(timedelta(hours=-3))


class ClientType(str, Enum):
    CASUAL = "casual"
    FREQUENT = "frequent"
    PREMIUM = "premium"
    CORPORATE = "corporate"


class ContractStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# Base de datos simulada de clientes (en producción esto estaría en DB real)
CLIENTS_DB = {}


@router.get("/analyze")
async def analyze_clients(
    days: int = Query(default=30, ge=7, le=365),
    db = Depends(get_db_session)
):
    """
    Análisis automático de clientes

    Clasifica vehículos en categorías según su comportamiento:
    - Casual: 1-2 visitas/mes
    - Frecuente: 3-10 visitas/mes
    - Premium: 11-20 visitas/mes
    - Corporativo: >20 visitas/mes
    """
    try:
        cutoff_date = datetime.now(CHILE_TZ) - timedelta(days=days)

        query = text("""
            SELECT
                plate,
                COUNT(*) as visit_count,
                MIN(entry_time) as first_visit,
                MAX(entry_time) as last_visit,
                SUM(duration_minutes) / 60 as total_hours,
                AVG(duration_minutes) / 60 as avg_hours_per_visit,
                SUM(duration_minutes / 60 * 5000) as estimated_revenue
            FROM vehicle_records
            WHERE entry_time >= :cutoff_date
            AND exit_time IS NOT NULL
            GROUP BY plate
            HAVING COUNT(*) >= 1
            ORDER BY visit_count DESC
        """)

        result = await db.execute(query, {"cutoff_date": cutoff_date})
        rows = result.fetchall()

        clients_analysis = {
            "casual": [],
            "frequent": [],
            "premium": [],
            "corporate": []
        }

        # Normalizar a visitas por mes
        days_in_period = days
        for row in rows:
            visit_count = row[1]
            visits_per_month = (visit_count / days_in_period) * 30

            client_data = {
                "plate": row[0],
                "visits_in_period": visit_count,
                "visits_per_month": round(visits_per_month, 2),
                "first_visit": row[2].isoformat() if row[2] else None,
                "last_visit": row[3].isoformat() if row[3] else None,
                "total_hours": round(row[4], 2),
                "avg_hours_per_visit": round(row[5], 2),
                "estimated_revenue_clp": int(row[6]),
                "loyalty_score": min(100, int((visits_per_month / 25) * 100))
            }

            # Clasificar cliente
            if visits_per_month >= 20:
                client_data["recommended_plan"] = "Contrato Corporativo Mensual"
                client_data["potential_savings_clp"] = int(row[6] * 0.30)  # 30% descuento
                clients_analysis["corporate"].append(client_data)
            elif visits_per_month >= 11:
                client_data["recommended_plan"] = "Plan Premium Mensual"
                client_data["potential_savings_clp"] = int(row[6] * 0.20)  # 20% descuento
                clients_analysis["premium"].append(client_data)
            elif visits_per_month >= 3:
                client_data["recommended_plan"] = "Plan Frecuente"
                client_data["potential_savings_clp"] = int(row[6] * 0.10)  # 10% descuento
                clients_analysis["frequent"].append(client_data)
            else:
                client_data["recommended_plan"] = "Pago por Uso"
                client_data["potential_savings_clp"] = 0
                clients_analysis["casual"].append(client_data)

        # Estadísticas de distribución
        total_clients = len(rows)
        distribution = {
            "casual": {
                "count": len(clients_analysis["casual"]),
                "percentage": round((len(clients_analysis["casual"]) / total_clients) * 100, 1) if total_clients > 0 else 0
            },
            "frequent": {
                "count": len(clients_analysis["frequent"]),
                "percentage": round((len(clients_analysis["frequent"]) / total_clients) * 100, 1) if total_clients > 0 else 0
            },
            "premium": {
                "count": len(clients_analysis["premium"]),
                "percentage": round((len(clients_analysis["premium"]) / total_clients) * 100, 1) if total_clients > 0 else 0
            },
            "corporate": {
                "count": len(clients_analysis["corporate"]),
                "percentage": round((len(clients_analysis["corporate"]) / total_clients) * 100, 1) if total_clients > 0 else 0
            }
        }

        return {
            "period_days": days,
            "total_clients": total_clients,
            "distribution": distribution,
            "clients": clients_analysis,
            "insights": {
                "top_opportunity": "corporate" if len(clients_analysis["corporate"]) > 0 else "premium",
                "conversion_potential": len(clients_analysis["frequent"]) + len(clients_analysis["premium"]) + len(clients_analysis["corporate"]),
                "total_potential_revenue_contracts": sum(
                    c["estimated_revenue_clp"] for c in
                    clients_analysis["frequent"] + clients_analysis["premium"] + clients_analysis["corporate"]
                )
            }
        }

    except Exception as e:
        logger.error(f"Error analyzing clients: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recommendations")
async def get_contract_recommendations(
    min_visits: int = Query(default=5, description="Mínimo de visitas para recomendar contrato"),
    days: int = Query(default=30),
    db = Depends(get_db_session)
):
    """
    Recomendaciones de contratos

    Identifica clientes ideales para ofrecer contratos mensuales
    """
    try:
        cutoff_date = datetime.now(CHILE_TZ) - timedelta(days=days)

        query = text("""
            SELECT
                plate,
                COUNT(*) as visits,
                SUM(duration_minutes) / 60 as total_hours,
                SUM(duration_minutes / 60 * 5000) as current_cost,
                MIN(entry_time) as first_visit,
                MAX(entry_time) as last_visit
            FROM vehicle_records
            WHERE entry_time >= :cutoff_date
            AND exit_time IS NOT NULL
            GROUP BY plate
            HAVING COUNT(*) >= :min_visits
            ORDER BY visits DESC
            LIMIT 50
        """)

        result = await db.execute(query, {"cutoff_date": cutoff_date, "min_visits": min_visits})
        rows = result.fetchall()

        recommendations = []

        for row in rows:
            visits = row[1]
            current_cost = int(row[3])

            # Calcular plan recomendado
            if visits >= 20:
                plan = "Corporativo Mensual"
                monthly_fee = 800000
                discount = 0.30
            elif visits >= 11:
                plan = "Premium Mensual"
                monthly_fee = 500000
                discount = 0.20
            elif visits >= 5:
                plan = "Frecuente Mensual"
                monthly_fee = 300000
                discount = 0.15
            else:
                continue

            # Calcular ahorros
            cost_with_contract = monthly_fee
            savings = current_cost - cost_with_contract
            savings_percentage = (savings / current_cost) * 100 if current_cost > 0 else 0

            if savings > 0:  # Solo recomendar si hay ahorro
                recommendations.append({
                    "plate": row[0],
                    "current_usage": {
                        "visits": visits,
                        "total_hours": round(row[2], 2),
                        "monthly_cost_clp": current_cost
                    },
                    "recommended_plan": {
                        "name": plan,
                        "monthly_fee_clp": monthly_fee,
                        "discount_percentage": int(discount * 100),
                        "estimated_savings_clp": savings,
                        "savings_percentage": round(savings_percentage, 1)
                    },
                    "conversion_priority": "high" if savings_percentage > 25 else "medium",
                    "first_visit": row[4].isoformat() if row[4] else None,
                    "last_visit": row[5].isoformat() if row[5] else None
                })

        return {
            "period_days": days,
            "total_recommendations": len(recommendations),
            "recommendations": sorted(recommendations, key=lambda x: x["recommended_plan"]["estimated_savings_clp"], reverse=True),
            "total_potential_monthly_revenue": sum(r["recommended_plan"]["monthly_fee_clp"] for r in recommendations),
            "summary": {
                "high_priority": sum(1 for r in recommendations if r["conversion_priority"] == "high"),
                "medium_priority": sum(1 for r in recommendations if r["conversion_priority"] == "medium")
            }
        }

    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/contract/create")
async def create_contract(
    plate: str = Body(...),
    plan_type: str = Body(...),
    monthly_fee: int = Body(...),
    start_date: str = Body(...),
    duration_months: int = Body(default=1, ge=1, le=24)
):
    """
    Crear nuevo contrato

    En producción esto guardaría en tabla de contratos
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = start + timedelta(days=30 * duration_months)

        contract = {
            "contract_id": f"CONT-{plate}-{datetime.now().strftime('%Y%m%d')}",
            "plate": plate,
            "plan_type": plan_type,
            "monthly_fee_clp": monthly_fee,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "duration_months": duration_months,
            "status": ContractStatus.ACTIVE,
            "created_at": datetime.now(CHILE_TZ).isoformat(),
            "total_contract_value": monthly_fee * duration_months
        }

        # TODO: Guardar en base de datos
        CLIENTS_DB[plate] = contract

        return {
            "status": "success",
            "message": f"Contrato creado para {plate}",
            "contract": contract
        }

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    except Exception as e:
        logger.error(f"Error creating contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/contract/{plate}")
async def get_contract_status(
    plate: str,
    db = Depends(get_db_session)
):
    """
    Obtener estado de contrato de un cliente

    Muestra si tiene contrato activo y su uso
    """
    try:
        # Buscar contrato (en producción sería query a DB)
        contract = CLIENTS_DB.get(plate)

        # Obtener uso actual
        month_ago = datetime.now(CHILE_TZ) - timedelta(days=30)
        usage_query = text("""
            SELECT
                COUNT(*) as visits_this_month,
                SUM(duration_minutes) / 60 as hours_this_month
            FROM vehicle_records
            WHERE plate = :plate
            AND entry_time >= :month_ago
        """)

        result = await db.execute(usage_query, {"plate": plate, "month_ago": month_ago})
        row = result.fetchone()

        return {
            "plate": plate,
            "has_contract": contract is not None,
            "contract": contract if contract else None,
            "current_usage": {
                "visits_this_month": row[0] or 0,
                "hours_this_month": round(row[1], 2) if row[1] else 0
            },
            "status": ContractStatus.ACTIVE if contract else "no_contract"
        }

    except Exception as e:
        logger.error(f"Error getting contract status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/loyalty/program")
async def get_loyalty_program(
    db = Depends(get_db_session)
):
    """
    Programa de Lealtad

    Rankings y beneficios por uso
    """
    try:
        # Top clientes últimos 3 meses
        three_months_ago = datetime.now(CHILE_TZ) - timedelta(days=90)

        query = text("""
            SELECT
                plate,
                COUNT(*) as total_visits,
                SUM(duration_minutes) / 60 as total_hours,
                MIN(entry_time) as customer_since
            FROM vehicle_records
            WHERE entry_time >= :three_months_ago
            AND exit_time IS NOT NULL
            GROUP BY plate
            ORDER BY total_visits DESC
            LIMIT 100
        """)

        result = await db.execute(query, {"three_months_ago": three_months_ago})
        rows = result.fetchall()

        loyalty_tiers = {
            "platinum": [],  # Top 5%
            "gold": [],      # Top 15%
            "silver": [],    # Top 30%
            "bronze": []     # Top 50%
        }

        total_customers = len(rows)

        for idx, row in enumerate(rows):
            percentile = (idx / total_customers) * 100 if total_customers > 0 else 100

            loyalty_points = row[1] * 10  # 10 puntos por visita

            customer = {
                "rank": idx + 1,
                "plate": row[0],
                "visits": row[1],
                "total_hours": round(row[2], 2),
                "loyalty_points": loyalty_points,
                "customer_since": row[3].isoformat() if row[3] else None,
                "benefits": []
            }

            if percentile <= 5:
                customer["tier"] = "Platinum"
                customer["discount"] = "30%"
                customer["benefits"] = ["30% descuento", "Prioridad entrada/salida", "Soporte VIP"]
                loyalty_tiers["platinum"].append(customer)
            elif percentile <= 15:
                customer["tier"] = "Gold"
                customer["discount"] = "20%"
                customer["benefits"] = ["20% descuento", "Soporte prioritario"]
                loyalty_tiers["gold"].append(customer)
            elif percentile <= 30:
                customer["tier"] = "Silver"
                customer["discount"] = "15%"
                customer["benefits"] = ["15% descuento"]
                loyalty_tiers["silver"].append(customer)
            elif percentile <= 50:
                customer["tier"] = "Bronze"
                customer["discount"] = "10%"
                customer["benefits"] = ["10% descuento"]
                loyalty_tiers["bronze"].append(customer)

        return {
            "program_name": "EKAIA Loyalty",
            "period": "Últimos 90 días",
            "total_customers": total_customers,
            "tiers": {
                "platinum": {
                    "members": len(loyalty_tiers["platinum"]),
                    "benefits": "30% descuento + Prioridad + Soporte VIP",
                    "top_members": loyalty_tiers["platinum"][:10]
                },
                "gold": {
                    "members": len(loyalty_tiers["gold"]),
                    "benefits": "20% descuento + Soporte prioritario",
                    "top_members": loyalty_tiers["gold"][:10]
                },
                "silver": {
                    "members": len(loyalty_tiers["silver"]),
                    "benefits": "15% descuento",
                    "top_members": loyalty_tiers["silver"][:10]
                },
                "bronze": {
                    "members": len(loyalty_tiers["bronze"]),
                    "benefits": "10% descuento",
                    "top_members": loyalty_tiers["bronze"][:10]
                }
            }
        }

    except Exception as e:
        logger.error(f"Error getting loyalty program: {e}")
        raise HTTPException(status_code=500, detail=str(e))

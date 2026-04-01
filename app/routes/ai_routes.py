"""
AI-powered automation endpoints.

Available to:
  - Customers  — salon recommendations, churn risk (self-service)
  - Vendors    — pricing suggestions, booking summaries, demand forecast, customer churn
  - Admins     — full access
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.booking import Booking, BookingItem, BookingStatus
from app.models.salon import Salon, Service
from app.models.user import User, UserRole
from app.services.ai_service import ai_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Salon recommendations  (customers)
# ---------------------------------------------------------------------------

@router.get("/recommendations/salons")
async def get_salon_recommendations(
    city: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI-powered salon recommendations based on the customer's booking history."""
    # Past services booked by this customer
    past_service_names = (
        db.query(Service.name)
        .join(BookingItem, BookingItem.service_id == Service.id)
        .join(Booking, Booking.id == BookingItem.booking_id)
        .filter(Booking.customer_id == current_user.id)
        .distinct()
        .all()
    )
    past_services = [r[0] for r in past_service_names]

    salon_query = db.query(Salon).filter(Salon.is_active == True)
    if city:
        salon_query = salon_query.filter(Salon.city.ilike(f"%{city}%"))

    salons = salon_query.limit(30).all()
    available = []
    for s in salons:
        service_names = [svc.name for svc in s.services if svc.is_active]
        available.append({
            "name": s.name,
            "city": s.city,
            "services": service_names,
            "average_rating": s.average_rating,
            "total_reviews": s.total_reviews,
        })

    result = await ai_service.get_salon_recommendations(
        customer_name=f"{current_user.first_name} {current_user.last_name}",
        past_services=past_services,
        location=city or "Ghana",
        available_salons=available,
    )
    return result


# ---------------------------------------------------------------------------
# Review sentiment  (vendors and admins)
# ---------------------------------------------------------------------------

@router.post("/reviews/sentiment")
async def analyze_review_sentiment(
    review_text: str,
    current_user: User = Depends(get_current_user),
):
    """Analyse the sentiment of a review text."""
    if current_user.role not in (UserRole.VENDOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Vendor or admin access required")

    return await ai_service.analyze_review_sentiment(review_text)


# ---------------------------------------------------------------------------
# Pricing suggestion  (vendors)
# ---------------------------------------------------------------------------

@router.get("/pricing/suggest")
async def suggest_pricing(
    service_name: str,
    duration_minutes: int = Query(..., ge=5),
    current_price_ghs: float = Query(..., ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI pricing recommendation for a service based on the local market."""
    if current_user.role not in (UserRole.VENDOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Vendor or admin access required")

    salons = db.query(Salon).filter(Salon.owner_id == current_user.id).all()
    city = salons[0].city if salons else "Ghana"

    # Gather competitor prices for the same service name
    competitor_prices = (
        db.query(Service.price)
        .join(Salon, Salon.id == Service.salon_id)
        .filter(
            Service.name.ilike(f"%{service_name}%"),
            Service.is_active == True,
            Salon.owner_id != current_user.id,
        )
        .limit(20)
        .all()
    )
    prices = [float(r[0]) for r in competitor_prices]

    return await ai_service.suggest_pricing(
        service_name=service_name,
        duration_minutes=duration_minutes,
        city=city,
        current_price_ghs=current_price_ghs,
        competitor_prices=prices,
    )


# ---------------------------------------------------------------------------
# Booking summary  (vendors)
# ---------------------------------------------------------------------------

@router.get("/bookings/{booking_id}/summary")
async def get_booking_ai_summary(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate an AI natural-language summary for a booking."""
    if current_user.role not in (UserRole.VENDOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Vendor or admin access required")

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Verify vendor owns this booking's salon
    if current_user.role == UserRole.VENDOR and booking.salon.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your booking")

    service_names = [item.service.name for item in booking.items if item.service]

    summary = await ai_service.generate_booking_summary({
        "customer_name": f"{booking.customer.first_name} {booking.customer.last_name}",
        "services": service_names,
        "booking_date": str(booking.booking_date),
        "total_amount": float(booking.total_amount),
        "special_requests": booking.special_requests,
    })

    return {"booking_id": booking_id, "summary": summary}


# ---------------------------------------------------------------------------
# Fraud risk assessment  (internal — used at booking creation)
# ---------------------------------------------------------------------------

@router.post("/bookings/risk-check")
async def assess_booking_risk(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run a fraud/risk assessment on an existing booking."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    customer = booking.customer
    account_age = (datetime.utcnow() - customer.created_at.replace(tzinfo=None)).days
    total_bookings = db.query(Booking).filter(Booking.customer_id == customer.id).count()
    recent_bookings = db.query(Booking).filter(
        Booking.customer_id == customer.id,
        Booking.created_at >= datetime.utcnow() - timedelta(hours=24),
    ).count()

    service_names = [item.service.name for item in booking.items if item.service]

    return await ai_service.assess_booking_risk({
        "customer_age_days": account_age,
        "total_bookings_history": total_bookings,
        "booking_amount_ghs": float(booking.total_amount),
        "services": service_names,
        "payment_method": str(booking.payment.payment_method) if booking.payment else "unknown",
        "bookings_last_24h": recent_bookings,
    })


# ---------------------------------------------------------------------------
# Customer churn risk  (vendors + admins)
# ---------------------------------------------------------------------------

@router.get("/customers/{customer_id}/churn-risk")
async def customer_churn_risk(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Predict the churn risk for a specific customer."""
    if current_user.role not in (UserRole.VENDOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Vendor or admin access required")

    customer = db.query(User).filter(User.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    bookings = db.query(Booking).filter(Booking.customer_id == customer_id).all()
    total_bookings = len(bookings)
    cancelled = sum(1 for b in bookings if b.status == BookingStatus.CANCELLED)
    cancellation_rate = cancelled / total_bookings if total_bookings else 0

    last_booking = max((b.created_at for b in bookings), default=None)
    days_since_last = (datetime.utcnow() - last_booking.replace(tzinfo=None)).days if last_booking else 999

    months_active = (datetime.utcnow() - customer.created_at.replace(tzinfo=None)).days // 30

    return await ai_service.predict_churn_risk({
        "days_since_last_booking": days_since_last,
        "total_bookings": total_bookings,
        "avg_rating_given": 4.5,  # placeholder until review ratings per customer are tracked
        "cancellation_rate": cancellation_rate,
        "months_active": months_active,
    })


# ---------------------------------------------------------------------------
# Demand forecast  (vendors)
# ---------------------------------------------------------------------------

@router.get("/forecast/demand")
async def demand_forecast(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Forecast booking demand for the next 7 days based on historical data."""
    if current_user.role not in (UserRole.VENDOR, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Vendor or admin access required")

    salon_ids = [
        s.id for s in db.query(Salon.id).filter(Salon.owner_id == current_user.id).all()
    ]
    if not salon_ids:
        return {"forecast": [], "peak_days": [], "trend": "stable"}

    daily = (
        db.query(func.date(Booking.created_at).label("date"), func.count(Booking.id).label("count"))
        .filter(
            Booking.salon_id.in_(salon_ids),
            Booking.created_at >= datetime.utcnow() - timedelta(days=60),
        )
        .group_by(func.date(Booking.created_at))
        .order_by(func.date(Booking.created_at))
        .all()
    )

    historical = [{"date": str(r.date), "bookings": r.count} for r in daily]
    return await ai_service.forecast_demand(historical)

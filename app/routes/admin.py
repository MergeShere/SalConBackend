"""
Admin dashboard routes.

All endpoints require an authenticated user with role == "admin".

Sections:
  - Dashboard overview
  - User management
  - Vendor management + KYC review
  - Salon management
  - Booking management
  - Payment management
  - Subscription / revenue analytics
  - Platform reports
  - Content moderation (reviews)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, and_, extract
from sqlalchemy.orm import Session, joinedload

from app.core.dependencies import get_current_user
from app.core.config import settings
from app.database import get_db
from app.models.booking import Booking, BookingStatus
from app.models.kyc import KYCAuditLog, VendorKYC
from app.models.payment import Payment, PaymentStatus
from app.models.salon import Review, Salon, Service
from app.models.user import User, UserRole

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency: admin only
# ---------------------------------------------------------------------------

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ---------------------------------------------------------------------------
# 1. Dashboard overview
# ---------------------------------------------------------------------------

@router.get("/dashboard")
def admin_dashboard(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    High-level platform snapshot:
    total users, vendors, salons, bookings, revenue, pending KYC requests.
    """
    now = datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_30 = now - timedelta(days=30)

    total_users      = db.query(User).filter(User.role == UserRole.CUSTOMER).count()
    total_vendors    = db.query(User).filter(User.role == UserRole.VENDOR).count()
    total_salons     = db.query(Salon).count()
    total_bookings   = db.query(Booking).count()
    pending_kyc      = db.query(VendorKYC).filter(VendorKYC.status == "processing").count()
    active_trials    = db.query(User).filter(
        User.subscription_plan == "premium_trial",
        User.subscription_expires_at > now,
    ).count()
    expired_trials   = db.query(User).filter(
        User.subscription_plan == "premium_trial",
        User.subscription_expires_at <= now,
    ).count()

    total_revenue = (
        db.query(func.sum(Payment.amount))
        .filter(Payment.status == PaymentStatus.SUCCESSFUL)
        .scalar() or 0
    )
    monthly_revenue = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.status == PaymentStatus.SUCCESSFUL,
            Payment.created_at >= start_of_month,
        )
        .scalar() or 0
    )

    new_users_30d    = db.query(User).filter(User.created_at >= last_30).count()
    new_bookings_30d = db.query(Booking).filter(Booking.created_at >= last_30).count()

    # Recent activity
    recent_kyc = (
        db.query(VendorKYC)
        .options(joinedload(VendorKYC.vendor))
        .filter(VendorKYC.status.in_(["processing", "pending"]))
        .order_by(VendorKYC.created_at.desc())
        .limit(5)
        .all()
    )
    recent_bookings = (
        db.query(Booking)
        .options(joinedload(Booking.customer), joinedload(Booking.salon))
        .order_by(Booking.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "users": {
            "total_customers": total_users,
            "total_vendors": total_vendors,
            "new_last_30_days": new_users_30d,
        },
        "salons": {"total": total_salons},
        "bookings": {
            "total": total_bookings,
            "new_last_30_days": new_bookings_30d,
        },
        "revenue": {
            "total_ghs": float(total_revenue),
            "monthly_ghs": float(monthly_revenue),
        },
        "kyc": {
            "pending_review": pending_kyc,
        },
        "subscriptions": {
            "active_trials": active_trials,
            "expired_trials": expired_trials,
        },
        "recent_kyc_requests": [
            {
                "id": k.id,
                "vendor_id": k.vendor_id,
                "vendor_name": f"{k.vendor.first_name} {k.vendor.last_name}" if k.vendor else None,
                "vendor_email": k.vendor.email if k.vendor else None,
                "status": k.status,
                "method": "metamap" if k.metamap_verification_id else "manual",
                "created_at": k.created_at,
            }
            for k in recent_kyc
        ],
        "recent_bookings": [
            {
                "id": b.id,
                "customer": f"{b.customer.first_name} {b.customer.last_name}",
                "salon": b.salon.name,
                "status": b.status,
                "amount": float(b.total_amount),
                "date": b.booking_date,
            }
            for b in recent_bookings
        ],
    }


# ---------------------------------------------------------------------------
# 2. User management
# ---------------------------------------------------------------------------

@router.get("/users")
def list_users(
    role: Optional[str] = Query(None, regex="^(customer|vendor|admin)$"),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users with filtering and pagination."""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if search:
        term = f"%{search}%"
        query = query.filter(
            User.email.ilike(term)
            | User.first_name.ilike(term)
            | User.last_name.ilike(term)
            | User.phone_number.ilike(term)
        )

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "phone_number": u.phone_number,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "role": u.role,
                "is_active": u.is_active,
                "is_verified": u.is_verified,
                "kyc_verified": u.kyc_verified,
                "subscription_plan": u.subscription_plan,
                "subscription_expires_at": u.subscription_expires_at,
                "created_at": u.created_at,
            }
            for u in users
        ],
    }


@router.get("/users/{user_id}")
def get_user_detail(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get full detail for a single user."""
    user = db.query(User).options(joinedload(User.profile), joinedload(User.kyc_data)).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "email": user.email,
        "phone_number": user.phone_number,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "kyc_verified": user.kyc_verified,
        "subscription_plan": user.subscription_plan,
        "subscription_expires_at": user.subscription_expires_at,
        "trial_start_date": user.trial_start_date,
        "google_id": user.google_id,
        "is_oauth_user": user.is_oauth_user,
        "created_at": user.created_at,
        "profile": {
            "bio": user.profile.bio if user.profile else None,
            "city": user.profile.city if user.profile else None,
            "country": user.profile.country if user.profile else None,
            "profile_picture": user.profile.profile_picture if user.profile else None,
        },
        "kyc": {
            "status": user.kyc_data.status if user.kyc_data else None,
            "method": "metamap" if (user.kyc_data and user.kyc_data.metamap_verification_id) else "manual",
            "created_at": user.kyc_data.created_at if user.kyc_data else None,
        } if user.kyc_data else None,
    }


@router.patch("/users/{user_id}/status")
def toggle_user_status(
    user_id: int,
    is_active: bool,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Activate or deactivate a user account."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Cannot modify admin accounts")

    user.is_active = is_active
    db.commit()
    return {"message": f"User {'activated' if is_active else 'deactivated'}", "user_id": user_id}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Permanently delete a user (irreversible — use with caution)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Cannot delete admin accounts")

    db.delete(user)
    db.commit()
    return {"message": "User deleted", "user_id": user_id}


# ---------------------------------------------------------------------------
# 3. Vendor management
# ---------------------------------------------------------------------------

@router.get("/vendors")
def list_vendors(
    kyc_status: Optional[str] = Query(None),
    subscription: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List vendors with their KYC and subscription status."""
    query = (
        db.query(User)
        .options(joinedload(User.kyc_data), joinedload(User.salons))
        .filter(User.role == UserRole.VENDOR)
    )

    if subscription:
        query = query.filter(User.subscription_plan == subscription)

    total = query.count()
    vendors = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    now = datetime.utcnow()

    result = []
    for v in vendors:
        kyc = v.kyc_data
        if kyc_status and (not kyc or kyc.status != kyc_status):
            continue

        days_left = None
        if v.subscription_expires_at and v.subscription_expires_at > now:
            days_left = (v.subscription_expires_at - now).days

        result.append({
            "id": v.id,
            "email": v.email,
            "name": f"{v.first_name} {v.last_name}",
            "phone_number": v.phone_number,
            "is_active": v.is_active,
            "kyc_verified": v.kyc_verified,
            "kyc_status": kyc.status if kyc else "not_started",
            "kyc_method": "metamap" if (kyc and kyc.metamap_verification_id) else "manual" if kyc else None,
            "subscription_plan": v.subscription_plan,
            "trial_days_remaining": days_left,
            "subscription_expires_at": v.subscription_expires_at,
            "total_salons": len(v.salons),
            "created_at": v.created_at,
        })

    return {"total": total, "page": page, "limit": limit, "vendors": result}


# ---------------------------------------------------------------------------
# 4. KYC management
# ---------------------------------------------------------------------------

@router.get("/kyc/pending")
def list_pending_kyc(
    method: Optional[str] = Query(None, regex="^(metamap|manual)$"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all KYC submissions awaiting admin review."""
    query = (
        db.query(VendorKYC)
        .options(joinedload(VendorKYC.vendor))
        .filter(VendorKYC.status.in_(["processing", "pending"]))
    )
    if method == "metamap":
        query = query.filter(VendorKYC.metamap_verification_id.isnot(None))
    elif method == "manual":
        query = query.filter(VendorKYC.metamap_verification_id.is_(None))

    records = query.order_by(VendorKYC.created_at.asc()).all()

    return {
        "total": len(records),
        "records": [
            {
                "id": r.id,
                "vendor_id": r.vendor_id,
                "vendor_name": f"{r.vendor.first_name} {r.vendor.last_name}" if r.vendor else None,
                "vendor_email": r.vendor.email if r.vendor else None,
                "status": r.status,
                "method": "metamap" if r.metamap_verification_id else "manual",
                "metamap_status": r.metamap_status,
                "id_type": r.id_type,
                "face_match_score": r.face_match_score,
                "risk_score": r.risk_score,
                "created_at": r.created_at,
            }
            for r in records
        ],
    }


@router.get("/kyc/{kyc_id}")
def get_kyc_detail(
    kyc_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get full KYC record details including MetaMap metadata and audit trail."""
    record = (
        db.query(VendorKYC)
        .options(joinedload(VendorKYC.vendor))
        .filter(VendorKYC.id == kyc_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="KYC record not found")

    audit_logs = (
        db.query(KYCAuditLog)
        .filter(KYCAuditLog.kyc_id == kyc_id)
        .order_by(KYCAuditLog.performed_at.desc())
        .all()
    )

    return {
        "id": record.id,
        "vendor_id": record.vendor_id,
        "vendor": {
            "id": record.vendor.id,
            "name": f"{record.vendor.first_name} {record.vendor.last_name}",
            "email": record.vendor.email,
            "phone": record.vendor.phone_number,
        } if record.vendor else None,
        "status": record.status,
        "method": "metamap" if record.metamap_verification_id else "manual",
        "id_type": record.id_type,
        "full_name": record.full_name,
        "date_of_birth": record.date_of_birth,
        "id_front_url": record.id_front_url,
        "id_back_url": record.id_back_url,
        "selfie_url": record.selfie_url,
        "face_match_score": record.face_match_score,
        "face_match_status": record.face_match_status,
        "document_verification_status": record.document_verification_status,
        "is_document_valid": record.is_document_valid,
        "risk_score": record.risk_score,
        "ai_analysis": record.ai_analysis,
        "metamap_verification_id": record.metamap_verification_id,
        "metamap_status": record.metamap_status,
        "metamap_verified_at": record.metamap_verified_at,
        "metamap_metadata": record.metamap_metadata,
        "rejection_reason": record.rejection_reason,
        "trial_activated_at": record.trial_activated_at,
        "reviewed_at": record.reviewed_at,
        "created_at": record.created_at,
        "audit_logs": [
            {
                "action": a.action,
                "performed_at": a.performed_at,
                "ip_address": a.ip_address,
                "details": a.details,
            }
            for a in audit_logs
        ],
    }


@router.patch("/kyc/{kyc_id}/review")
def review_kyc(
    kyc_id: int,
    decision: str = Query(..., regex="^(approve|reject)$"),
    rejection_reason: Optional[str] = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Manually approve or reject a KYC submission.

    Approving grants the vendor a 30-day free trial (same as the automated flow).
    """
    record = (
        db.query(VendorKYC)
        .options(joinedload(VendorKYC.vendor))
        .filter(VendorKYC.id == kyc_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="KYC record not found")

    now = datetime.utcnow()

    if decision == "approve":
        record.status = "approved"
        record.reviewed_by = admin.id
        record.reviewed_at = now
        record.trial_activated_at = record.trial_activated_at or now

        vendor = record.vendor
        if vendor:
            vendor.kyc_verified = True
            vendor.subscription_plan = "premium_trial"
            vendor.trial_start_date = vendor.trial_start_date or now
            vendor.subscription_expires_at = (
                vendor.subscription_expires_at
                if vendor.subscription_expires_at and vendor.subscription_expires_at > now
                else now + timedelta(days=settings.TRIAL_DAYS)
            )

            try:
                from app.services.email import EmailService
                EmailService.send_trial_started_email(
                    email=vendor.email,
                    first_name=vendor.first_name,
                    expiry_date=vendor.subscription_expires_at,
                )
            except Exception as exc:
                logger.error("Could not send trial email: %s", exc)

    else:
        if not rejection_reason:
            raise HTTPException(status_code=400, detail="rejection_reason is required when rejecting")
        record.status = "rejected"
        record.rejection_reason = rejection_reason
        record.reviewed_by = admin.id
        record.reviewed_at = now

    audit = KYCAuditLog(
        kyc_id=record.id,
        action=f"admin_{decision}d",
        performed_by=admin.id,
        details={"decision": decision, "reason": rejection_reason},
    )
    db.add(audit)
    db.commit()

    return {"message": f"KYC {decision}d", "kyc_id": kyc_id}


# ---------------------------------------------------------------------------
# 5. Salon management
# ---------------------------------------------------------------------------

@router.get("/salons")
def list_salons(
    is_verified: Optional[bool] = Query(None),
    city: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all salons with filtering."""
    query = db.query(Salon).options(joinedload(Salon.owner))

    if is_verified is not None:
        query = query.filter(Salon.is_verified == is_verified)
    if city:
        query = query.filter(Salon.city.ilike(f"%{city}%"))
    if search:
        term = f"%{search}%"
        query = query.filter(Salon.name.ilike(term) | Salon.email.ilike(term))

    total = query.count()
    salons = query.order_by(Salon.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "salons": [
            {
                "id": s.id,
                "name": s.name,
                "city": s.city,
                "owner_email": s.owner.email if s.owner else None,
                "is_active": s.is_active,
                "is_verified": s.is_verified,
                "average_rating": s.average_rating,
                "total_reviews": s.total_reviews,
                "created_at": s.created_at,
            }
            for s in salons
        ],
    }


@router.patch("/salons/{salon_id}/verify")
def verify_salon(
    salon_id: int,
    is_verified: bool,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Toggle salon verified status."""
    salon = db.query(Salon).filter(Salon.id == salon_id).first()
    if not salon:
        raise HTTPException(status_code=404, detail="Salon not found")

    salon.is_verified = is_verified
    db.commit()
    return {"message": f"Salon {'verified' if is_verified else 'unverified'}", "salon_id": salon_id}


# ---------------------------------------------------------------------------
# 6. Booking management
# ---------------------------------------------------------------------------

@router.get("/bookings")
def list_bookings(
    booking_status: Optional[str] = Query(None, alias="status"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all bookings across the platform."""
    query = db.query(Booking).options(
        joinedload(Booking.customer), joinedload(Booking.salon)
    )

    if booking_status:
        query = query.filter(Booking.status == booking_status)
    if start_date:
        query = query.filter(Booking.booking_date >= start_date)
    if end_date:
        query = query.filter(Booking.booking_date <= end_date)

    total = query.count()
    bookings = query.order_by(Booking.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "bookings": [
            {
                "id": b.id,
                "customer": f"{b.customer.first_name} {b.customer.last_name}",
                "customer_email": b.customer.email,
                "salon": b.salon.name,
                "booking_date": b.booking_date,
                "status": b.status,
                "total_amount": float(b.total_amount),
                "currency": b.currency,
                "created_at": b.created_at,
            }
            for b in bookings
        ],
    }


# ---------------------------------------------------------------------------
# 7. Payment management
# ---------------------------------------------------------------------------

@router.get("/payments")
def list_payments(
    payment_status: Optional[str] = Query(None, alias="status"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all payments across the platform."""
    query = db.query(Payment).options(joinedload(Payment.booking))

    if payment_status:
        query = query.filter(Payment.status == payment_status)
    if start_date:
        query = query.filter(Payment.created_at >= start_date)
    if end_date:
        query = query.filter(Payment.created_at <= end_date)

    total = query.count()
    payments = query.order_by(Payment.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "payments": [
            {
                "id": p.id,
                "reference": p.reference,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status,
                "payment_method": p.payment_method,
                "paid_at": p.paid_at,
                "created_at": p.created_at,
            }
            for p in payments
        ],
    }


# ---------------------------------------------------------------------------
# 8. Platform analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/overview")
def analytics_overview(
    period: str = Query("month", regex="^(week|month|year)$"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Time-series analytics for the platform:
    new users, new bookings, and revenue grouped by day/week.
    """
    now = datetime.utcnow()
    if period == "week":
        since = now - timedelta(days=7)
        trunc = func.date(User.created_at)
    elif period == "month":
        since = now - timedelta(days=30)
        trunc = func.date(User.created_at)
    else:
        since = now - timedelta(days=365)
        trunc = func.date_trunc("month", User.created_at) if db.bind.dialect.name == "postgresql" else func.strftime("%Y-%m", User.created_at)

    user_growth = (
        db.query(func.date(User.created_at).label("date"), func.count(User.id).label("count"))
        .filter(User.created_at >= since)
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
        .all()
    )

    booking_trend = (
        db.query(func.date(Booking.created_at).label("date"), func.count(Booking.id).label("count"))
        .filter(Booking.created_at >= since)
        .group_by(func.date(Booking.created_at))
        .order_by(func.date(Booking.created_at))
        .all()
    )

    revenue_trend = (
        db.query(
            func.date(Payment.created_at).label("date"),
            func.sum(Payment.amount).label("revenue"),
        )
        .filter(Payment.status == PaymentStatus.SUCCESSFUL, Payment.created_at >= since)
        .group_by(func.date(Payment.created_at))
        .order_by(func.date(Payment.created_at))
        .all()
    )

    return {
        "period": period,
        "user_growth": [{"date": str(r.date), "count": r.count} for r in user_growth],
        "booking_trend": [{"date": str(r.date), "count": r.count} for r in booking_trend],
        "revenue_trend": [{"date": str(r.date), "revenue": float(r.revenue or 0)} for r in revenue_trend],
    }


@router.get("/analytics/revenue")
def revenue_analytics(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Aggregate revenue metrics."""
    now = datetime.utcnow()

    def revenue_for_period(since: datetime) -> float:
        return float(
            db.query(func.sum(Payment.amount))
            .filter(Payment.status == PaymentStatus.SUCCESSFUL, Payment.created_at >= since)
            .scalar() or 0
        )

    total   = float(db.query(func.sum(Payment.amount)).filter(Payment.status == PaymentStatus.SUCCESSFUL).scalar() or 0)
    today   = revenue_for_period(now.replace(hour=0, minute=0, second=0))
    week    = revenue_for_period(now - timedelta(days=7))
    month   = revenue_for_period(now - timedelta(days=30))
    year    = revenue_for_period(now - timedelta(days=365))

    by_method = (
        db.query(Payment.payment_method, func.sum(Payment.amount).label("total"))
        .filter(Payment.status == PaymentStatus.SUCCESSFUL)
        .group_by(Payment.payment_method)
        .all()
    )

    return {
        "total_revenue_ghs": total,
        "today_ghs": today,
        "last_7_days_ghs": week,
        "last_30_days_ghs": month,
        "last_year_ghs": year,
        "by_payment_method": [
            {"method": str(r.payment_method), "total_ghs": float(r.total or 0)}
            for r in by_method
        ],
    }


# ---------------------------------------------------------------------------
# 9. Reports
# ---------------------------------------------------------------------------

@router.get("/reports/users")
def user_report(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """User registration and role distribution report."""
    now = datetime.utcnow()

    total     = db.query(User).count()
    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).count()
    vendors   = db.query(User).filter(User.role == UserRole.VENDOR).count()
    admins    = db.query(User).filter(User.role == UserRole.ADMIN).count()
    verified  = db.query(User).filter(User.is_verified == True).count()
    oauth     = db.query(User).filter(User.is_oauth_user == True).count()

    this_month = db.query(User).filter(
        User.created_at >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ).count()

    return {
        "total_users": total,
        "by_role": {"customers": customers, "vendors": vendors, "admins": admins},
        "email_verified": verified,
        "oauth_users": oauth,
        "registered_this_month": this_month,
    }


@router.get("/reports/bookings")
def booking_report(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Booking status distribution and top-performing salons."""
    by_status = (
        db.query(Booking.status, func.count(Booking.id).label("count"))
        .group_by(Booking.status)
        .all()
    )

    top_salons = (
        db.query(Salon.name, func.count(Booking.id).label("bookings"))
        .join(Booking, Booking.salon_id == Salon.id)
        .group_by(Salon.id, Salon.name)
        .order_by(func.count(Booking.id).desc())
        .limit(10)
        .all()
    )

    return {
        "by_status": [{"status": str(r.status), "count": r.count} for r in by_status],
        "top_salons_by_bookings": [
            {"salon": r.name, "bookings": r.bookings} for r in top_salons
        ],
    }


@router.get("/reports/subscriptions")
def subscription_report(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Subscription and trial status across all vendors."""
    now = datetime.utcnow()

    by_plan = (
        db.query(User.subscription_plan, func.count(User.id).label("count"))
        .filter(User.role == UserRole.VENDOR)
        .group_by(User.subscription_plan)
        .all()
    )

    expiring_soon = (
        db.query(User)
        .filter(
            User.subscription_plan == "premium_trial",
            User.subscription_expires_at > now,
            User.subscription_expires_at <= now + timedelta(days=7),
        )
        .all()
    )

    expired = (
        db.query(User)
        .filter(
            User.subscription_plan == "premium_trial",
            User.subscription_expires_at <= now,
        )
        .count()
    )

    return {
        "by_plan": [{"plan": r.subscription_plan, "count": r.count} for r in by_plan],
        "trials_expiring_in_7_days": [
            {
                "id": u.id,
                "email": u.email,
                "name": f"{u.first_name} {u.last_name}",
                "expires_at": u.subscription_expires_at,
            }
            for u in expiring_soon
        ],
        "expired_trials": expired,
    }


# ---------------------------------------------------------------------------
# 10. Content moderation
# ---------------------------------------------------------------------------

@router.get("/reviews")
def list_reviews(
    is_approved: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all reviews, optionally filtering by approval status."""
    query = db.query(Review)
    if is_approved is not None:
        query = query.filter(Review.is_approved == is_approved)

    total   = query.count()
    reviews = query.order_by(Review.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "reviews": [
            {
                "id": r.id,
                "salon_id": r.salon_id,
                "customer_id": r.customer_id,
                "rating": r.rating,
                "comment": r.comment,
                "is_approved": r.is_approved,
                "created_at": r.created_at,
            }
            for r in reviews
        ],
    }


@router.patch("/reviews/{review_id}/moderate")
def moderate_review(
    review_id: int,
    is_approved: bool,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve or remove a customer review."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_approved = is_approved
    db.commit()
    return {
        "message": f"Review {'approved' if is_approved else 'hidden'}",
        "review_id": review_id,
    }


# ---------------------------------------------------------------------------
# 11. Subscription — manual grant
# ---------------------------------------------------------------------------

@router.post("/subscriptions/grant")
def grant_subscription(
    vendor_id: int,
    plan: str = Query(..., regex="^(premium_trial|premium|free)$"),
    days: int = Query(30, ge=1, le=365),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Manually grant or extend a subscription for a vendor.
    Useful for support, promotions, or rectifying failed payments.
    """
    vendor = db.query(User).filter(User.id == vendor_id, User.role == UserRole.VENDOR).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    now = datetime.utcnow()
    vendor.subscription_plan = plan
    vendor.subscription_expires_at = now + timedelta(days=days)
    if plan != "free":
        vendor.trial_start_date = vendor.trial_start_date or now

    db.commit()
    return {
        "message": f"Granted {plan} for {days} days",
        "vendor_id": vendor_id,
        "expires_at": vendor.subscription_expires_at,
    }

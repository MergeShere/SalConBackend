from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime, date, timedelta

from app.database import get_db
from app.schemas.salon import SalonResponse, SalonCreate, ServiceResponse, ServiceCreate
from app.schemas.booking import BookingResponse
from app.core.security import verify_token
from app.services.auth import AuthService
from app.services.salon_service import SalonService
from app.services.booking_service import BookingService
from app.services.metamap_service import MetaMapService
from app.core.cloudinary import upload_image
from app.models.user import User
from app.models.salon import Salon, Service, SalonImage, Review
from app.models.booking import Booking, BookingStatus
from app.models.payment import Payment, PaymentStatus
from app.models.kyc import VendorKYC

router = APIRouter()


async def get_current_vendor(token: str, db: Session = Depends(get_db)):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    user_id = payload.get("user_id")
    user = AuthService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    if user.role != "vendor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor access required"
        )
    
    return user



@router.post("/salons", response_model=SalonResponse)
def create_salon(
    salon_data: SalonCreate,
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Create a new salon (Vendor only)"""
    return SalonService.create_salon(db, salon_data, vendor.id)

@router.get("/salons", response_model=List[SalonResponse])
def get_my_salons(
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Get all salons owned by current vendor"""
    return SalonService.get_user_salons(db, vendor.id)

@router.put("/salons/{salon_id}", response_model=SalonResponse)
def update_salon(
    salon_id: int,
    salon_data: dict,  
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Update salon information (Owner only)"""
    salon = SalonService.get_salon_by_id(db, salon_id)
    if not salon:
        raise HTTPException(status_code=404, detail="Salon not found")
    
    if salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this salon")
    
    return SalonService.update_salon(db, salon_id, salon_data)

@router.post("/salons/{salon_id}/images")
def upload_salon_images(
    salon_id: int,
    files: List[UploadFile] = File(...),
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Upload multiple images for a salon"""
    salon = SalonService.get_salon_by_id(db, salon_id)
    if not salon:
        raise HTTPException(status_code=404, detail="Salon not found")
    
    if salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    uploaded_images = []
    for file in files:
        if not file.content_type.startswith('image/'):
            continue
        
        try:
            result = upload_image(file.file, folder=f"salon_connect/salons/{salon_id}")
            image_url = result.get('secure_url')
            
            
            salon_image = SalonImage(
                salon_id=salon_id,
                image_url=image_url,
                is_primary=False
            )
            db.add(salon_image)
            uploaded_images.append(image_url)
            
        except Exception as e:
            continue
    
    db.commit()
    return {"message": f"Uploaded {len(uploaded_images)} images", "images": uploaded_images}



@router.post("/salons/{salon_id}/services", response_model=ServiceResponse)
def create_service(
    salon_id: int,
    service_data: ServiceCreate,
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Create a new service for a salon (Owner only)"""
    salon = SalonService.get_salon_by_id(db, salon_id)
    if not salon:
        raise HTTPException(status_code=404, detail="Salon not found")
    
    if salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized to create services for this salon")
    
    return SalonService.create_service(db, salon_id, service_data)

@router.put("/services/{service_id}", response_model=ServiceResponse)
def update_service(
    service_id: int,
    service_data: dict,
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Update service information"""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    salon = SalonService.get_salon_by_id(db, service.salon_id)
    if salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this service")
    
    for field, value in service_data.items():
        if hasattr(service, field) and value is not None:
            setattr(service, field, value)
    
    db.commit()
    db.refresh(service)
    return service

@router.delete("/services/{service_id}")
def delete_service(
    service_id: int,
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Soft delete a service"""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    salon = SalonService.get_salon_by_id(db, service.salon_id)
    if salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this service")
    
    service.is_active = False
    db.commit()
    return {"message": "Service deleted successfully"}



@router.get("/bookings", response_model=List[BookingResponse])
def get_vendor_bookings(
    status: Optional[str] = Query(None),
    salon_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Get all bookings for vendor's salons with filters"""
    return BookingService.get_vendor_bookings(db, vendor.id, status, salon_id, start_date, end_date)

@router.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking_details(
    booking_id: int,
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Get detailed booking information"""
    booking = BookingService.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if booking.salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this booking")
    
    return booking

@router.put("/bookings/{booking_id}/status")
def update_booking_status(
    booking_id: int,
    status: BookingStatus,
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Update booking status (Vendor only)"""
    booking = BookingService.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    if booking.salon.owner_id != vendor.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this booking")
    
    booking.status = status
    db.commit()
    db.refresh(booking)
    
    return {"message": f"Booking status updated to {status}", "booking": booking}

@router.get("/bookings/stats")
def get_booking_stats(
    period: str = Query("today", regex="^(today|week|month|year)$"),
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Get booking statistics for vendor"""
    from sqlalchemy import func, and_
    
    
    salons = db.query(Salon).filter(Salon.owner_id == vendor.id).all()
    salon_ids = [salon.id for salon in salons]
    
    if not salon_ids:
        return {
            "total_bookings": 0,
            "pending_bookings": 0,
            "confirmed_bookings": 0,
            "completed_bookings": 0,
            "revenue": 0
        }
    
    
    today = datetime.now().date()
    if period == "today":
        date_filter = func.date(Booking.created_at) == today
    elif period == "week":
        date_filter = Booking.created_at >= today - timedelta(days=7)
    elif period == "month":
        date_filter = Booking.created_at >= today - timedelta(days=30)
    else:  
        date_filter = Booking.created_at >= today - timedelta(days=365)
    
    
    total_bookings = db.query(Booking).filter(
        Booking.salon_id.in_(salon_ids),
        date_filter
    ).count()
    
    pending_bookings = db.query(Booking).filter(
        Booking.salon_id.in_(salon_ids),
        Booking.status == BookingStatus.PENDING,
        date_filter
    ).count()
    
    confirmed_bookings = db.query(Booking).filter(
        Booking.salon_id.in_(salon_ids),
        Booking.status == BookingStatus.CONFIRMED,
        date_filter
    ).count()
    
    completed_bookings = db.query(Booking).filter(
        Booking.salon_id.in_(salon_ids),
        Booking.status == BookingStatus.COMPLETED,
        date_filter
    ).count()
    
    
    revenue_result = db.query(func.sum(Booking.total_amount)).filter(
        Booking.salon_id.in_(salon_ids),
        Booking.status == BookingStatus.COMPLETED,
        date_filter
    ).scalar() or 0
    
    return {
        "total_bookings": total_bookings,
        "pending_bookings": pending_bookings,
        "confirmed_bookings": confirmed_bookings,
        "completed_bookings": completed_bookings,
        "revenue": float(revenue_result),
        "period": period
    }



@router.get("/dashboard/overview")
def get_vendor_overview(
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Get comprehensive vendor dashboard overview"""
    from sqlalchemy import func
    
    
    total_salons = db.query(Salon).filter(Salon.owner_id == vendor.id).count()
    salon_ids = [salon.id for salon in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()]
    
    
    total_bookings = db.query(Booking).filter(Booking.salon_id.in_(salon_ids)).count() if salon_ids else 0
    today_bookings = db.query(Booking).filter(
        Booking.salon_id.in_(salon_ids),
        func.date(Booking.created_at) == datetime.now().date()
    ).count() if salon_ids else 0
    
    
    total_revenue = db.query(func.sum(Booking.total_amount)).filter(
        Booking.salon_id.in_(salon_ids),
        Booking.status == BookingStatus.COMPLETED
    ).scalar() or 0
    
    monthly_revenue = db.query(func.sum(Booking.total_amount)).filter(
        Booking.salon_id.in_(salon_ids),
        Booking.status == BookingStatus.COMPLETED,
        func.extract('month', Booking.created_at) == datetime.now().month
    ).scalar() or 0
    
    
    recent_bookings = db.query(Booking).filter(
        Booking.salon_id.in_(salon_ids)
    ).order_by(Booking.created_at.desc()).limit(5).all() if salon_ids else []
    
    return {
        "total_salons": total_salons,
        "total_bookings": total_bookings,
        "today_bookings": today_bookings,
        "total_revenue": float(total_revenue),
        "monthly_revenue": float(monthly_revenue),
        "recent_bookings": [
            {
                "id": booking.id,
                "customer_name": f"{booking.customer.first_name} {booking.customer.last_name}",
                "salon_name": booking.salon.name,
                "booking_date": booking.booking_date,
                "status": booking.status,
                "total_amount": booking.total_amount
            }
            for booking in recent_bookings
        ]
    }

@router.get("/revenue/analytics")
def get_revenue_analytics(
    period: str = Query("month", regex="^(week|month|year)$"),
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db)
):
    """Get revenue analytics for charts"""
    from sqlalchemy import func, extract
    
    salon_ids = [salon.id for salon in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()]
    
    if not salon_ids:
        return {"data": []}
    
    if period == "week":
        
        revenue_data = db.query(
            func.date(Booking.created_at).label('date'),
            func.sum(Booking.total_amount).label('revenue')
        ).filter(
            Booking.salon_id.in_(salon_ids),
            Booking.status == BookingStatus.COMPLETED,
            Booking.created_at >= datetime.now().date() - timedelta(days=7)
        ).group_by(func.date(Booking.created_at)).all()
    elif period == "month":
        
        revenue_data = db.query(
            func.date(Booking.created_at).label('date'),
            func.sum(Booking.total_amount).label('revenue')
        ).filter(
            Booking.salon_id.in_(salon_ids),
            Booking.status == BookingStatus.COMPLETED,
            Booking.created_at >= datetime.now().date() - timedelta(days=30)
        ).group_by(func.date(Booking.created_at)).all()
    else:  
        
        revenue_data = db.query(
            extract('month', Booking.created_at).label('month'),
            func.sum(Booking.total_amount).label('revenue')
        ).filter(
            Booking.salon_id.in_(salon_ids),
            Booking.status == BookingStatus.COMPLETED,
            Booking.created_at >= datetime.now().date() - timedelta(days=365)
        ).group_by(extract('month', Booking.created_at)).all()
    
    return {
        "period": period,
        "data": [{"label": str(item[0]), "revenue": float(item[1] or 0)} for item in revenue_data]
    }


# ---------------------------------------------------------------------------
# Subscription / trial status
# ---------------------------------------------------------------------------

@router.get("/subscription/status")
def get_subscription_status(
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """
    Returns the vendor's current subscription / trial status with a live countdown.
    """
    kyc_record = db.query(VendorKYC).filter(VendorKYC.vendor_id == vendor.id).first()

    subscription = MetaMapService.get_subscription_status(vendor)
    subscription["kyc_status"] = kyc_record.status if kyc_record else "not_started"
    subscription["kyc_method"] = (
        "metamap" if (kyc_record and kyc_record.metamap_verification_id) else
        "manual" if kyc_record else None
    )
    return subscription


# ---------------------------------------------------------------------------
# Payment history
# ---------------------------------------------------------------------------

@router.get("/payments/history")
def get_payment_history(
    payment_status: Optional[str] = Query(None, alias="status"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """
    All payments received across the vendor's salons with optional filters.
    """
    from sqlalchemy import func

    salon_ids = [
        s.id for s in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()
    ]
    if not salon_ids:
        return {"total": 0, "page": page, "limit": limit, "payments": []}

    query = (
        db.query(Payment)
        .options(joinedload(Payment.booking))
        .join(Payment.booking)
        .filter(Booking.salon_id.in_(salon_ids))
    )

    if payment_status:
        query = query.filter(Payment.status == payment_status)
    if start_date:
        query = query.filter(Payment.created_at >= start_date)
    if end_date:
        query = query.filter(Payment.created_at <= end_date)

    total = query.count()
    payments = (
        query.order_by(Payment.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "payments": [
            {
                "id": p.id,
                "reference": p.reference,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status,
                "payment_method": p.payment_method,
                "booking_id": p.booking_id,
                "paid_at": p.paid_at,
                "created_at": p.created_at,
            }
            for p in payments
        ],
    }


# ---------------------------------------------------------------------------
# Customer analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/customers")
def customer_analytics(
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """
    Insights about customers who booked at the vendor's salons:
    total unique customers, returning vs new, top customers by spend.
    """
    from sqlalchemy import func, distinct

    salon_ids = [
        s.id for s in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()
    ]
    if not salon_ids:
        return {"total_customers": 0, "returning_customers": 0, "top_customers": []}

    total_unique = (
        db.query(func.count(distinct(Booking.customer_id)))
        .filter(Booking.salon_id.in_(salon_ids))
        .scalar() or 0
    )

    # Returning = placed more than one booking
    returning = (
        db.query(Booking.customer_id)
        .filter(Booking.salon_id.in_(salon_ids))
        .group_by(Booking.customer_id)
        .having(func.count(Booking.id) > 1)
        .count()
    )

    top_customers = (
        db.query(
            Booking.customer_id,
            func.count(Booking.id).label("total_bookings"),
            func.sum(Booking.total_amount).label("total_spent"),
        )
        .filter(
            Booking.salon_id.in_(salon_ids),
            Booking.status == BookingStatus.COMPLETED,
        )
        .group_by(Booking.customer_id)
        .order_by(func.sum(Booking.total_amount).desc())
        .limit(10)
        .all()
    )

    customer_ids = [r.customer_id for r in top_customers]
    customers_map = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(customer_ids)).all()
    }

    return {
        "total_customers": total_unique,
        "returning_customers": returning,
        "new_customers": total_unique - returning,
        "top_customers_by_spend": [
            {
                "customer_id": r.customer_id,
                "name": f"{customers_map[r.customer_id].first_name} {customers_map[r.customer_id].last_name}"
                if r.customer_id in customers_map else "Unknown",
                "total_bookings": r.total_bookings,
                "total_spent_ghs": float(r.total_spent or 0),
            }
            for r in top_customers
        ],
    }


# ---------------------------------------------------------------------------
# Service analytics
# ---------------------------------------------------------------------------

@router.get("/analytics/services")
def service_analytics(
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """Top services by booking count and revenue."""
    from sqlalchemy import func
    from app.models.booking import BookingItem

    salon_ids = [
        s.id for s in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()
    ]
    if not salon_ids:
        return {"top_services": []}

    top_services = (
        db.query(
            Service.name,
            func.count(BookingItem.id).label("bookings"),
            func.sum(BookingItem.price * BookingItem.quantity).label("revenue"),
        )
        .join(BookingItem, BookingItem.service_id == Service.id)
        .join(Booking, Booking.id == BookingItem.booking_id)
        .filter(Booking.salon_id.in_(salon_ids))
        .group_by(Service.id, Service.name)
        .order_by(func.count(BookingItem.id).desc())
        .limit(10)
        .all()
    )

    return {
        "top_services": [
            {
                "service": r.name,
                "total_bookings": r.bookings,
                "total_revenue_ghs": float(r.revenue or 0),
            }
            for r in top_services
        ]
    }


# ---------------------------------------------------------------------------
# Review management
# ---------------------------------------------------------------------------

@router.get("/reviews")
def get_vendor_reviews(
    salon_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """All reviews left for the vendor's salons."""
    salon_ids = [
        s.id for s in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()
    ]
    if not salon_ids:
        return {"total": 0, "reviews": []}

    query = db.query(Review).filter(Review.salon_id.in_(salon_ids))
    if salon_id:
        if salon_id not in salon_ids:
            raise HTTPException(status_code=403, detail="Not your salon")
        query = query.filter(Review.salon_id == salon_id)

    total   = query.count()
    reviews = query.order_by(Review.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    customer_ids = [r.customer_id for r in reviews]
    customers_map = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(customer_ids)).all()
    }

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "reviews": [
            {
                "id": r.id,
                "salon_id": r.salon_id,
                "rating": r.rating,
                "comment": r.comment,
                "customer_name": f"{customers_map[r.customer_id].first_name} {customers_map[r.customer_id].last_name}"
                if r.customer_id in customers_map else "Anonymous",
                "is_approved": r.is_approved,
                "created_at": r.created_at,
            }
            for r in reviews
        ],
    }


# ---------------------------------------------------------------------------
# Comprehensive vendor profile
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_vendor_profile(
    vendor: User = Depends(get_current_vendor),
    db: Session = Depends(get_db),
):
    """Full vendor profile: account details, KYC status, subscription, salon summary."""
    from sqlalchemy import func

    kyc = db.query(VendorKYC).filter(VendorKYC.vendor_id == vendor.id).first()
    salon_count = db.query(Salon).filter(Salon.owner_id == vendor.id).count()
    salon_ids = [s.id for s in db.query(Salon.id).filter(Salon.owner_id == vendor.id).all()]

    total_bookings = db.query(Booking).filter(Booking.salon_id.in_(salon_ids)).count() if salon_ids else 0
    total_revenue = (
        db.query(func.sum(Booking.total_amount))
        .filter(Booking.salon_id.in_(salon_ids), Booking.status == BookingStatus.COMPLETED)
        .scalar() or 0
    ) if salon_ids else 0

    return {
        "id": vendor.id,
        "email": vendor.email,
        "phone_number": vendor.phone_number,
        "first_name": vendor.first_name,
        "last_name": vendor.last_name,
        "is_active": vendor.is_active,
        "is_verified": vendor.is_verified,
        "kyc_verified": vendor.kyc_verified,
        "subscription": MetaMapService.get_subscription_status(vendor),
        "kyc": {
            "status": kyc.status if kyc else "not_started",
            "method": "metamap" if (kyc and kyc.metamap_verification_id) else "manual" if kyc else None,
            "rejection_reason": kyc.rejection_reason if kyc else None,
        },
        "stats": {
            "total_salons": salon_count,
            "total_bookings": total_bookings,
            "total_revenue_ghs": float(total_revenue),
        },
        "created_at": vendor.created_at,
    }
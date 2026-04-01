"""
KYC routes.

Two verification paths co-exist:
  1. Legacy path  — document upload + OCR + DeepFace (existing endpoints kept intact)
  2. MetaMap path — hosted SDK widget with Ghana card dedup + 30-day trial

All MetaMap endpoints are prefixed /metamap/.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, UploadFile, File, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.kyc import KYCAuditLog, VendorKYC
from app.models.user import User, UserRole
from app.schemas.kyc import KYCResponse, KYCVerificationRequest
from app.services.kyc_service import KYCService
from app.services.metamap_service import MetaMapService

router = APIRouter()
kyc_service = KYCService()
metamap_service = MetaMapService()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_vendor(user: User) -> None:
    if user.role != UserRole.VENDOR:
        raise HTTPException(status_code=403, detail="Only vendors can access KYC endpoints")


# ---------------------------------------------------------------------------
# Legacy portal (served as HTML)
# ---------------------------------------------------------------------------

@router.get("/portal", response_class=HTMLResponse)
async def kyc_portal(request: Request):
    """Serve the legacy KYC portal HTML page."""
    with open("app/templates/kyc_portal.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


# ---------------------------------------------------------------------------
# Current vendor KYC status
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_kyc_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the vendor's current KYC verification status together with
    subscription / trial countdown information.
    """
    _require_vendor(current_user)

    kyc_record = (
        db.query(VendorKYC).filter(VendorKYC.vendor_id == current_user.id).first()
    )

    subscription = MetaMapService.get_subscription_status(current_user)

    return {
        "kyc_submitted": kyc_record is not None,
        "kyc_status": kyc_record.status if kyc_record else "not_started",
        "kyc_method": (
            "metamap"
            if (kyc_record and kyc_record.metamap_verification_id)
            else "manual"
            if kyc_record
            else None
        ),
        "metamap_status": kyc_record.metamap_status if kyc_record else None,
        "rejection_reason": kyc_record.rejection_reason if kyc_record else None,
        "kyc_verified": current_user.kyc_verified,
        "subscription": subscription,
    }


# ---------------------------------------------------------------------------
# MetaMap — start verification
# ---------------------------------------------------------------------------

@router.post("/metamap/start")
async def start_metamap_verification(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Initiate a MetaMap identity verification session.

    Returns a `verification_url` that the frontend opens inside the MetaMap SDK
    widget, plus the `verification_id` used to track progress.

    A vendor who is already approved cannot re-verify.
    """
    _require_vendor(current_user)

    existing = (
        db.query(VendorKYC).filter(VendorKYC.vendor_id == current_user.id).first()
    )

    if existing and existing.status == "approved":
        raise HTTPException(status_code=400, detail="KYC already approved for this account")

    if existing and existing.status == "processing":
        # Allow re-initiation only if there is no active MetaMap session
        if existing.metamap_verification_id:
            raise HTTPException(
                status_code=400,
                detail="A MetaMap verification is already in progress. Please complete it.",
            )

    try:
        session = await metamap_service.create_verification_session(
            user_id=current_user.id,
            email=current_user.email,
            first_name=current_user.first_name or "",
            last_name=current_user.last_name or "",
        )
    except RuntimeError as exc:
        logger.error("MetaMap session creation failed for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=502, detail=f"MetaMap error: {exc}")

    # Create or update the KYC record
    if not existing:
        existing = VendorKYC(vendor_id=current_user.id)
        db.add(existing)

    existing.metamap_verification_id = session["verification_id"]
    existing.metamap_identity_id = session["identity_id"]
    existing.metamap_flow_id = settings.METAMAP_FLOW_ID
    existing.status = "processing"
    existing.updated_at = datetime.utcnow()

    audit = KYCAuditLog(
        kyc_id=existing.id if existing.id else None,
        action="metamap_session_started",
        performed_by=current_user.id,
        details={"verification_id": session["verification_id"]},
    )

    db.commit()
    db.refresh(existing)

    # Now we can set the audit kyc_id
    audit.kyc_id = existing.id
    db.add(audit)
    db.commit()

    return {
        "verification_id": session["verification_id"],
        "verification_url": session["verification_url"],
        "message": "Open the verification_url in the MetaMap widget to proceed",
    }


# ---------------------------------------------------------------------------
# MetaMap — webhook receiver
# ---------------------------------------------------------------------------

@router.post("/metamap/webhook")
async def metamap_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Receives MetaMap webhook events.

    MetaMap signs the body with HMAC-SHA256 and sets the header:
        x-signature: sha256=<hex>

    After signature verification the payload is processed asynchronously.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-signature", "")

    if not metamap_service.verify_webhook_signature(raw_body, signature):
        logger.warning("MetaMap webhook: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.info(
        "MetaMap webhook received: event=%s", payload.get("eventName", "unknown")
    )

    # Process in background so we return 200 quickly to MetaMap
    background_tasks.add_task(_process_metamap_event, db, payload)

    return {"received": True}


async def _process_metamap_event(db: Session, payload: dict) -> None:
    """Background task: delegate to MetaMapService."""
    try:
        result = await metamap_service.process_webhook(db, payload)
        logger.info("MetaMap event processed: %s", result)
    except Exception as exc:
        logger.exception("MetaMap event processing failed: %s", exc)


# ---------------------------------------------------------------------------
# Legacy — document upload (S3 path)
# ---------------------------------------------------------------------------

@router.post("/upload-document")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = "front",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a KYC document image to S3 (legacy path)."""
    _require_vendor(current_user)

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        file_url = await kyc_service.upload_document_to_s3(file.file, current_user.id, doc_type)

        extracted_data = {}
        if doc_type == "front":
            extracted_data = await kyc_service.extract_document_data(file_url)

        kyc_record = (
            db.query(VendorKYC).filter(VendorKYC.vendor_id == current_user.id).first()
        )
        if not kyc_record:
            kyc_record = VendorKYC(vendor_id=current_user.id)
            db.add(kyc_record)

        if doc_type == "front":
            kyc_record.id_front_url = file_url
        elif doc_type == "back":
            kyc_record.id_back_url = file_url
        elif doc_type == "selfie":
            kyc_record.selfie_url = file_url

        if extracted_data:
            kyc_record.ocr_extracted_data = extracted_data

        db.commit()
        db.refresh(kyc_record)

        audit = KYCAuditLog(
            kyc_id=kyc_record.id,
            action="document_upload",
            performed_by=current_user.id,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent"),
            details={"doc_type": doc_type},
        )
        db.add(audit)
        db.commit()

        return {
            "message": "Document uploaded successfully",
            "url": file_url,
            "extracted_data": extracted_data,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Document upload failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


# ---------------------------------------------------------------------------
# Legacy — submit KYC (OCR + DeepFace path)
# ---------------------------------------------------------------------------

@router.post("/submit", response_model=KYCResponse)
async def submit_kyc(
    request: Request,
    verification_request: KYCVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit the KYC form for analysis using the legacy OCR + face-matching pipeline.
    For new vendors we recommend using the MetaMap path instead.
    """
    _require_vendor(current_user)

    existing = (
        db.query(VendorKYC)
        .filter(
            VendorKYC.vendor_id == current_user.id,
            VendorKYC.status.in_(["processing", "approved"]),
        )
        .first()
    )

    if existing:
        if existing.status == "approved":
            raise HTTPException(status_code=400, detail="KYC already approved")
        raise HTTPException(status_code=400, detail="KYC is already being processed")

    kyc_record = (
        db.query(VendorKYC).filter(VendorKYC.vendor_id == current_user.id).first()
    )
    if not kyc_record:
        kyc_record = VendorKYC(vendor_id=current_user.id)
        db.add(kyc_record)

    kyc_record.id_type = verification_request.id_type
    kyc_record.id_number = verification_request.id_number
    kyc_record.full_name = verification_request.full_name
    kyc_record.date_of_birth = datetime.strptime(verification_request.date_of_birth, "%Y-%m-%d")
    kyc_record.id_front_url = verification_request.id_front_url
    kyc_record.id_back_url = verification_request.id_back_url
    kyc_record.selfie_url = verification_request.selfie_url
    kyc_record.status = "processing"

    analysis = await kyc_service.perform_full_kyc_analysis(
        {
            "id_front_url": verification_request.id_front_url,
            "id_back_url": verification_request.id_back_url,
            "selfie_url": verification_request.selfie_url,
        }
    )

    kyc_record.face_match_score = analysis.get("face_comparison", {}).get("score")
    kyc_record.face_match_status = (
        "verified" if analysis.get("face_comparison", {}).get("is_match") else "failed"
    )
    kyc_record.document_verification_status = (
        "verified" if analysis.get("document_verification", {}).get("is_valid") else "failed"
    )
    kyc_record.is_document_valid = analysis.get("document_verification", {}).get("is_valid")
    kyc_record.is_live_selfie = analysis.get("liveness_check", {}).get("is_live")
    kyc_record.risk_score = analysis.get("risk_score", 1.0)
    kyc_record.ai_analysis = analysis

    if analysis.get("is_approved"):
        # Ghana card dedup check on the submitted id_number
        if verification_request.id_type == "ghana_card" and verification_request.id_number:
            card_hash = MetaMapService.hash_card_number(verification_request.id_number)
            if MetaMapService.is_card_already_registered(db, card_hash, current_user.id):
                kyc_record.status = "rejected"
                kyc_record.rejection_reason = (
                    "This Ghana card is already registered with another account."
                )
                db.commit()
                db.refresh(kyc_record)
                return kyc_record
            kyc_record.ghana_card_hash = card_hash
            current_user.ghana_card_hash = card_hash

        now = datetime.utcnow()
        kyc_record.status = "approved"
        kyc_record.trial_activated_at = now
        current_user.kyc_verified = True
        current_user.subscription_plan = "premium_trial"
        current_user.trial_start_date = now
        current_user.subscription_expires_at = now + timedelta(days=settings.TRIAL_DAYS)

        try:
            from app.services.email import EmailService
            EmailService.send_trial_started_email(
                email=current_user.email,
                first_name=current_user.first_name,
                expiry_date=current_user.subscription_expires_at,
            )
        except Exception as exc:
            logger.error("Failed to send trial email: %s", exc)
    else:
        kyc_record.status = "rejected"
        kyc_record.rejection_reason = analysis.get(
            "recommendations", "KYC verification failed"
        )

    db.commit()
    db.refresh(kyc_record)

    audit = KYCAuditLog(
        kyc_id=kyc_record.id,
        action="kyc_submitted",
        performed_by=current_user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
        details={"status": kyc_record.status, "risk_score": kyc_record.risk_score},
    )
    db.add(audit)
    db.commit()

    return kyc_record

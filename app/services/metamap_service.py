"""
MetaMap (Mati) KYC service.

Flow:
  1. Vendor hits POST /api/kyc/metamap/start  -> we call MetaMap to create a verification
     session and return the verification URL + verificationId to the frontend.
  2. Frontend opens the MetaMap SDK widget with that URL.
  3. MetaMap calls POST /api/kyc/metamap/webhook with the result.
  4. We extract the Ghana card number, hash it, check for duplicates, and if clean we
     activate the vendor's 30-day free trial.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.kyc import VendorKYC, KYCAuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

METAMAP_AUTH_URL = "https://api.metamap.com/oauth"
METAMAP_API_BASE = "https://api.metamap.com"


class MetaMapService:
    """Handles all MetaMap API interactions and post-verification business logic."""

    # ------------------------------------------------------------------
    # Authentication helpers
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> str:
        """Exchange client credentials for a Bearer token."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{METAMAP_AUTH_URL}/token",
                data={"grant_type": "client_credentials"},
                auth=(settings.METAMAP_CLIENT_ID, settings.METAMAP_CLIENT_SECRET),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code != 200:
            logger.error("MetaMap token error: %s", response.text)
            raise RuntimeError("Failed to obtain MetaMap access token")
        return response.json()["access_token"]

    # ------------------------------------------------------------------
    # Create a verification session
    # ------------------------------------------------------------------

    async def create_verification_session(
        self, user_id: int, email: str, first_name: str, last_name: str
    ) -> dict:
        """
        Ask MetaMap to create a verification session for a vendor.

        Returns:
            {
                "verification_id": "...",
                "verification_url": "https://...",
                "identity_id": "..."
            }
        """
        token = await self._get_access_token()

        payload = {
            "flowId": settings.METAMAP_FLOW_ID,
            "merchantId": settings.METAMAP_MERCHANT_ID,
            "metadata": {
                "userId": str(user_id),
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{METAMAP_API_BASE}/v2/identities",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

        if response.status_code not in (200, 201):
            logger.error("MetaMap create identity error: %s", response.text)
            raise RuntimeError(f"MetaMap error: {response.text}")

        data = response.json()
        identity_id = data.get("_id") or data.get("id", "")

        # Build the hosted verification URL the frontend SDK uses
        verification_url = (
            f"https://signup.getmati.com/?merchantToken={settings.METAMAP_MERCHANT_ID}"
            f"&flowId={settings.METAMAP_FLOW_ID}"
            f"&identityId={identity_id}"
        )

        return {
            "verification_id": identity_id,
            "verification_url": verification_url,
            "identity_id": identity_id,
        }

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """
        MetaMap signs the webhook payload with HMAC-SHA256 using your webhook secret.
        The header is typically: x-signature: sha256=<hex_digest>
        """
        if not settings.METAMAP_WEBHOOK_SECRET:
            logger.warning("METAMAP_WEBHOOK_SECRET not configured — skipping signature check")
            return True

        secret = settings.METAMAP_WEBHOOK_SECRET.encode()
        expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()

        provided = signature_header.replace("sha256=", "").strip()
        return hmac.compare_digest(expected, provided)

    # ------------------------------------------------------------------
    # Ghana card extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ghana_card_number(metamap_payload: dict) -> Optional[str]:
        """
        Walk the MetaMap identity resource and pull out the Ghana card number.

        MetaMap returns structured fields inside steps[].data[].fields[].
        We look for documentNumber / nationalId fields on Ghana Card documents.
        """
        # Try top-level fields first
        for key in ("documentNumber", "nationalId", "idNumber"):
            if metamap_payload.get(key):
                return metamap_payload[key].strip().upper()

        # Walk steps array
        steps = metamap_payload.get("steps") or []
        for step in steps:
            data_list = step.get("data") if isinstance(step, dict) else []
            if not isinstance(data_list, list):
                data_list = [data_list] if data_list else []
            for data_item in data_list:
                if not isinstance(data_item, dict):
                    continue
                for field in data_item.get("fields", []):
                    if not isinstance(field, dict):
                        continue
                    field_id = (field.get("fieldType") or "").lower()
                    if field_id in ("documentnumber", "nationalid", "idnumber", "cardnumber"):
                        value = field.get("value") or ""
                        if value:
                            return value.strip().upper()

        return None

    @staticmethod
    def hash_card_number(card_number: str) -> str:
        """Return a SHA-256 hex digest of the normalised Ghana card number."""
        normalised = card_number.strip().upper().replace(" ", "")
        return hashlib.sha256(normalised.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Duplicate-card guard
    # ------------------------------------------------------------------

    @staticmethod
    def is_card_already_registered(db: Session, card_hash: str, exclude_user_id: int) -> bool:
        """
        Return True if another vendor has already used a card with this hash.
        We check both the User table (permanent dedup store) and VendorKYC (in case
        a previous KYC attempt stored it before the user record was updated).
        """
        existing_user = (
            db.query(User)
            .filter(User.ghana_card_hash == card_hash, User.id != exclude_user_id)
            .first()
        )
        if existing_user:
            return True

        existing_kyc = (
            db.query(VendorKYC)
            .filter(
                VendorKYC.ghana_card_hash == card_hash,
                VendorKYC.vendor_id != exclude_user_id,
                VendorKYC.status == "approved",
            )
            .first()
        )
        return existing_kyc is not None

    # ------------------------------------------------------------------
    # Main webhook processor
    # ------------------------------------------------------------------

    async def process_webhook(self, db: Session, payload: dict) -> dict:
        """
        Handle an inbound MetaMap webhook.

        Expected top-level keys (from MetaMap docs):
          eventName: "verification_completed" | "verification_failed" | ...
          resource: the full identity/verification resource URL or object
          status:   "verified" | "reviewNeeded" | "rejected"

        Returns a summary dict for logging/response.
        """
        event_name = payload.get("eventName", "")
        resource = payload.get("resource", {})
        if isinstance(resource, str):
            # Some versions send a URL — we already have the payload in the outer object
            resource = payload

        identity_id = (
            resource.get("_id")
            or resource.get("id")
            or payload.get("identity", {}).get("_id", "")
        )
        metamap_status = payload.get("status") or resource.get("status", "")

        # Find the KYC record by metamap_verification_id
        kyc_record = (
            db.query(VendorKYC)
            .filter(VendorKYC.metamap_verification_id == identity_id)
            .first()
        )
        if not kyc_record:
            logger.warning("MetaMap webhook: no KYC record for identity_id=%s", identity_id)
            return {"handled": False, "reason": "unknown_identity"}

        vendor: User = kyc_record.vendor
        kyc_record.metamap_status = metamap_status
        kyc_record.metamap_metadata = payload
        kyc_record.updated_at = datetime.utcnow()

        if metamap_status in ("verified",):
            await self._handle_verified(db, kyc_record, vendor, payload)
        elif metamap_status in ("reviewNeeded",):
            kyc_record.status = "processing"
            self._log_audit(db, kyc_record, "metamap_review_needed", vendor.id, payload)
        else:
            # rejected / failed
            kyc_record.status = "rejected"
            kyc_record.rejection_reason = (
                payload.get("rejectionLabels")
                or payload.get("reason")
                or "MetaMap verification rejected"
            )
            self._log_audit(db, kyc_record, "metamap_rejected", vendor.id, payload)

        db.commit()
        db.refresh(kyc_record)
        return {"handled": True, "status": metamap_status, "vendor_id": vendor.id}

    # ------------------------------------------------------------------
    # Internal: handle a successful verification
    # ------------------------------------------------------------------

    async def _handle_verified(
        self, db: Session, kyc_record: VendorKYC, vendor: User, payload: dict
    ) -> None:
        """
        Called when MetaMap marks the identity as 'verified'.
        Extracts the Ghana card number, enforces uniqueness, then activates trial.
        """
        card_number = self._extract_ghana_card_number(payload)

        if card_number:
            card_hash = self.hash_card_number(card_number)

            # Duplicate check
            if self.is_card_already_registered(db, card_hash, vendor.id):
                kyc_record.status = "rejected"
                kyc_record.rejection_reason = (
                    "This Ghana card has already been used to register on Salon Connect. "
                    "Each vendor must use a unique Ghana card."
                )
                self._log_audit(
                    db, kyc_record, "duplicate_ghana_card", vendor.id,
                    {"card_hash": card_hash}
                )
                return

            # Store hash in both records
            kyc_record.ghana_card_hash = card_hash
            vendor.ghana_card_hash = card_hash

            # Store the raw id_number (so admin can see it, but we never expose to clients)
            kyc_record.id_number = card_number
            kyc_record.id_type = "ghana_card"
        else:
            logger.warning(
                "MetaMap verified vendor %s but Ghana card number not found in payload",
                vendor.id,
            )
            # Still approve — admin can review metamap_metadata if needed
            card_hash = None

        # Approve KYC
        now = datetime.utcnow()
        kyc_record.status = "approved"
        kyc_record.metamap_verified_at = now
        kyc_record.trial_activated_at = now
        kyc_record.document_verification_status = "verified"

        # Grant 30-day free trial
        vendor.kyc_verified = True
        vendor.subscription_plan = "premium_trial"
        vendor.trial_start_date = now
        vendor.subscription_expires_at = now + timedelta(days=settings.TRIAL_DAYS)

        self._log_audit(db, kyc_record, "approved_via_metamap", vendor.id, {
            "trial_expires": vendor.subscription_expires_at.isoformat(),
        })

        # Send trial-started email in background (fire-and-forget at call-site)
        try:
            from app.services.email import EmailService
            EmailService.send_trial_started_email(
                email=vendor.email,
                first_name=vendor.first_name,
                expiry_date=vendor.subscription_expires_at,
            )
        except Exception as exc:
            logger.error("Failed to send trial email to %s: %s", vendor.email, exc)

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    @staticmethod
    def _log_audit(
        db: Session,
        kyc_record: VendorKYC,
        action: str,
        user_id: int,
        details: dict,
    ) -> None:
        audit = KYCAuditLog(
            kyc_id=kyc_record.id,
            action=action,
            performed_by=user_id,
            details=details,
        )
        db.add(audit)

    # ------------------------------------------------------------------
    # Subscription status helper
    # ------------------------------------------------------------------

    @staticmethod
    def get_subscription_status(vendor: User) -> dict:
        """
        Return a structured subscription/trial status payload for the vendor.
        """
        now = datetime.utcnow()
        plan = vendor.subscription_plan or "free"
        expires_at = vendor.subscription_expires_at

        if plan == "premium_trial":
            if expires_at and now < expires_at:
                delta = expires_at - now
                return {
                    "plan": "premium_trial",
                    "is_active": True,
                    "trial_active": True,
                    "days_remaining": delta.days,
                    "hours_remaining": delta.seconds // 3600,
                    "expires_at": expires_at.isoformat(),
                    "trial_started_at": (
                        vendor.trial_start_date.isoformat()
                        if vendor.trial_start_date
                        else None
                    ),
                    "message": f"Free trial — {delta.days} day(s) remaining",
                }
            else:
                return {
                    "plan": "premium_trial",
                    "is_active": False,
                    "trial_active": False,
                    "days_remaining": 0,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "message": "Free trial expired. Please subscribe to continue.",
                    "renewal_amount_ghs": settings.SUBSCRIPTION_MONTHLY_AMOUNT_GHS,
                }
        elif plan == "premium":
            if expires_at and now < expires_at:
                delta = expires_at - now
                return {
                    "plan": "premium",
                    "is_active": True,
                    "trial_active": False,
                    "days_remaining": delta.days,
                    "expires_at": expires_at.isoformat(),
                    "message": f"Premium subscription — {delta.days} day(s) remaining",
                }
            else:
                return {
                    "plan": "premium",
                    "is_active": False,
                    "trial_active": False,
                    "days_remaining": 0,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "message": "Premium subscription expired.",
                    "renewal_amount_ghs": settings.SUBSCRIPTION_MONTHLY_AMOUNT_GHS,
                }
        else:
            return {
                "plan": "free",
                "is_active": True,
                "trial_active": False,
                "days_remaining": None,
                "expires_at": None,
                "message": "Free plan — complete KYC to start your 30-day premium trial",
                "kyc_required": True,
            }

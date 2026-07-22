from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Float, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class VendorKYC(Base):
    """KYC verification for vendors"""
    __tablename__ = "vendor_kyc"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)

    # Document Information
    id_type = Column(String(50))  # ghana_card, passport, drivers_license
    id_number = Column(String(100))
    full_name = Column(String(200))
    date_of_birth = Column(DateTime)

    # Document URLs (S3 / Cloudinary)
    id_front_url = Column(String(500))
    id_back_url = Column(String(500))
    selfie_url = Column(String(500))

    # Legacy verification results (OCR / DeepFace path)
    face_match_score = Column(Float)
    face_match_status = Column(String(20))
    document_verification_status = Column(String(20))
    ocr_extracted_data = Column(JSON)
    is_document_valid = Column(Boolean, default=False)
    is_live_selfie = Column(Boolean, default=False)
    risk_score = Column(Float, default=0.0)
    ai_analysis = Column(JSON)

    # MetaMap integration fields
    metamap_verification_id = Column(String(200), nullable=True, index=True)
    metamap_identity_id = Column(String(200), nullable=True)
    metamap_flow_id = Column(String(200), nullable=True)
    metamap_status = Column(String(50), nullable=True)       # verified, reviewNeeded, rejected
    metamap_metadata = Column(JSON, nullable=True)           # full payload from MetaMap webhook
    metamap_verified_at = Column(DateTime, nullable=True)

    # Ghana card anti-duplication (SHA-256 hash of the card number)
    ghana_card_hash = Column(String(64), nullable=True, index=True)

    # Trial
    trial_activated_at = Column(DateTime, nullable=True)

    # Status & Timestamps
    status = Column(String(20), default="pending")  # pending, processing, approved, rejected
    rejection_reason = Column(Text)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    vendor = relationship("User", foreign_keys=[vendor_id], back_populates="kyc_data")
    reviewer = relationship("User", foreign_keys=[reviewed_by])

class KYCAuditLog(Base):
    """Audit log for KYC actions"""
    __tablename__ = "kyc_audit_logs"
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True, index=True)
    kyc_id = Column(Integer, ForeignKey("vendor_kyc.id"))
    action = Column(String(50))  # submitted, verified, rejected, etc.
    performed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    performed_at = Column(DateTime(timezone=True), server_default=func.now())
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    details = Column(JSON)
    
    # Relationships
    kyc = relationship("VendorKYC")
    user = relationship("User", foreign_keys=[performed_by])
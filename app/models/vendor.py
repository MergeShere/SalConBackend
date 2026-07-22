from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base

class IDType(str, enum.Enum):
    GHANA_CARD = "ghana_card"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"

class KYCStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class VendorBusinessInfo(Base):
    """Store vendor business information"""
    __tablename__ = "vendor_business_info"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    business_name = Column(String(255), nullable=False)
    business_phone = Column(String(20), nullable=False)
    business_address = Column(Text, nullable=False)
    business_city = Column(String(100), nullable=False)
    business_state = Column(String(100), nullable=False)
    business_country = Column(String(100), nullable=False)
    business_description = Column(Text)
    business_website = Column(String(500))
    tax_id = Column(String(100))
    business_registration_number = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# NOTE: VendorKYC is defined in app.models.kyc and exported via models.__init__
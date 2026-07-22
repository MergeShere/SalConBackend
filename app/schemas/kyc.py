from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

class IDType(str, Enum):
    GHANA_CARD = "ghana_card"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    VOTERS_ID = "voters_id"

class KYCStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"

class KYCDocumentUpload(BaseModel):
    doc_type: str = Field(..., description="Type of document: front, back, selfie")
    
class KYCSelfieUpload(BaseModel):
    doc_type: str = Field("selfie", description="Type of document")
    
class KYCVerificationRequest(BaseModel):
    id_type: IDType
    id_number: str
    full_name: str
    date_of_birth: str
    id_front_url: str
    id_back_url: Optional[str] = None
    selfie_url: str
    
    @validator('date_of_birth')
    def validate_dob(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('Date of birth must be in YYYY-MM-DD format')

class KYCResponse(BaseModel):
    id: int
    vendor_id: int
    id_type: Optional[str]
    id_number: Optional[str]
    full_name: Optional[str]
    status: str
    face_match_score: Optional[float]
    face_match_status: Optional[str]
    document_verification_status: Optional[str]
    is_document_valid: Optional[bool]
    is_live_selfie: Optional[bool]
    risk_score: Optional[float]
    rejection_reason: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class KYCExtractedData(BaseModel):
    id_number: Optional[str]
    full_name: Optional[str]
    date_of_birth: Optional[str]
    issue_date: Optional[str]
    expiry_date: Optional[str]
    raw_text: Optional[str]
    confidence: Optional[float]

class FaceMatchResult(BaseModel):
    score: float
    is_match: bool
    threshold: float = 0.75
    details: Dict[str, Any]

class KYCAnalysis(BaseModel):
    document_validity: bool
    face_match_result: FaceMatchResult
    liveness_check: bool
    risk_assessment: Dict[str, Any]
    recommendations: Optional[str]
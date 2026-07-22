from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from enum import Enum
from datetime import datetime

class UserRole(str, Enum):
    CUSTOMER = "customer"
    VENDOR = "vendor"
    ADMIN = "admin"

class UserBase(BaseModel):
    email: EmailStr
    phone_number: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: UserRole = UserRole.CUSTOMER

class UserCreate(UserBase):
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if v and not v.startswith('+'):
            raise ValueError('Phone number must start with country code (e.g., +1234567890)')
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class OTPLoginRequest(BaseModel):
    email: EmailStr

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v
# Add these to your existing schemas in schemas/user.py

class CustomerRegister(BaseModel):
    """Schema for customer registration"""
    email: EmailStr
    password: str
    phone_number: Optional[str] = None
    first_name: str
    last_name: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if v and not v.startswith('+'):
            raise ValueError('Phone number must start with country code (e.g., +1234567890)')
        return v

class VendorRegister(BaseModel):
    """Schema for vendor registration with business info"""
    email: EmailStr
    password: str
    phone_number: str  # Required for vendors
    first_name: str
    last_name: str
    business_name: str
    business_phone: str
    business_address: str
    business_city: str
    business_state: str
    business_country: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if not v.startswith('+'):
            raise ValueError('Phone number must start with country code (e.g., +1234567890)')
        return v
    
    @validator('business_phone')
    def validate_business_phone(cls, v):
        if not v.startswith('+'):
            raise ValueError('Business phone must start with country code (e.g., +1234567890)')
        return v


class CustomerRegister(BaseModel):
    """Schema for customer registration"""
    email: EmailStr
    password: str
    phone_number: Optional[str] = None
    first_name: str
    last_name: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if v and not v.startswith('+'):
            raise ValueError('Phone number must start with country code (e.g., +1234567890)')
        return v

class VendorRegister(BaseModel):
    """Schema for vendor registration with business info"""
    email: EmailStr
    password: str
    phone_number: str  # Required for vendors
    first_name: str
    last_name: str
    business_name: str
    business_phone: str
    business_address: str
    business_city: str
    business_state: str
    business_country: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters long')
        return v
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if not v.startswith('+'):
            raise ValueError('Phone number must start with country code (e.g., +1234567890)')
        return v
    
    @validator('business_phone')
    def validate_business_phone(cls, v):
        if not v.startswith('+'):
            raise ValueError('Business phone must start with country code (e.g., +1234567890)')
        return v
class UserResponse(UserBase):
    id: int
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class UserProfileBase(BaseModel):
    profile_picture: Optional[str] = None
    cover_photo: Optional[str] = None
    bio: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None

class UserProfileCreate(UserProfileBase):
    pass

class UserProfileUpdate(UserProfileBase):
    pass


# Add these schemas to your existing schemas

class GoogleOAuthRegister(BaseModel):
    role: UserRole
    phone_number: Optional[str] = None
    
    @validator('phone_number')
    def validate_phone_number(cls, v):
        if v and not v.startswith('+'):
            raise ValueError('Phone number must start with country code (e.g., +1234567890)')
        return v

class GoogleUserInfo(BaseModel):
    email: str
    first_name: str
    last_name: str
    picture: Optional[str] = None
    google_id: str
    email_verified: bool

class OAuthSessionData(BaseModel):
    google_user: GoogleUserInfo
    temp_session_id: str
    
class UserProfileResponse(BaseModel):
    id: int
    user_id: int
    bio: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    profile_picture: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[int] = None
    email: Optional[str] = None


# Add this to your existing schemas in schemas/user.py

class UserProfileResponse(UserProfileBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
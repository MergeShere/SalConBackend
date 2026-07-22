from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum, ForeignKey, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base

class UserRole(str, enum.Enum):
    CUSTOMER = "customer"
    VENDOR = "vendor"
    ADMIN = "admin"

user_favorites = Table(
    'user_favorites',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('salon_id', Integer, ForeignKey('salons.id'), primary_key=True),
    Column('created_at', DateTime(timezone=True), server_default=func.now())
)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone_number = Column(String(20), unique=True, index=True)
    password = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    role = Column(Enum(UserRole), default=UserRole.CUSTOMER)
    
    # Status flags
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False) # Email verification
    
    # KYC & Subscription
    kyc_verified = Column(Boolean, default=False)
    subscription_plan = Column(String(50), default="free")   # free, premium_trial, premium
    subscription_expires_at = Column(DateTime, nullable=True)
    trial_start_date = Column(DateTime, nullable=True)
    # SHA-256 hash of Ghana card number — enforces one card per account across the platform
    ghana_card_hash = Column(String(64), unique=True, index=True, nullable=True)
    
    # OAuth fields
    google_id = Column(String(255), unique=True, index=True)
    is_oauth_user = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    profile = relationship("UserProfile", back_populates="user", uselist=False)
    salons = relationship("Salon", back_populates="owner")
    bookings = relationship("Booking", back_populates="customer")
    favorite_salons = relationship("Salon", secondary=user_favorites, backref="favorited_by_users")
    otps = relationship("UserOTP", back_populates="user")
    password_resets = relationship("PasswordReset", back_populates="user")
    
    # Add relationship to KYC data (disambiguate FK vs reviewer FK)
    kyc_data = relationship(
        "VendorKYC",
        back_populates="vendor",
        uselist=False,
        foreign_keys="VendorKYC.vendor_id",
        primaryjoin="User.id==VendorKYC.vendor_id",
    )

class UserProfile(Base):
    __tablename__ = "user_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    profile_picture = Column(String(500))
    cover_photo = Column(String(500))
    bio = Column(Text)
    date_of_birth = Column(DateTime)
    gender = Column(String(20))
    address = Column(Text)
    city = Column(String(100))
    state = Column(String(100))
    country = Column(String(100))
    postal_code = Column(String(20))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    user = relationship("User", back_populates="profile")

class PasswordReset(Base):
    __tablename__ = "password_resets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(Text, nullable=False)  
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="password_resets")

class PendingUser(Base):
    """Store user data before email verification"""
    __tablename__ = "pending_users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone_number = Column(String(20), unique=True, index=True)
    password = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    role = Column(Enum(UserRole), default=UserRole.CUSTOMER)
    verification_token = Column(Text, nullable=False)  
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class UserOTP(Base):
    """Store OTP for login"""
    __tablename__ = "user_otps"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    otp = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="otps")
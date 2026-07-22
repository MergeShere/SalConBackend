import os
import sys

# Add the current directory to sys.path so we can import from app
sys.path.append(os.getcwd())

from app.database import engine, Base
# Import all models to ensure they are registered with Base.metadata
from app.models import (
    User, UserProfile, PasswordReset, UserRole, user_favorites, PendingUser, UserOTP,
    Salon, Service, SalonImage, Review,
    Booking, BookingItem, BookingStatus,
    Payment, PaymentStatus, PaymentMethod,
    VendorBusinessInfo, VendorKYC, IDType, KYCStatus
)

def create_tables():
    print("Creating tables in database...")
    try:
        # This checks the DB and creates any missing tables defined in your models
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created successfully!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")

if __name__ == "__main__":
    create_tables()
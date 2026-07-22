from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from datetime import datetime, timedelta
import jwt  
from app.core.config import settings  
import secrets
from app.schemas.user import CustomerRegister, VendorRegister

import os
from app.models.user import User, UserProfile, UserRole, PendingUser, UserOTP
from app.schemas.user import UserCreate, UserResponse, UserLogin, Token, UserProfileUpdate, OTPLoginRequest, OTPVerifyRequest, GoogleOAuthRegister
from app.core.security import get_password_hash, verify_password, create_access_token, verify_token
from app.services.email import EmailService

class AuthService:
    @staticmethod
    def register_user(db: Session, user_data: UserCreate):
        # Check if email already exists in users or pending users
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        existing_pending = db.query(PendingUser).filter(PendingUser.email == user_data.email).first()
        if existing_pending:
            # Resend verification email - USING NEW SIGNATURE
            verification_url = f"https://salonconnect-qzne.onrender.com/api/users/verify-email?token={existing_pending.verification_token}"
            email_sent = EmailService.send_verification_email(
                email=existing_pending.email,
                first_name=existing_pending.first_name,
                verification_url=verification_url
            )
            raise HTTPException(status_code=400, detail="Verification email already sent. Please check your email.")
        
        # Check phone number only if provided
        if user_data.phone_number:
            existing_phone = db.query(User).filter(User.phone_number == user_data.phone_number).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Phone number already registered")

        hashed_password = get_password_hash(user_data.password)
        
        # Create pending user (not saved to users table yet)
        verification_token = EmailService.generate_verification_token(user_data.email)
        pending_user = PendingUser(
            email=user_data.email,
            phone_number=user_data.phone_number,
            password=hashed_password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            role=user_data.role,
            verification_token=verification_token,
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        
        db.add(pending_user)
        db.commit()
        db.refresh(pending_user)
        
        # Send verification email - USING NEW SIGNATURE
        verification_url = f"https://salonconnect-qzne.onrender.com/api/users/verify-email?token={verification_token}"
        email_sent = EmailService.send_verification_email(
            email=user_data.email,
            first_name=user_data.first_name,
            verification_url=verification_url
        )
        
        return {"message": "Registration successful! Please check your email for verification link."}

    @staticmethod
    def verify_email(db: Session, token: str):
        """Verify user email and create actual user"""
        payload = EmailService.verify_token(token, 'email_verification')
        if not payload:
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")
        
        # Find pending user by email (not by token since token is regenerated each time)
        pending_user = db.query(PendingUser).filter(
            PendingUser.email == payload['email'],
            PendingUser.expires_at > datetime.utcnow()
        ).first()
        
        if not pending_user:
            raise HTTPException(status_code=404, detail="Verification token not found or expired")
        
        # Verify the token matches
        try:
            # Decode the token from pending user to verify it matches
            pending_payload = jwt.decode(pending_user.verification_token, settings.SECRET_KEY, algorithms=['HS256'])
            if pending_payload.get('email') != payload['email']:
                raise HTTPException(status_code=400, detail="Token mismatch")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=400, detail="Invalid token")
        
        # Create actual user
        user = User(
            email=pending_user.email,
            phone_number=pending_user.phone_number,
            password=pending_user.password,
            first_name=pending_user.first_name,
            last_name=pending_user.last_name,
            role=pending_user.role,
            is_verified=True
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create user profile
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        
        # Delete pending user
        db.delete(pending_user)
        db.commit()
        
        return user 
    
    @staticmethod
    def request_otp_login(db: Session, email: str):
        """Request OTP for login"""
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Don't reveal if user exists
            return {"message": "If the email exists, an OTP has been sent"}
        
        if not user.is_verified:
            raise HTTPException(status_code=400, detail="Please verify your email first")
        
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Account is deactivated")
        
        # Generate OTP
        otp = EmailService.generate_otp()
        
        # Save OTP to database
        user_otp = UserOTP(
            user_id=user.id,
            otp=otp,
            expires_at=datetime.utcnow() + timedelta(minutes=10)
        )
        
        # Deactivate previous OTPs
        db.query(UserOTP).filter(
            UserOTP.user_id == user.id,
            UserOTP.used == False
        ).update({"used": True})
        
        db.add(user_otp)
        db.commit()
        
        # Send OTP email - USING NEW SIGNATURE
        email_sent = EmailService.send_otp_email(
            email=user.email,
            first_name=user.first_name,
            otp=otp
        )
        
        return {"message": "OTP sent to your email"}

    @staticmethod
    def verify_otp_login(db: Session, otp_data: OTPVerifyRequest):
        """Verify OTP and login user"""
        user = db.query(User).filter(User.email == otp_data.email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Find valid OTP
        user_otp = db.query(UserOTP).filter(
            UserOTP.user_id == user.id,
            UserOTP.otp == otp_data.otp,
            UserOTP.expires_at > datetime.utcnow(),
            UserOTP.used == False
        ).first()
        
        if not user_otp:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
        
        # Mark OTP as used
        user_otp.used = True
        db.commit()
        
        # Generate tokens
        access_token = create_access_token(data={"user_id": user.id, "email": user.email})
        refresh_token = create_access_token(data={"user_id": user.id}, expires_delta=timedelta(days=7))
        
        return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

    @staticmethod
    def password_login(db: Session, user_data: UserLogin):
        """Traditional password login (for admin/vendors)"""
        user = db.query(User).filter(User.email == user_data.email).first()
        if not user or not verify_password(user_data.password, user.password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        if not user.is_active:
            raise HTTPException(status_code=401, detail="Account is deactivated")
        
        if not user.is_verified:
            raise HTTPException(
                status_code=401, 
                detail="Please verify your email before logging in. Check your inbox for verification link."
            )
        
        access_token = create_access_token(data={"user_id": user.id, "email": user.email})
        refresh_token = create_access_token(data={"user_id": user.id}, expires_delta=timedelta(days=7))
        
        return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")

    @staticmethod
    def get_user_by_id(db: Session, user_id: int):
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def refresh_token(db: Session, refresh_token: str):
        payload = verify_token(refresh_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        user_id = payload.get("user_id")
        user = AuthService.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        new_access_token = create_access_token(data={"user_id": user.id, "email": user.email})
        return Token(access_token=new_access_token, refresh_token=refresh_token, token_type="bearer")

    @staticmethod
    def update_user_profile(db: Session, user_id: int, profile_data: UserProfileUpdate):
        """Update user profile - returns UserProfile object"""
        # Get or create user profile
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        
        if not profile:
            # Create profile if it doesn't exist
            profile = UserProfile(user_id=user_id)
            db.add(profile)
        
        # Update profile fields
        update_data = profile_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(profile, field, value)
        
        profile.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(profile)
        
        return profile  # Return UserProfile object, not User object

    @staticmethod
    def get_user_profile(db: Session, user_id: int):
        """Get user profile - returns UserProfile object"""
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        
        if not profile:
            # Create default profile if it doesn't exist
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            db.commit()
            db.refresh(profile)
        
        return profile  # Return UserProfile object

    @staticmethod
    def get_customer_dashboard(db: Session, user_id: int):
        """Get customer dashboard data"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get recent bookings count
        from app.models.booking import Booking
        recent_bookings_count = db.query(Booking).filter(
            Booking.customer_id == user_id
        ).count()
        
        # Get favorites count
        favorites_count = len(user.favorite_salons) if user.favorite_salons else 0
        
        return {
            "user_id": user_id,
            "user_name": f"{user.first_name} {user.last_name}",
            "total_bookings": recent_bookings_count,
            "favorite_salons_count": favorites_count,
            "recent_activity": [],
            "upcoming_appointments": []
        }

    @staticmethod
    def get_vendor_dashboard(db: Session, user_id: int):
        """Get vendor dashboard data"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get vendor's salons
        from app.models.salon import Salon
        from app.models.booking import Booking
        
        salons = db.query(Salon).filter(Salon.owner_id == user_id).all()
        total_salons = len(salons)
        
        # Get total bookings across all salons
        total_bookings = 0
        total_revenue = 0
        for salon in salons:
            salon_bookings = db.query(Booking).filter(Booking.salon_id == salon.id).all()
            total_bookings += len(salon_bookings)
            # Calculate revenue (you'll need to implement this based on your payment model)
        
        return {
            "user_id": user_id,
            "vendor_name": f"{user.first_name} {user.last_name}",
            "total_salons": total_salons,
            "total_bookings": total_bookings,
            "total_revenue": total_revenue,
            "recent_bookings": [],
            "salon_performance": []
        }

    @staticmethod
    def register_customer(db: Session, customer_data: CustomerRegister):
        """Register a new customer"""
        try:
            print(f"🔐 [AUTH] Customer registration attempt for: {customer_data.email}")
            
            # Check if email already exists
            existing_user = db.query(User).filter(User.email == customer_data.email).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Email already registered")
            
            existing_pending = db.query(PendingUser).filter(PendingUser.email == customer_data.email).first()
            if existing_pending:
                # Resend verification email - USING NEW SIGNATURE
                verification_url = f"https://salonconnect-qzne.onrender.com/api/users/verify-email?token={existing_pending.verification_token}"
                email_sent = EmailService.send_verification_email(
                    email=existing_pending.email,
                    first_name=existing_pending.first_name,
                    verification_url=verification_url
                )
                raise HTTPException(status_code=400, detail="Verification email already sent. Please check your email.")
            
            # Check phone number
            if customer_data.phone_number:
                existing_phone = db.query(User).filter(User.phone_number == customer_data.phone_number).first()
                if existing_phone:
                    raise HTTPException(status_code=400, detail="Phone number already registered")

            hashed_password = get_password_hash(customer_data.password)
            
            # Create pending user with CUSTOMER role
            verification_token = EmailService.generate_verification_token(customer_data.email)
            pending_user = PendingUser(
                email=customer_data.email,
                phone_number=customer_data.phone_number,
                password=hashed_password,
                first_name=customer_data.first_name,
                last_name=customer_data.last_name,
                role=UserRole.CUSTOMER,  # Always CUSTOMER for this endpoint
                verification_token=verification_token,
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            
            db.add(pending_user)
            db.commit()
            db.refresh(pending_user)
            
            # Send verification email - USING NEW SIGNATURE
            verification_url = f"https://salonconnect-qzne.onrender.com/api/users/verify-email?token={verification_token}"
            email_sent = EmailService.send_verification_email(
                email=customer_data.email,
                first_name=customer_data.first_name,
                verification_url=verification_url
            )
            
            return {
                "message": "Customer registration successful! Please check your email for verification link.",
                "email_sent": email_sent,
                "debug_info": {
                    "verification_url": verification_url,
                    "email": customer_data.email,
                    "role": "customer"
                } if os.getenv("DEBUG") == "True" else None
            }
                
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ [AUTH] Customer registration error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Customer registration failed. Please try again."
            )

    @staticmethod
    def register_vendor(db: Session, vendor_data: VendorRegister):
        """Register a new vendor with business info"""
        try:
            print(f"🔐 [AUTH] Vendor registration attempt for: {vendor_data.email}")
            
            # Check if email already exists
            existing_user = db.query(User).filter(User.email == vendor_data.email).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="Email already registered")
            
            existing_pending = db.query(PendingUser).filter(PendingUser.email == vendor_data.email).first()
            if existing_pending:
                # Resend verification email - USING NEW SIGNATURE
                verification_url = f"https://salonconnect-qzne.onrender.com/api/users/verify-email?token={existing_pending.verification_token}"
                email_sent = EmailService.send_verification_email(
                    email=existing_pending.email,
                    first_name=existing_pending.first_name,
                    verification_url=verification_url
                )
                raise HTTPException(status_code=400, detail="Verification email already sent. Please check your email.")
            
            # Check phone numbers
            existing_phone = db.query(User).filter(User.phone_number == vendor_data.phone_number).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Phone number already registered")
            
            # Check business phone (optional additional check)
            existing_business_phone = db.query(User).filter(User.phone_number == vendor_data.business_phone).first()
            if existing_business_phone:
                raise HTTPException(status_code=400, detail="Business phone number already registered")

            hashed_password = get_password_hash(vendor_data.password)
            
            # Create pending user with VENDOR role
            verification_token = EmailService.generate_verification_token(vendor_data.email)
            pending_user = PendingUser(
                email=vendor_data.email,
                phone_number=vendor_data.phone_number,
                password=hashed_password,
                first_name=vendor_data.first_name,
                last_name=vendor_data.last_name,
                role=UserRole.VENDOR,  # Always VENDOR for this endpoint
                verification_token=verification_token,
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            
            db.add(pending_user)
            db.commit()
            db.refresh(pending_user)
            
            # Send vendor-specific verification email - USING NEW SIGNATURE
            verification_url = f"https://salonconnect-qzne.onrender.com/api/users/verify-email?token={verification_token}"
            email_sent = EmailService.send_vendor_welcome_email(
                email=vendor_data.email,
                first_name=vendor_data.first_name,
                business_name=vendor_data.business_name,
                verification_url=verification_url
            )
            
            # Store business info
            from app.models.vendor import VendorBusinessInfo
            business_info = VendorBusinessInfo(
                email=vendor_data.email,
                business_name=vendor_data.business_name,
                business_phone=vendor_data.business_phone,
                business_address=vendor_data.business_address,
                business_city=vendor_data.business_city,
                business_state=vendor_data.business_state,
                business_country=vendor_data.business_country,
            )
            db.add(business_info)
            db.commit()
            
            return {
                "message": "Vendor registration successful! Please check your email for verification link.",
                "email_sent": email_sent,
                "debug_info": {
                    "verification_url": verification_url,
                    "email": vendor_data.email,
                    "role": "vendor",
                    "business_name": vendor_data.business_name
                } if os.getenv("DEBUG") == "True" else None
            }
                
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ [AUTH] Vendor registration error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vendor registration failed. Please try again."
            )

    @staticmethod
    async def register_google_user(db: Session, google_user: dict, registration_data: GoogleOAuthRegister = None):
        try:
            # Check if user already exists
            existing_user = db.query(User).filter(User.email == google_user['email']).first()
            
            if existing_user:
                # Update existing user with Google info if needed
                if not existing_user.google_id:
                    existing_user.google_id = google_user['google_id']
                    existing_user.is_oauth_user = True
                
                if not existing_user.is_verified:
                    existing_user.is_verified = True
                
                # Update name if different
                if (existing_user.first_name != google_user['first_name'] or 
                    existing_user.last_name != google_user['last_name']):
                    existing_user.first_name = google_user['first_name']
                    existing_user.last_name = google_user['last_name']
                    existing_user.updated_at = datetime.utcnow()
                
                db.commit()
                db.refresh(existing_user)
                return existing_user, False  # False means existing user
            
            # Create new user
            auto_password = f"google_oauth_{secrets.token_urlsafe(12)}"
            hashed_password = get_password_hash(auto_password)
            
            # Determine role
            user_role = UserRole.CUSTOMER
            if google_user['email'] in settings.ADMIN_EMAILS:
                user_role = UserRole.ADMIN
            elif registration_data and registration_data.role:
                user_role = registration_data.role
            
            user = User(
                email=google_user['email'],
                password=hashed_password,
                first_name=google_user['first_name'],
                last_name=google_user['last_name'],
                role=user_role,
                google_id=google_user['google_id'],
                is_oauth_user=True,
                is_verified=True,
                is_active=True
            )
            
            # Add phone number if provided during registration
            if registration_data and registration_data.phone_number:
                user.phone_number = registration_data.phone_number
            
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # Create user profile
            profile = UserProfile(user_id=user.id)
            if google_user.get('picture'):
                profile.profile_picture = google_user['picture']
            db.add(profile)
            db.commit()
            
            print(f"✅ Created new user via Google OAuth: {user.email} with role: {user.role}")
            return user, True  # True means new user
            
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating Google OAuth user: {e}")
            raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")
    
    @staticmethod
    def send_welcome_notification(user: User, is_new_user: bool):
        """Send welcome email to new users"""
        try:
            if is_new_user:
                subject = "Welcome to Salon Connect!"
                html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .role-badge {{ display: inline-block; background: #007bff; color: white; padding: 5px 15px; border-radius: 20px; font-size: 14px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Welcome to Salon Connect! 🎉</h1>
                        </div>
                        <div class="content">
                            <h2>Hello {user.first_name} {user.last_name}!</h2>
                            <p>Thank you for joining Salon Connect. We're excited to have you on board!</p>
                            
                            <p><strong>Your Account Details:</strong></p>
                            <ul>
                                <li><strong>Email:</strong> {user.email}</li>
                                <li><strong>Role:</strong> <span class="role-badge">{user.role.value.upper()}</span></li>
                                <li><strong>Account Type:</strong> Google OAuth</li>
                            </ul>
                            
                            <p>As a {user.role.value}, you can now:</p>
                            {"<ul><li>Browse and book salon services</li><li>Manage your appointments</li><li>Save favorite salons</li><li>Write reviews</li></ul>" if user.role == UserRole.CUSTOMER else 
                             "<ul><li>Create and manage your salon profile</li><li>Accept bookings from customers</li><li>Manage your services and availability</li><li>Track your business performance</li></ul>"}
                            
                            <p>If you have any questions, feel free to reach out to our support team.</p>
                            
                            <p>Best regards,<br>The Salon Connect Team</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                # Send welcome email using the generic send_email method
                email_sent = EmailService.send_email(
                    to_email=user.email,
                    subject=subject,
                    html_content=html_content
                )
                if email_sent:
                    print(f"✅ Welcome email sent to: {user.email}")
                else:
                    print(f"❌ Failed to send welcome email to: {user.email}")
            
        except Exception as e:
            print(f"❌ Failed to send welcome notification: {e}")
    
    @staticmethod
    def get_user_role_permissions(role: UserRole):
        permissions = {
            UserRole.CUSTOMER: [
                "view_salons", "book_appointments", "manage_own_bookings", 
                "view_own_profile", "update_own_profile", "favorite_salons",
                "write_reviews", "cancel_own_bookings", "view_booking_history"
            ],
            UserRole.VENDOR: [
                "manage_salons", "manage_bookings", "view_reports", 
                "update_business_info", "manage_services", "view_analytics",
                "manage_availability", "process_payments", "manage_staff"
            ],
            UserRole.ADMIN: [
                "manage_users", "manage_all_salons", "view_all_reports",
                "system_configuration", "content_moderation", "all_permissions",
                "manage_payments", "view_analytics", "manage_system_settings"
            ]
        }
        return permissions.get(role, [])
    
    @staticmethod
    def can_user_access(user: User, permission: str):
        user_permissions = AuthService.get_user_role_permissions(user.role)
        return permission in user_permissions


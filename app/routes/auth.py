from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import os
import jwt

from app.services.auth import AuthService
from app.schemas.user import (
    CustomerRegister, VendorRegister, UserCreate, UserResponse, 
    Token, UserLogin, ForgotPasswordRequest, ResetPasswordRequest, 
    ChangePasswordRequest, OTPLoginRequest, OTPVerifyRequest
)
from app.services.email import EmailService
from app.core.security import verify_token, get_password_hash, create_access_token, verify_password
from app.database import get_db
from app.core.config import settings
from app.models.vendor import VendorBusinessInfo
from app.models.salon import Salon
from app.models.user import User, PasswordReset, PendingUser, UserOTP, UserRole
import logging

router = APIRouter()

logger = logging.getLogger(__name__)
security = HTTPBearer()
templates = Jinja2Templates(directory="app/templates")

# Use settings from config instead of os.getenv for consistency
BASE_URL = settings.CURRENT_BASE_URL
FRONTEND_URL = settings.FRONTEND_URL

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security), 
    db: Session = Depends(get_db)
):
    """Get current authenticated user"""
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    return user

@router.post("/register/customer")
def register_customer(customer_data: CustomerRegister, db: Session = Depends(get_db)):
    """Register a new customer"""
    return AuthService.register_customer(db, customer_data)

@router.post("/register/vendor")
def register_vendor(vendor_data: VendorRegister, db: Session = Depends(get_db)):
    """Register a new vendor with business information"""
    return AuthService.register_vendor(db, vendor_data)

@router.post("/register")
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user - sends verification email"""
    try:
        logger.info(f"[AUTH] Registration attempt for: {user_data.email}")
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Check if pending user exists
        existing_pending = db.query(PendingUser).filter(PendingUser.email == user_data.email).first()
        if existing_pending:
            # Resend verification email
            verification_url = f"{BASE_URL}/api/users/verify-email?token={existing_pending.verification_token}"
            email_sent = EmailService.send_verification_email(
                email=user_data.email,
                first_name=user_data.first_name,
                verification_url=verification_url
            )
            raise HTTPException(
                status_code=400, 
                detail="Verification email already sent. Please check your email."
            )
        
        # Check phone number if provided
        if user_data.phone_number:
            existing_phone = db.query(User).filter(User.phone_number == user_data.phone_number).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Phone number already registered")

        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # Generate verification token
        verification_token = EmailService.generate_verification_token(user_data.email)
        
        # Create pending user
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
        
        # Send verification email
        verification_url = f"{BASE_URL}/api/users/verify-email?token={verification_token}"
        email_sent = EmailService.send_verification_email(
            email=user_data.email,
            first_name=user_data.first_name,
            verification_url=verification_url
        )
        
        return {
            "message": "Registration successful! Please check your email for verification link.",
            "email_sent": email_sent,
            "debug_info": {
                "verification_url": verification_url,
                "email": user_data.email
            } if settings.DEBUG else None
        }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed. Please try again."
        )

@router.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str = Query(...), db: Session = Depends(get_db)):
    """Verify user email and show success page"""
    try:
        logger.info(f"[AUTH] Email verification attempt with token: {token[:50]}...")
        # Verify token
        payload = EmailService.verify_token(token, 'email_verification')
        if not payload:
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")
        
        # Find pending user
        pending_user = db.query(PendingUser).filter(
            PendingUser.email == payload['email'],
            PendingUser.expires_at > datetime.utcnow()
        ).first()
        
        if not pending_user:
            raise HTTPException(status_code=404, detail="Verification token not found or expired")
        
        # Create user
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
        
        # If vendor, create initial salon
        if user.role == UserRole.VENDOR:
            business_info = db.query(VendorBusinessInfo).filter(
                VendorBusinessInfo.email == user.email
            ).first()
            
            if business_info:
                initial_salon = Salon(
                    owner_id=user.id,
                    name=business_info.business_name,
                    address=business_info.business_address,
                    city=business_info.business_city,
                    state=business_info.business_state,
                    country=business_info.business_country,
                    phone_number=business_info.business_phone,
                    email=user.email,
                    is_active=True
                )
                db.add(initial_salon)
                db.commit()
                logger.info(f"Created initial salon for vendor: {user.email}")
        # Clean up pending user
        db.delete(pending_user)
        db.commit()
        
        logger.info(f"[AUTH] Email verified successfully for: {user.email}")
        return templates.TemplateResponse("email_verified.html", {"request": request})
        
    except Exception as e:
        logger.error(f"[AUTH] Email verification error: {str(e)}")
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Verification Failed - Salon Connect</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
                .error {{ color: #dc3545; font-size: 20px; margin-bottom: 20px; }}
                .button {{ background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="error">⚠️ Verification Failed</div>
            <p>{str(e)}</p>
            <a href="{FRONTEND_URL}/register" class="button">Try Registering Again</a>
        </body>
        </html>
        """)

@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request password reset - sends email with reset link"""
    try:
        logger.info(f"[AUTH] Forgot password attempt for: {request.email}")
        user = db.query(User).filter(User.email == request.email).first()
        if not user:
            logger.info(f"[AUTH] User not found for email: {request.email}")
            return {"message": "If the email exists, a password reset link will be sent."}
        
        reset_token = EmailService.generate_reset_token(user.email)
        
        # Save reset token
        password_reset = PasswordReset(
            user_id=user.id,
            token=reset_token,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        db.add(password_reset)
        db.commit()
        
        reset_url = f"{BASE_URL}/api/users/reset-password-page?token={reset_token}"
        
        # Send email
        email_sent = EmailService.send_password_reset_email(
            email=user.email,
            first_name=user.first_name,
            reset_url=reset_url
        )
        logger.info(f"[AUTH] Password reset email sent status: {email_sent}")
        return {
            "message": "Password reset link sent to your email.",
            "email_sent": email_sent,
            "debug_info": {
                "reset_url": reset_url,
                "email": request.email
            } if settings.DEBUG else None
        }
            
    except Exception as e:
        logger.error(f"[AUTH] Forgot password error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/reset-password-page", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = Query(...), db: Session = Depends(get_db)):
    """Serve the beautiful reset password page with token validation"""
    try:
        logger.info(f"[AUTH] Reset password page access with token: {token[:50]}...")
        if token.startswith("b'") and token.endswith("'"):
            token = token[2:-1]
        
        payload = EmailService.verify_reset_token(token)
        if not payload:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "Invalid or expired reset link. Please request a new password reset.",
                "valid_token": False
            })
        
        password_reset = db.query(PasswordReset).filter(
            PasswordReset.token == token,
            PasswordReset.expires_at > datetime.utcnow(),
            PasswordReset.used == False
        ).first()
        
        if not password_reset:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "Invalid or expired reset link. Please request a new password reset.",
                "valid_token": False
            })
        
        return templates.TemplateResponse("reset_password.html", {
            "request": request, 
            "token": token,
            "valid_token": True
        })
        
    except Exception as e:
        logger.error(f"[AUTH] Reset password page error: {str(e)}")
        return templates.TemplateResponse("reset_password.html", {
            "request": request, 
            "error": "An error occurred. Please try again.",
            "valid_token": False
        })

@router.post("/reset-password")
def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Reset password with token from form"""
    try:
        logger.info(f"[AUTH] Password reset attempt with token: {token[:50]}...")
        payload = EmailService.verify_reset_token(token)
        if not payload:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "Invalid or expired reset token",
                "valid_token": False
            })
        
        user = db.query(User).filter(User.email == payload['email']).first()
        if not user:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "User not found",
                "valid_token": False
            })
        
        password_reset = db.query(PasswordReset).filter(
            PasswordReset.user_id == user.id,
            PasswordReset.token == token,
            PasswordReset.expires_at > datetime.utcnow(),
            PasswordReset.used == False
        ).first()
        
        if not password_reset:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "Invalid or expired reset token",
                "valid_token": False
            })
        
        if new_password != confirm_password:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "Passwords do not match",
                "token": token,
                "valid_token": True
            })
        
        if len(new_password) < 6:
            return templates.TemplateResponse("reset_password.html", {
                "request": request, 
                "error": "Password must be at least 6 characters long",
                "token": token,
                "valid_token": True
            })
        
        # Update password
        user.password = get_password_hash(new_password)
        password_reset.used = True
        db.commit()
        
        logger.info(f"[AUTH] Password reset successful for user: {user.email}")
        return templates.TemplateResponse("password_reset_success.html", {
            "request": request
        })
        
    except Exception as e:
        logger.error(f"[AUTH] Password reset error: {str(e)}")
        return templates.TemplateResponse("reset_password.html", {
            "request": request, 
            "error": "An error occurred. Please try again.",
            "valid_token": False
        })

@router.post("/resend-verification")
def resend_verification(email: str, db: Session = Depends(get_db)):
    """Resend email verification"""
    try:
        logger.info(f"[AUTH] Resend verification attempt for: {email}")
        # First check if user already exists and is verified
        existing_user = db.query(User).filter(User.email == email, User.is_verified == True).first()
        if existing_user:
            # Return proper 400 response
            raise HTTPException(
                status_code=400, 
                detail="Email already verified. You can log in to your account."
            )
        
        # Check for pending user
        pending_user = db.query(PendingUser).filter(PendingUser.email == email).first()
        if not pending_user:
            # For security, don't reveal if account exists
            return {
                "message": "If you have an account, a verification link has been sent to your email.",
                "email_sent": False
            }
        
        # Check if verification token is expired
        if pending_user.expires_at < datetime.utcnow():
            # Generate new token
            new_token = EmailService.generate_verification_token(email)
            pending_user.verification_token = new_token
            pending_user.expires_at = datetime.utcnow() + timedelta(hours=24)
            db.commit()
            verification_url = f"{BASE_URL}/api/users/verify-email?token={new_token}"
        else:
            verification_url = f"{BASE_URL}/api/users/verify-email?token={pending_user.verification_token}"
        
        # Send verification email
        email_sent = EmailService.send_verification_email(
            email=email,
            first_name=pending_user.first_name,
            verification_url=verification_url
        )
        
        logger.info(f"[AUTH] Resend verification email sent status: {email_sent}")
        return {
            "message": "Verification email sent successfully",
            "email_sent": email_sent
        }
        
    except HTTPException:
        # Re-raise HTTPException to maintain proper status code
        raise
    except Exception as e:
        logger.error(f"[AUTH] Resend verification error: {str(e)}")
        # Return error response without raising HTTPException
        return {
            "message": "Failed to resend verification email",
            "error": str(e),
            "email_sent": False
        }

@router.post("/login", response_model=Token)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """Password login"""
    try:
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Login error: {str(e)}")
        raise HTTPException(status_code=401, detail="Login failed")

@router.post("/login/otp/request")
def request_otp_login(request: OTPLoginRequest, db: Session = Depends(get_db)):
    """Request OTP for login"""
    try:
        user = db.query(User).filter(User.email == request.email).first()
        if not user:
            # For security, don't reveal if user exists
            return {"message": "If the email exists, an OTP has been sent"}
        
        if not user.is_verified:
            raise HTTPException(status_code=400, detail="Please verify your email first")
        
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Account is deactivated")
        
        # Generate OTP
        otp = EmailService.generate_otp()
        
        # Create OTP record
        user_otp = UserOTP(
            user_id=user.id,
            otp=otp,
            expires_at=datetime.utcnow() + timedelta(minutes=10)
        )
        
        # Mark previous OTPs as used
        db.query(UserOTP).filter(
            UserOTP.user_id == user.id,
            UserOTP.used == False
        ).update({"used": True})
        
        db.add(user_otp)
        db.commit()
        
        # Send OTP email
        email_sent = EmailService.send_otp_email(
            email=user.email,
            first_name=user.first_name,
            otp=otp
        )
        
        return {
            "message": "OTP sent to your email",
            "email_sent": email_sent
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] OTP request error: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to send OTP")

@router.post("/login/otp/verify", response_model=Token)
def verify_otp_login(request: OTPVerifyRequest, db: Session = Depends(get_db)):
    """Verify OTP and login"""
    try:
        user = db.query(User).filter(User.email == request.email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Verify OTP
        user_otp = db.query(UserOTP).filter(
            UserOTP.user_id == user.id,
            UserOTP.otp == request.otp,
            UserOTP.expires_at > datetime.utcnow(),
            UserOTP.used == False
        ).first()
        
        if not user_otp:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
        
        # Mark OTP as used
        user_otp.used = True
        db.commit()
        
        # Create tokens
        access_token = create_access_token(data={"user_id": user.id, "email": user.email})
        refresh_token = create_access_token(data={"user_id": user.id}, expires_delta=timedelta(days=7))
        
        return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] OTP verify error: {str(e)}")
        raise HTTPException(status_code=400, detail="OTP verification failed")

@router.post("/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Change password for authenticated user"""
    try:
        if not verify_password(request.current_password, current_user.password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        
        current_user.password = get_password_hash(request.new_password)
        db.commit()
        
        return {"message": "Password changed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Change password error: {str(e)}")
        raise HTTPException(status_code=400, detail="Password change failed")

@router.post("/token/refresh", response_model=Token)
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    """Refresh access token"""
    try:
        payload = verify_token(refresh_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        new_access_token = create_access_token(data={"user_id": user.id, "email": user.email})
        return Token(access_token=new_access_token, refresh_token=refresh_token, token_type="bearer")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Token refresh error: {str(e)}")
        raise HTTPException(status_code=401, detail="Token refresh failed")

@router.get("/token/verify")
def verify_token_endpoint(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify token validity"""
    try:
        token = credentials.credentials
        payload = verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return {"valid": True, "user_id": payload.get("user_id")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Token verify error: {str(e)}")
        raise HTTPException(status_code=401, detail="Token verification failed")

@router.post("/logout")
def logout(current_user: dict = Depends(get_current_user)):
    """Logout user (client should remove tokens)"""
    return {"message": "Successfully logged out"}

@router.get("/debug-env")
def debug_environment():
    """Debug environment variables on Render"""
    import os
    
    env_vars = {
        "SMTP_HOST": os.getenv("SMTP_HOST"),
        "SMTP_PORT": os.getenv("SMTP_PORT"), 
        "SMTP_USER": os.getenv("SMTP_USER"),
        "FROM_EMAIL": os.getenv("FROM_EMAIL"),
        "SENDGRID_API_KEY_SET": bool(os.getenv("SENDGRID_API_KEY")),
        "SENDGRID_API_KEY_LENGTH": len(os.getenv("SENDGRID_API_KEY", "")),
        "DEBUG": os.getenv("DEBUG"),
        "ENVIRONMENT": os.getenv("ENVIRONMENT"),
        "RENDER": os.getenv("RENDER"),
        "RENDER_EXTERNAL_URL": os.getenv("RENDER_EXTERNAL_URL"),
        "BASE_URL": BASE_URL,
        "FRONTEND_URL": FRONTEND_URL
    }
    
    logger.debug(f"[ENV DEBUG] Environment variables: {env_vars}")
    return env_vars

@router.get("/debug-email")
def debug_email_config():
    """Debug endpoint to check email configuration"""
    import os
    
    config_info = {
        "FROM_EMAIL": settings.FROM_EMAIL,
        "SENDGRID_API_KEY_SET": bool(settings.SENDGRID_API_KEY),
        "SENDGRID_API_KEY_LENGTH": len(settings.SENDGRID_API_KEY) if settings.SENDGRID_API_KEY else 0,
        "DEBUG": settings.DEBUG,
        "ENVIRONMENT": "PRODUCTION" if settings.IS_PRODUCTION else "DEVELOPMENT",
        "BASE_URL": BASE_URL,
        "FRONTEND_URL": FRONTEND_URL
    }
    
    logger.debug(f"[DEBUG] Email Configuration: {config_info}")
    return config_info
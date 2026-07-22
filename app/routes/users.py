from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.schemas.user import UserResponse, UserProfileResponse, UserProfileUpdate
from app.core.security import verify_token
from app.services.auth import AuthService
from app.core.cloudinary import upload_image
from app.models.user import User, UserProfile


from app.routes import google_oauth

router = APIRouter()
security = HTTPBearer()

# Include Google OAuth routes
# router.include_router(google_oauth.router, prefix="/api/users", tags=["Google OAuth"])



async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    user_id = payload.get("user_id")
    user = AuthService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    return user

@router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user

@router.get("/me/profile", response_model=UserProfileResponse)
def get_user_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user profile"""
    profile = AuthService.get_user_profile(db, current_user.id)
    return profile

@router.put("/me/profile", response_model=UserProfileResponse)
def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user profile"""
    updated_profile = AuthService.update_user_profile(db, current_user.id, profile_data)
    return updated_profile

@router.get("/me/role")
def get_user_role(current_user: User = Depends(get_current_user)):
    """Get current user role"""
    return {"role": current_user.role.value}  

@router.get("/customer/dashboard")
def get_customer_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get customer dashboard data"""
    if current_user.role.value != "customer":  
        raise HTTPException(status_code=403, detail="Only customers can access this endpoint")
    return AuthService.get_customer_dashboard(db, current_user.id)

@router.get("/vendor/dashboard")
def get_vendor_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get vendor dashboard data"""
    if current_user.role.value != "vendor":  
        raise HTTPException(status_code=403, detail="Only vendors can access this endpoint")
    return AuthService.get_vendor_dashboard(db, current_user.id)

@router.post("/me/profile/picture", response_model=UserProfileResponse)
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload profile picture"""
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    try:
        
        result = upload_image(file.file, folder="salon_connect/profiles")
        profile_picture_url = result.get('secure_url')
        
        
        profile_data = UserProfileUpdate(profile_picture=profile_picture_url)
        updated_profile = AuthService.update_user_profile(db, current_user.id, profile_data)
        
        return updated_profile
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading image: {str(e)}")

@router.delete("/me/profile/remove-picture", response_model=UserProfileResponse)
def remove_profile_picture(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove profile picture"""
    profile_data = UserProfileUpdate(profile_picture=None)
    updated_profile = AuthService.update_user_profile(db, current_user.id, profile_data)
    return updated_profile
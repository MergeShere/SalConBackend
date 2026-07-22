from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.services.auth import AuthService
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.schemas.user import GoogleOAuthRegister
from app.core.config import settings
import json
import secrets
import time
import httpx
import traceback

router = APIRouter()

class GoogleOAuthService:
    async def start_oauth(self, request: Request, is_registration: bool = False):
        """Start OAuth flow and return authorization URL"""
        try:
            if not settings.GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=500, detail="Google OAuth not configured")

            state = secrets.token_urlsafe(32)
            
            # Store in session
            request.session['oauth_state'] = state
            request.session['oauth_timestamp'] = time.time()
            request.session['oauth_purpose'] = 'registration' if is_registration else 'login'
            
            # Build authorization URL
            auth_url = (
                f"https://accounts.google.com/o/oauth2/v2/auth?"
                f"client_id={settings.GOOGLE_CLIENT_ID}&"
                f"redirect_uri={settings.GOOGLE_REDIRECT_URI}&"
                f"response_type=code&"
                f"scope=email%20profile%20openid&"
                f"state={state}&"
                f"access_type=offline&"
                f"prompt=select_account"
            )
            
            return auth_url
            
        except Exception as e:
            print(f"Error generating authorization URL: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start OAuth: {str(e)}")

    async def handle_callback(self, request: Request):
        """Handle OAuth callback from Google"""
        try:
            # Get query parameters
            error = request.query_params.get('error')
            code = request.query_params.get('code')
            state = request.query_params.get('state')
            
            if error:
                error_description = request.query_params.get('error_description', 'Authentication failed')
                raise HTTPException(status_code=400, detail=f"Google OAuth error: {error_description}")
            
            if not code:
                raise HTTPException(status_code=400, detail="No authorization code received")
            
            if not state:
                raise HTTPException(status_code=400, detail="No state parameter received")
            
            # Verify state
            stored_state = request.session.get('oauth_state')
            stored_timestamp = request.session.get('oauth_timestamp')
            oauth_purpose = request.session.get('oauth_purpose', 'login')
            
            if not stored_state or stored_state != state:
                raise HTTPException(status_code=400, detail="Session expired. Please try again.")
            
            if stored_timestamp and (time.time() - stored_timestamp) > 600:
                raise HTTPException(status_code=400, detail="Session expired")
            
            # Exchange code for tokens
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        'client_id': settings.GOOGLE_CLIENT_ID,
                        'client_secret': settings.GOOGLE_CLIENT_SECRET,
                        'code': code,
                        'grant_type': 'authorization_code',
                        'redirect_uri': settings.GOOGLE_REDIRECT_URI,
                    }
                )
                
                if token_response.status_code != 200:
                    error_detail = token_response.text
                    print(f"Token exchange failed: {error_detail}")
                    raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
                
                token_data = token_response.json()
                access_token = token_data.get('access_token')
            
            # Get user info
            async with httpx.AsyncClient() as client:
                userinfo_response = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if userinfo_response.status_code != 200:
                    raise HTTPException(status_code=400, detail="Failed to get user information")
                
                user_info = userinfo_response.json()
            
            # Prepare user data
            google_user_data = {
                'email': user_info['email'],
                'first_name': user_info.get('given_name', ''),
                'last_name': user_info.get('family_name', ''),
                'picture': user_info.get('picture', ''),
                'google_id': user_info['sub'],
                'email_verified': user_info.get('email_verified', False)
            }
            
            # Store for registration if needed
            if oauth_purpose == 'registration':
                request.session['pending_google_user'] = google_user_data
                request.session['oauth_temp_id'] = secrets.token_urlsafe(16)
            
            # Clean up session
            self._cleanup_oauth_session(request)
            
            return google_user_data, oauth_purpose
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"OAuth callback error: {e}")
            raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")
    
    def _cleanup_oauth_session(self, request: Request):
        """Clean up OAuth session data"""
        session_keys = ['oauth_state', 'oauth_timestamp', 'oauth_purpose']
        for key in session_keys:
            if key in request.session:
                del request.session[key]

# Create global instance
google_oauth_service = GoogleOAuthService()

# Google OAuth Login - Returns JSON for API calls, Redirect for browser
@router.get("/google/login", tags=["Google OAuth"], response_class=JSONResponse)
async def google_login(request: Request):
    try:
        auth_url = await google_oauth_service.start_oauth(request, is_registration=False)
        
        # Check if this is an API call (based on headers)
        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header:
            return JSONResponse(
                status_code=200,
                content={
                    "message": "OAuth flow started",
                    "auth_url": auth_url,
                    "redirect_required": True
                }
            )
        else:
            # Browser request - redirect directly
            return RedirectResponse(url=auth_url)
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )

# Google OAuth Registration - Returns JSON for API calls, Redirect for browser
@router.get("/google/register", tags=["Google OAuth"], response_class=JSONResponse)
async def google_register(request: Request):
    try:
        auth_url = await google_oauth_service.start_oauth(request, is_registration=True)
        
        # Check if this is an API call (based on headers)
        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header:
            return JSONResponse(
                status_code=200,
                content={
                    "message": "OAuth registration flow started",
                    "auth_url": auth_url,
                    "redirect_required": True
                }
            )
        else:
            # Browser request - redirect directly
            return RedirectResponse(url=auth_url)
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )

# OAuth Callback Handler - This should only be called by Google
@router.get("/google/callback", tags=["Google OAuth"])
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        google_user, oauth_purpose = await google_oauth_service.handle_callback(request)
        
        # Check if user exists
        existing_user = db.query(User).filter(User.email == google_user['email']).first()
        
        if existing_user:
            # Existing user - proceed with login
            access_token = create_access_token(
                data={"user_id": existing_user.id, "email": existing_user.email, "role": existing_user.role.value}
            )
            refresh_token = create_access_token(
                data={"user_id": existing_user.id}, 
                expires_delta=timedelta(days=7)
            )
            
            # PRINT TOKENS TO SERVER CONSOLE
            print("\n" + "="*60)
            print("GOOGLE OAUTH LOGIN - TOKENS GENERATED")
            print("="*60)
            print(f"User: {existing_user.email} (ID: {existing_user.id})")
            print(f"Email: {google_user['email']}")
            print(f"Role: {existing_user.role.value}")
            print("="*60)
            print(f"ACCESS TOKEN:\n{access_token}")
            print("="*60)
            print(f"REFRESH TOKEN:\n{refresh_token}")
            print("="*60)
            print("Copy these tokens to authorize your API requests!")
            print("="*60 + "\n")
            
            user_permissions = AuthService.get_user_role_permissions(existing_user.role)
            
            return HTMLResponse(content=create_success_html(
                existing_user, google_user, access_token, refresh_token, user_permissions, is_new_user=False
            ))
        
        elif oauth_purpose == 'registration':
            # New user for registration - show role selection form
            temp_session_id = request.session.get('oauth_temp_id')
            if not temp_session_id:
                temp_session_id = secrets.token_urlsafe(16)
                request.session['oauth_temp_id'] = temp_session_id
            
            return HTMLResponse(content=create_registration_form(google_user, temp_session_id))
        else:
            # New user but trying to login - redirect to registration
            return HTMLResponse(content=create_redirect_to_registration(google_user))
        
    except Exception as e:
        print(f"ERROR in Google OAuth callback: {str(e)}")
        return HTMLResponse(content=create_error_html(str(e)), status_code=400)

@router.post("/google/complete-registration", tags=["Google OAuth"])
async def complete_google_registration(
    request: Request,
    role: str = Form(...),
    phone_number: str = Form(None),
    temp_session_id: str = Form(None),
    db: Session = Depends(get_db)
):
    try:
        print("Starting complete registration")
        
        # Get session data
        pending_user = request.session.get('pending_google_user')
        stored_temp_id = request.session.get('oauth_temp_id')
        
        # Check if we have the necessary data
        if not pending_user:
            raise HTTPException(status_code=400, detail="No registration data found. Please start the registration process again.")
        
        # Use stored_temp_id if temp_session_id is not provided
        if not temp_session_id:
            temp_session_id = stored_temp_id
        
        if not temp_session_id:
            raise HTTPException(status_code=400, detail="Session identifier missing.")
        
        if stored_temp_id != temp_session_id:
            raise HTTPException(status_code=400, detail="Registration session expired. Please start over.")
        
        # Validate role
        try:
            user_role = UserRole(role)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid role selected")
        
        # Create registration data
        registration_data = GoogleOAuthRegister(
            role=user_role,
            phone_number=phone_number
        )
        
        # Register the user
        user, is_new_user = await AuthService.register_google_user(db, pending_user, registration_data)
        
        # Generate tokens
        access_token = create_access_token(
            data={"user_id": user.id, "email": user.email, "role": user.role.value}
        )
        refresh_token = create_access_token(
            data={"user_id": user.id}, 
            expires_delta=timedelta(days=7)
        )
        
        # PRINT TOKENS TO SERVER CONSOLE FOR NEW REGISTRATIONS
        print("\n" + "="*60)
        print("GOOGLE OAUTH REGISTRATION - TOKENS GENERATED")
        print("="*60)
        print(f"New User: {user.email} (ID: {user.id})")
        print(f"Email: {pending_user['email']}")
        print(f"Role: {user.role.value}")
        print("="*60)
        print(f"ACCESS TOKEN:\n{access_token}")
        print("="*60)
        print(f"REFRESH TOKEN:\n{refresh_token}")
        print("="*60)
        print("Copy these tokens to authorize your API requests!")
        print("="*60 + "\n")
        
        user_permissions = AuthService.get_user_role_permissions(user.role)
        
        # Clean up session
        if 'pending_google_user' in request.session:
            del request.session['pending_google_user']
        if 'oauth_temp_id' in request.session:
            del request.session['oauth_temp_id']
        
        return HTMLResponse(content=create_success_html(
            user, pending_user, access_token, refresh_token, user_permissions, is_new_user=True
        ))
        
    except Exception as e:
        print(f"ERROR in complete registration: {str(e)}")
        return HTMLResponse(content=create_error_html(str(e)), status_code=400)

# HTML Template Functions
def create_registration_form(google_user, temp_session_id):
    # Ensure temp_session_id is not None
    if not temp_session_id:
        temp_session_id = "missing_session_id"
        
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Complete Registration - Salon Connect</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }}
            .container {{
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                max-width: 500px;
                width: 90%;
            }}
            .user-info {{
                text-align: center;
                margin-bottom: 30px;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 8px;
            }}
            .avatar {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                margin: 0 auto 15px;
            }}
            .form-group {{
                margin-bottom: 20px;
            }}
            label {{
                display: block;
                margin-bottom: 8px;
                font-weight: bold;
                color: #333;
            }}
            select, input {{
                width: 100%;
                padding: 12px;
                border: 2px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
                box-sizing: border-box;
            }}
            select:focus, input:focus {{
                border-color: #667eea;
                outline: none;
            }}
            .role-option {{
                display: flex;
                align-items: center;
                padding: 15px;
                margin: 10px 0;
                border: 2px solid #ddd;
                border-radius: 8px;
                cursor: pointer;
                transition: all 0.3s;
            }}
            .role-option:hover {{
                border-color: #667eea;
                background: #f8f9fa;
            }}
            .role-option.selected {{
                border-color: #667eea;
                background: #667eea;
                color: white;
            }}
            .role-icon {{
                font-size: 24px;
                margin-right: 15px;
            }}
            .role-info h3 {{
                margin: 0 0 5px 0;
            }}
            .role-info p {{
                margin: 0;
                font-size: 14px;
                opacity: 0.8;
            }}
            .submit-btn {{
                background: #28a745;
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 5px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
                margin-top: 20px;
            }}
            .submit-btn:hover {{
                background: #218838;
            }}
            .debug-info {{
                background: #f8f9fa;
                padding: 10px;
                border-radius: 5px;
                font-size: 12px;
                color: #666;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="user-info">
                <img class="avatar" src="{google_user.get('picture', '')}" alt="Profile Picture" onerror="this.style.display='none'">
                <h2>Complete Your Registration</h2>
                <p>Welcome, {google_user['first_name']}! Please choose your account type:</p>
                <div class="debug-info">
                    Debug: Session ID = {temp_session_id}
                </div>
            </div>

            <form action="/api/auth/google/complete-registration" method="post" id="registrationForm">
                <input type="hidden" name="temp_session_id" value="{temp_session_id}">
                
                <div class="form-group">
                    <label>Account Type *</label>
                    
                    <div class="role-option" onclick="selectRole('customer')">
                        <div class="role-icon">👤</div>
                        <div class="role-info">
                            <h3>Customer</h3>
                            <p>Book appointments, find salons, manage bookings</p>
                        </div>
                        <input type="radio" name="role" value="customer" required style="display: none;">
                    </div>
                    
                    <div class="role-option" onclick="selectRole('vendor')">
                        <div class="role-icon">💼</div>
                        <div class="role-info">
                            <h3>Vendor</h3>
                            <p>Manage your salon, accept bookings, grow your business</p>
                        </div>
                        <input type="radio" name="role" value="vendor" required style="display: none;">
                    </div>
                </div>

                <div class="form-group">
                    <label for="phone_number">Phone Number (Optional)</label>
                    <input type="tel" id="phone_number" name="phone_number" placeholder="+1234567890">
                    <small style="color: #666;">Include country code. We'll use this for booking notifications.</small>
                </div>

                <button type="submit" class="submit-btn">Complete Registration</button>
            </form>
        </div>

        <script>
            console.log('Registration form loaded');
            console.log('Temp session ID:', '{temp_session_id}');
            console.log('Form action:', document.getElementById('registrationForm').action);
            
            function selectRole(role) {{
                document.querySelectorAll('.role-option').forEach(opt => {{
                    opt.classList.remove('selected');
                    opt.querySelector('input[type="radio"]').checked = false;
                }});
                
                const selectedOption = event.currentTarget;
                selectedOption.classList.add('selected');
                selectedOption.querySelector('input[type="radio"]').checked = true;
            }}

            document.getElementById('registrationForm').addEventListener('submit', function(e) {{
                const roleSelected = document.querySelector('input[name="role"]:checked');
                if (!roleSelected) {{
                    e.preventDefault();
                    alert('Please select an account type');
                    return false;
                }}
                console.log('Form submitting with session ID:', '{temp_session_id}');
            }});
        </script>
    </body>
    </html>
    """

def create_success_html(user, google_user, access_token, refresh_token, permissions, is_new_user):
    welcome_message = "Welcome to Salon Connect!" if is_new_user else "Welcome back to Salon Connect!"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Registration Successful - Salon Connect</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }}
            .container {{
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                text-align: center;
                max-width: 500px;
            }}
            .success {{
                color: #28a745;
                font-size: 48px;
                margin-bottom: 20px;
            }}
            .user-info {{
                margin: 20px 0;
            }}
            .avatar {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                margin: 0 auto 15px;
            }}
            .role-badge {{
                display: inline-block;
                padding: 5px 15px;
                background: #007bff;
                color: white;
                border-radius: 20px;
                font-size: 14px;
                margin: 10px 0;
            }}
            .welcome-badge {{
                display: inline-block;
                padding: 5px 15px;
                background: #28a745;
                color: white;
                border-radius: 20px;
                font-size: 14px;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success">Success</div>
            <h2>{welcome_message}</h2>
            
            <div class="user-info">
                <img class="avatar" src="{google_user.get('picture', '')}" alt="Profile Picture" onerror="this.style.display='none'">
                <h3>{user.first_name} {user.last_name}</h3>
                <p>{user.email}</p>
                <div class="role-badge">{user.role.value.upper()}</div>
                {'<div class="welcome-badge">NEW USER</div>' if is_new_user else ''}
            </div>
            
            <p>Your account has been successfully {"created" if is_new_user else "accessed"}.</p>
            {'<p>We have sent a welcome email with more information.</p>' if is_new_user else ''}
            
            <script>
                const authData = {{
                    access_token: "{access_token}",
                    refresh_token: "{refresh_token}",
                    user: {{
                        id: {user.id},
                        email: "{user.email}",
                        first_name: "{user.first_name}",
                        last_name: "{user.last_name}",
                        role: "{user.role.value}",
                        is_verified: {str(user.is_verified).lower()},
                        is_oauth_user: true,
                        permissions: {json.dumps(permissions)}
                    }}
                }};
                
                console.log('Authentication successful:', authData);
                
                if (window.opener && !window.opener.closed) {{
                    window.opener.postMessage({{ 
                        type: 'oauth_success', 
                        data: authData,
                        is_new_user: {str(is_new_user).lower()}
                    }}, "{settings.FRONTEND_URL}");
                    setTimeout(() => window.close(), 1000);
                }} else {{
                    localStorage.setItem('salonconnect_auth', JSON.stringify(authData));
                    setTimeout(() => {{
                        window.location.href = '{settings.FRONTEND_URL}/dashboard';
                    }}, 2000);
                }}
            </script>
            
            <p><small>Redirecting to application...</small></p>
        </div>
    </body>
    </html>
    """

def create_redirect_to_registration(google_user):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Account Not Found - Salon Connect</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            }}
            .container {{
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                text-align: center;
                max-width: 400px;
            }}
            .info {{
                color: #007bff;
                font-size: 48px;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="info">ℹ️</div>
            <h2>Account Not Found</h2>
            <p>We couldn't find an account for <strong>{google_user['email']}</strong>.</p>
            <p>Please register first to create your account.</p>
            <button onclick="window.location.href='/api/auth/google/register'" style="
                background: #007bff;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                margin: 10px;
            ">Register with Google</button>
            <p><small>You'll be able to choose your account type during registration.</small></p>
        </div>
    </body>
    </html>
    """

def create_error_html(error_message):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Error - Salon Connect</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            }}
            .container {{
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10
            }}

            .error {{
                color: #dc3545;
                font-size: 48px;
                margin-bottom: 20px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error">Error</div>
            <h2>Authentication Failed</h2>
            <p><strong>Error:</strong> {error_message}</p>
            <button onclick="window.close()" style="
                background: #dc3545;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                cursor: pointer;
                margin-top: 20px;
            ">Close Window</button>
        </div>
    </body>
    </html>
    """            

# Test endpoints
@router.get("/test-oauth", tags=["Google OAuth"])
async def test_oauth_config():
    return {
        "google_configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "admin_emails": settings.get_admin_emails_list(),
        "endpoints": {
            "login": "/api/auth/google/login",
            "register": "/api/auth/google/register", 
            "callback": "/api/auth/google/callback"
        }
    }

@router.get("/debug-session", tags=["Google OAuth"])
async def debug_session(request: Request):
    """Debug session state"""
    session_data = {
        "session_exists": hasattr(request, 'session'),
        "session_keys": list(request.session.keys()) if hasattr(request, 'session') else [],
        "oauth_state": request.session.get('oauth_state') if hasattr(request, 'session') else None,
        "oauth_timestamp": request.session.get('oauth_timestamp') if hasattr(request, 'session') else None,
        "oauth_purpose": request.session.get('oauth_purpose') if hasattr(request, 'session') else None,
        "pending_google_user": bool(request.session.get('pending_google_user')),
        "oauth_temp_id": request.session.get('oauth_temp_id')
    }
    return session_data
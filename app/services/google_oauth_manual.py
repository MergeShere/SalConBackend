from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from app.core.config import settings
import secrets
import time
import httpx
import json

class GoogleOAuthManualService:
    def __init__(self):
        self.setup_oauth()
    
    def setup_oauth(self):
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            print("Google OAuth credentials not configured")
            return False
        print("Google OAuth configured successfully")
        return True
    
    async def start_oauth(self, request: Request, is_registration: bool = False):
        try:
            if not settings.GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=500, detail="Google OAuth not configured")
            
            state = secrets.token_urlsafe(32)
            request.session['oauth_state'] = state
            request.session['oauth_timestamp'] = time.time()
            request.session['oauth_purpose'] = 'registration' if is_registration else 'login'
            
            print(f"Generated state: {state}")
            print(f"OAuth purpose: {'registration' if is_registration else 'login'}")
            
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
            
            print(f"Redirecting to Google OAuth")
            return auth_url
            
        except Exception as e:
            print(f"Error starting OAuth: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start OAuth: {str(e)}")
    
    async def handle_callback(self, request: Request):
        try:
            print("=== Processing OAuth Callback ===")
            print(f"Callback URL: {request.url}")
            
            query_params = dict(request.query_params)
            print(f"Query parameters: {query_params}")
            
            error = query_params.get('error')
            if error:
                error_description = query_params.get('error_description', 'No description')
                print(f"Google OAuth error: {error} - {error_description}")
                raise HTTPException(status_code=400, detail=f"Google OAuth error: {error_description}")
            
            code = query_params.get('code')
            incoming_state = query_params.get('state')
            
            print(f"Authorization code received: {bool(code)}")
            print(f"State parameter received: {incoming_state}")
            
            if not code:
                raise HTTPException(status_code=400, detail="No authorization code received from Google")
            
            if not incoming_state:
                raise HTTPException(status_code=400, detail="No state parameter received from Google")
            
            stored_state = request.session.get('oauth_state')
            stored_timestamp = request.session.get('oauth_timestamp')
            oauth_purpose = request.session.get('oauth_purpose', 'login')
            
            print(f"Stored state: {stored_state}")
            print(f"State match: {stored_state == incoming_state}")
            
            if not stored_state:
                raise HTTPException(status_code=400, detail="Session expired. No state found in session.")
            
            if stored_state != incoming_state:
                raise HTTPException(status_code=400, detail="Security verification failed. Session may have expired.")
            
            if stored_timestamp and (time.time() - stored_timestamp) > 600:
                raise HTTPException(status_code=400, detail="Session expired. Please try again.")
            
            print("State verification successful")
            
            # Manual token exchange
            print("Exchanging authorization code for access token...")
            
            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                'client_id': settings.GOOGLE_CLIENT_ID,
                'client_secret': settings.GOOGLE_CLIENT_SECRET,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': settings.GOOGLE_REDIRECT_URI,
            }
            
            async with httpx.AsyncClient() as client:
                token_response = await client.post(token_url, data=token_data)
                
                print(f"Token response status: {token_response.status_code}")
                
                if token_response.status_code != 200:
                    print(f"Token exchange failed: {token_response.text}")
                    raise HTTPException(status_code=400, detail="Failed to exchange authorization code for token")
                
                token_result = token_response.json()
                access_token = token_result.get('access_token')
                print("Access token received successfully")
            
            # Get user info
            userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
            async with httpx.AsyncClient() as client:
                userinfo_response = await client.get(
                    userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                print(f"Userinfo response status: {userinfo_response.status_code}")
                
                if userinfo_response.status_code != 200:
                    raise HTTPException(status_code=400, detail="Failed to get user information")
                
                user_info = userinfo_response.json()
                print(f"User info received: {user_info.get('email')}")
            
            # Clean up session
            if 'oauth_state' in request.session:
                del request.session['oauth_state']
            if 'oauth_timestamp' in request.session:
                del request.session['oauth_timestamp']
            
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
            
            return google_user_data, oauth_purpose
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"OAuth callback error: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")

google_oauth_manual = GoogleOAuthManualService()
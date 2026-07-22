from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from app.core.config import settings
import secrets
import time
import httpx
import json

oauth = OAuth()

class GoogleOAuthService:
    def __init__(self):
        self.setup_oauth()
    
    def setup_oauth(self):
        try:
            if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
                print("Google OAuth credentials not configured")
                return
            
            oauth.register(
                name='google',
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                client_kwargs={
                    'scope': 'email profile openid',
                    'redirect_uri': settings.GOOGLE_REDIRECT_URI
                }
            )
            print("Google OAuth configured successfully")
        except Exception as e:
            print(f"Failed to setup Google OAuth: {e}")
    
    async def get_authorization_url(self, request: Request, is_registration: bool = False):
        try:
            if not settings.GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=500, detail="Google OAuth not configured")
            
            state = secrets.token_urlsafe(32)
            request.session['oauth_state'] = state
            request.session['oauth_timestamp'] = time.time()
            request.session['oauth_purpose'] = 'registration' if is_registration else 'login'
            
            print(f"Generated OAuth state: {state}")
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
            
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=auth_url)
            
        except Exception as e:
            print(f"Error generating authorization URL: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start OAuth: {str(e)}")
    
    async def handle_callback(self, request: Request):
        try:
            print("Processing OAuth callback")
            print(f"Callback URL: {request.url}")
            
            query_params = dict(request.query_params)
            print(f"Query parameters: {query_params}")
            
            error = query_params.get('error')
            if error:
                error_description = query_params.get('error_description', 'No description')
                print(f"Google OAuth error: {error} - {error_description}")
                raise HTTPException(status_code=400, detail=f"Google OAuth error: {error_description}")
            
            code = query_params.get('code')
            state = query_params.get('state')
            
            print(f"Authorization code present: {bool(code)}")
            print(f"State parameter present: {bool(state)}")
            
            if not code:
                print("No authorization code received from Google")
                raise HTTPException(status_code=400, detail="No authorization code received. Please try again.")
            
            if not state:
                print("No state parameter received from Google")
                raise HTTPException(status_code=400, detail="Security verification failed. Please try again.")
            
            stored_state = request.session.get('oauth_state')
            stored_timestamp = request.session.get('oauth_timestamp')
            oauth_purpose = request.session.get('oauth_purpose', 'login')
            
            print(f"Stored state: {stored_state}")
            print(f"OAuth purpose: {oauth_purpose}")
            
            if not stored_state or stored_state != state:
                print(f"State mismatch: stored={stored_state}, received={state}")
                raise HTTPException(status_code=400, detail="Session expired. Please try again.")
            
            if stored_timestamp and (time.time() - stored_timestamp) > 600:
                raise HTTPException(status_code=400, detail="Session expired")
            
            print("State verification passed, exchanging code for token")
            
            token = await oauth.google.authorize_access_token(request)
            user_info = token.get('userinfo')
            
            if not user_info:
                raise HTTPException(status_code=400, detail="Failed to get user information from Google")
            
            print(f"User authenticated: {user_info.email}")
            
            google_user_data = {
                'email': user_info.email,
                'first_name': user_info.given_name or '',
                'last_name': user_info.family_name or '',
                'picture': user_info.picture or '',
                'google_id': user_info.sub,
                'email_verified': user_info.email_verified or False
            }
            
            # Store Google user data in session for registration flow
            if oauth_purpose == 'registration':
                request.session['pending_google_user'] = google_user_data
                request.session['oauth_temp_id'] = secrets.token_urlsafe(16)
            
            # Clean up session
            if 'oauth_state' in request.session:
                del request.session['oauth_state']
            if 'oauth_timestamp' in request.session:
                del request.session['oauth_timestamp']
            if 'oauth_purpose' in request.session:
                del request.session['oauth_purpose']
            
            return google_user_data, oauth_purpose
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"OAuth callback error: {e}")
            raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")

google_oauth_service = GoogleOAuthService()
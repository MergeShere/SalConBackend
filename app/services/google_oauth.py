from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from app.core.config import settings
import secrets
import time
import httpx

oauth = OAuth()

def setup_google_oauth():
    try:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            print("Google OAuth credentials not found")
            return False
            
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
        print(f"Redirect URI: {settings.GOOGLE_REDIRECT_URI}")
        return True
    except Exception as e:
        print(f"Failed to setup Google OAuth: {e}")
        return False

oauth_configured = setup_google_oauth()

class GoogleOAuthService:
    @staticmethod
    async def get_authorization_url(request: Request):
        try:
            if not oauth_configured:
                raise HTTPException(status_code=500, detail="Google OAuth not configured properly")
            
            state = secrets.token_urlsafe(32)
            nonce = secrets.token_urlsafe(32)
            
            request.session['oauth_state'] = state
            request.session['oauth_timestamp'] = time.time()
            
            print(f"Generated state: {state}")
            print(f"Redirect URI: {settings.GOOGLE_REDIRECT_URI}")
            
            auth_url = (
                "https://accounts.google.com/o/oauth2/v2/auth?"
                f"client_id={settings.GOOGLE_CLIENT_ID}&"
                f"redirect_uri={settings.GOOGLE_REDIRECT_URI}&"
                "response_type=code&"
                "scope=email%20profile%20openid&"
                f"state={state}&"
                f"nonce={nonce}&"
                "access_type=offline&"
                "prompt=select_account"
            )
            
            print(f"OAuth URL generated")
            
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=auth_url)
            
        except Exception as e:
            print(f"Error generating authorization URL: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start OAuth: {str(e)}")

    @staticmethod
    async def handle_callback(request: Request):
        try:
            print("Processing OAuth callback")
            print(f"Callback URL: {request.url}")
            print(f"Query parameters: {dict(request.query_params)}")
            
            error = request.query_params.get('error')
            if error:
                error_description = request.query_params.get('error_description', 'No description')
                print(f"OAuth error from Google: {error} - {error_description}")
                raise HTTPException(status_code=400, detail=f"Google OAuth error: {error_description}")
            
            code = request.query_params.get('code')
            incoming_state = request.query_params.get('state')
            
            print(f"Incoming state from Google: {incoming_state}")
            print(f"Authorization code from Google: {code}")
            
            if not code and not incoming_state:
                print("No authorization code or state received from Google")
                raise HTTPException(
                    status_code=400, 
                    detail="No authorization data received from Google. Check your OAuth configuration."
                )
            
            if not code:
                raise HTTPException(status_code=400, detail="No authorization code received from Google")
            
            if not incoming_state:
                raise HTTPException(status_code=400, detail="No state parameter received from Google")
            
            stored_state = request.session.get('oauth_state')
            stored_timestamp = request.session.get('oauth_timestamp')
            
            print(f"Stored state from session: {stored_state}")
            
            if not stored_state:
                raise HTTPException(status_code=400, detail="No OAuth session found. Please start login again.")
            
            if incoming_state != stored_state:
                print(f"State mismatch: Incoming: {incoming_state}, Stored: {stored_state}")
                raise HTTPException(status_code=400, detail="Security verification failed")
            
            if stored_timestamp and (time.time() - stored_timestamp) > 600:
                raise HTTPException(status_code=400, detail="Session expired")
            
            print("State verification passed")
            
            print("Exchanging authorization code for access token")
            
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
                    print(f"Token exchange failed: {token_response.text}")
                    raise HTTPException(status_code=400, detail="Failed to exchange authorization code for token")
                
                token_data = token_response.json()
                print("Access token received")
            
            async with httpx.AsyncClient() as client:
                userinfo_response = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {token_data['access_token']}"}
                )
                
                if userinfo_response.status_code != 200:
                    raise HTTPException(status_code=400, detail="Failed to get user information")
                
                user_info = userinfo_response.json()
                print(f"User info received: {user_info['email']}")
            
            if 'oauth_state' in request.session:
                del request.session['oauth_state']
            if 'oauth_timestamp' in request.session:
                del request.session['oauth_timestamp']
            
            return {
                'email': user_info['email'],
                'first_name': user_info.get('given_name', ''),
                'last_name': user_info.get('family_name', ''),
                'picture': user_info.get('picture', ''),
                'google_id': user_info['sub'],
                'email_verified': user_info.get('email_verified', False)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"OAuth callback error: {e}")
            raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")
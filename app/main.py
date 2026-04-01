from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from starlette.middleware.sessions import SessionMiddleware
import os
import asyncio
import httpx
from app.routes import auth, users, salons, bookings, payments, vendor, favorites, google_oauth, kyc
from app.routes import admin as admin_router
from app.routes import ai_routes
from app.core.config import settings

async def keep_alive():
    if not settings.IS_PRODUCTION:
        return
        
    await asyncio.sleep(30)
    while True:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                endpoints = [
                    f"{settings.CURRENT_BASE_URL}/health",
                    f"{settings.CURRENT_BASE_URL}/",
                    f"{settings.CURRENT_BASE_URL}/ping"
                ]
                for endpoint in endpoints:
                    try:
                        response = await client.get(endpoint)
                        print(f" Keep-alive ping to {endpoint} - Status: {response.status_code}")
                        break
                    except Exception as e:
                        print(f" Ping failed for {endpoint}: {e}")
                        continue
        except Exception as e:
            print(f"Keep-alive ping failed: {e}")
        await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(" Salon Connect API Starting...")
    
    # Start keep-alive only in production
    if settings.IS_PRODUCTION:
        print(" Starting production keep-alive service...")
        keep_alive_task = asyncio.create_task(keep_alive())
        yield
        keep_alive_task.cancel()
    else:
        print(" Development mode - no keep-alive")
        yield

app = FastAPI(
    title="Salon Connect API",
    description="A platform connecting salons with customers",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Session middleware for OAuth - Enhanced configuration
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="salonconnect_session",
    max_age=3600,  
    same_site="lax",
    https_only=settings.IS_PRODUCTION,
    domain=None,  
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "https://saloonconnect.vercel.app",
        settings.FRONTEND_URL.rstrip("/"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/users", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(google_oauth.router, prefix="/api/auth", tags=["Google OAuth"])
app.include_router(salons.router, prefix="/api/salons", tags=["Salons"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["Bookings"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
app.include_router(vendor.router, prefix="/api/vendor", tags=["Vendor Management"])
app.include_router(favorites.router, prefix="/api/users", tags=["Favorites"])
app.include_router(kyc.router, prefix="/api/kyc", tags=["Identity Verification"])
app.include_router(admin_router.router, prefix="/api/admin", tags=["Admin"])
app.include_router(ai_routes.router, prefix="/api/ai", tags=["AI Automation"])

@app.get("/")
async def root():
    return {
        "message": "Welcome to Salon Connect API", 
        "status": "healthy",
        "version": "1.0.0",
        "environment": "production" if settings.IS_PRODUCTION else "development"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "message": "Salon Connect API is running",
        "environment": "production" if settings.IS_PRODUCTION else "development"
    }

@app.get("/ping")
async def ping():
    return {"message": "ping"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=not settings.IS_PRODUCTION)
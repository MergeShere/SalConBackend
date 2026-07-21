import os
import logging
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import List

load_dotenv()

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # App
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fallback-secret-key-for-development")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440").split()[0])
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

    # Paystack
    PAYSTACK_SECRET_KEY: str = os.getenv("PAYSTACK_SECRET_KEY", "")
    PAYSTACK_PUBLIC_KEY: str = os.getenv("PAYSTACK_PUBLIC_KEY", "")
    PAYSTACK_BASE_URL: str = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

    # Email provider selection: "resend" or "sendgrid" (default)
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "sendgrid").lower()

    # Resend
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")

    # SendGrid
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    FROM_EMAIL: str = os.getenv(
        "FROM_EMAIL",
        os.getenv("SENDGRID_FROM_EMAIL", "anane365221@gmail.com")
    )
    SENDGRID_FROM_NAME: str = os.getenv("SENDGRID_FROM_NAME", "Salon Connect")
    SENDGRID_REPLY_TO: str = os.getenv("SENDGRID_REPLY_TO", "")

    # SMTP (fallback email transport)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", os.getenv("SMTP_PASS", ""))
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "Salon Connect")

    # URLs
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://saloonconnect.vercel.app")
    BACKEND_URL: str = os.getenv("BACKEND_URL", "https://salonconnect-qzne.onrender.com")

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # Render
    RENDER_EXTERNAL_URL: str = os.getenv("RENDER_EXTERNAL_URL", "")
    RENDER: bool = os.getenv("RENDER", "False").lower() == "true"

    # AWS
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")

    # KYC (legacy OCR)
    KYC_REQUIRED: bool = os.getenv("KYC_REQUIRED", "True").lower() == "true"
    FACE_MATCHING_THRESHOLD: float = float(os.getenv("FACE_MATCHING_THRESHOLD", "0.75"))
    OCR_SERVICE_URL: str = os.getenv("OCR_SERVICE_URL", "https://api.ocr.space/parse/image")
    OCR_API_KEY: str = os.getenv("OCR_API_KEY", "helloworld")

    # MetaMap (Mati) KYC
    METAMAP_CLIENT_ID: str = os.getenv("METAMAP_CLIENT_ID", "")
    METAMAP_CLIENT_SECRET: str = os.getenv("METAMAP_CLIENT_SECRET", "")
    METAMAP_MERCHANT_ID: str = os.getenv("METAMAP_MERCHANT_ID", "")
    METAMAP_FLOW_ID: str = os.getenv("METAMAP_FLOW_ID", "")
    METAMAP_WEBHOOK_SECRET: str = os.getenv("METAMAP_WEBHOOK_SECRET", "")
    METAMAP_BASE_URL: str = "https://api.metamap.com"

    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

    # Anthropic AI
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    TWILIO_API_KEY: str = os.getenv("TWILIO_API_KEY", "")
    TWILIO_API_SECRET: str = os.getenv("TWILIO_API_SECRET", "")
    TWILIO_VERIFY_SERVICE_SID: str = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")

    # Subscription
    TRIAL_DAYS: int = 30
    SUBSCRIPTION_MONTHLY_AMOUNT_GHS: float = 50.0

    # Admin
    ADMIN_EMAILS: str = os.getenv("ADMIN_EMAILS", "anane365221@gmail.com")

    @property
    def IS_PRODUCTION(self):
        return self.RENDER or bool(self.RENDER_EXTERNAL_URL)

    @property
    def CURRENT_BASE_URL(self):
        if self.IS_PRODUCTION and self.RENDER_EXTERNAL_URL:
            return self.RENDER_EXTERNAL_URL.rstrip('/')
        return self.BACKEND_URL.rstrip('/')

    @property
    def GOOGLE_REDIRECT_URI(self):
        return f"{self.CURRENT_BASE_URL}/api/auth/google/callback"

    def get_admin_emails_list(self) -> List[str]:
        return [email.strip() for email in self.ADMIN_EMAILS.split(',') if email.strip()]

settings = Settings()

logger.info(
    "Environment=%s BackendURL=%s",
    "PRODUCTION" if settings.IS_PRODUCTION else "DEVELOPMENT",
    settings.CURRENT_BASE_URL,
)
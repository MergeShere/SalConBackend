import requests
import jwt
import random
import string
from datetime import datetime, timedelta
from app.core.config import settings
import os
import re
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def send_email(to_email: str, subject: str, html_content: str) -> bool:
        """Send email via the configured provider (EMAIL_PROVIDER: resend | sendgrid)"""
        if settings.EMAIL_PROVIDER == "resend":
            return EmailService._send_via_resend(to_email, subject, html_content)
        return EmailService._send_via_sendgrid(to_email, subject, html_content)

    @staticmethod
    def _send_via_resend(to_email: str, subject: str, html_content: str) -> bool:
        """Send email using the Resend API"""
        try:
            logger.info(f"[RESEND] Starting email send to: {to_email}")

            if not settings.RESEND_API_KEY:
                logger.error("[RESEND] Missing RESEND_API_KEY")
                return False

            if not settings.EMAIL_FROM:
                logger.error("[RESEND] Missing EMAIL_FROM")
                return False

            response = requests.post(
                "https://api.resend.com/emails",
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_content,
                    "text": EmailService._extract_plain_text(html_content),
                },
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

            if response.status_code in (200, 201):
                logger.info(f"[RESEND] Email sent successfully! id={response.json().get('id')}")
                return True

            logger.error(f"[RESEND] Failed to send email. Status: {response.status_code} Body: {response.text}")
            return False

        except requests.exceptions.Timeout:
            logger.warning("[RESEND] Request timeout")
            return False
        except Exception as e:
            logger.error(f"[RESEND] Error sending email: {str(e)}")
            return False

    @staticmethod
    def _send_via_sendgrid(to_email: str, subject: str, html_content: str) -> bool:
        """Send email using SendGrid API with comprehensive anti-spam measures"""
        try:
            logger.info(f"[SENDGRID] Starting email send to: {to_email}")
            # Validate required configurations
            if not settings.SENDGRID_API_KEY:
                logger.error("[SENDGRID] Missing SENDGRID_API_KEY")
                return False
                
            if not settings.FROM_EMAIL:
                logger.error("[SENDGRID] Missing FROM_EMAIL")
                return False

            # Extract domain for headers
            from_domain = settings.FROM_EMAIL.split('@')[1] if '@' in settings.FROM_EMAIL else "salonconnect.com"
            
            # Prepare headers with better email deliverability settings
            headers = {
                "Authorization": f"Bearer {settings.SENDGRID_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "SalonConnect-API/1.0"
            }
            
            # Prepare email data with improved deliverability settings
            data = {
                "personalizations": [{
                    "to": [{"email": to_email}],
                    "subject": subject,
                    "headers": {
                        "X-Priority": "3",  # Normal priority instead of High
                        "X-MSMail-Priority": "Normal",
                        "Importance": "normal",
                        "X-Mailer": "SalonConnect",
                        "List-Unsubscribe": f"<mailto:unsubscribe@{from_domain}?subject=unsubscribe>, <{settings.FRONTEND_URL}/unsubscribe>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                        "Precedence": "bulk",
                        "X-Entity-Ref": f"salon-connect-{datetime.now().strftime('%Y%m%d')}",
                        "X-Report-Abuse": f"Please report abuse to {settings.FROM_EMAIL}",
                        "X-Auto-Response-Suppress": "All",  # Prevent auto-replies
                        "Auto-Submitted": "auto-generated"  # Mark as transactional
                    }
                }],
                "from": {
                    "email": settings.FROM_EMAIL,
                    "name": "Salon Connect"
                },
                "reply_to": {
                    "email": settings.FROM_EMAIL,
                    "name": "Salon Connect Support"
                },
                "subject": subject,
                "content": [
                    {
                        "type": "text/plain",
                        "value": EmailService._extract_plain_text(html_content)
                    },
                    {
                        "type": "text/html",
                        "value": html_content
                    }
                ],
                "mail_settings": {
                    "bypass_list_management": {"enable": False},
                    "footer": {
                        "enable": True,
                        "text": "This is a transactional email from Salon Connect.",
                        "html": "<p>This is a transactional email from Salon Connect.</p>"
                    },
                    "sandbox_mode": {"enable": False},
                    "spam_check": {"enable": False}
                },
                "tracking_settings": {
                    "click_tracking": {"enable": True},
                    "open_tracking": {"enable": True},
                    "subscription_tracking": {"enable": False}
                },
                "categories": ["transactional", "salon_connect", "account_notifications"],
                "custom_args": {
                    "app_name": "Salon Connect",
                    "email_type": "transactional",
                    "timestamp": str(datetime.utcnow().timestamp())
                }
            }
            
            logger.info(f"[SENDGRID] Sending email via SendGrid API...")
            response = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 202:
                logger.info(f"[SENDGRID] Email sent successfully! Status: {response.status_code}")
                return True
            else:
                logger.error(f"[SENDGRID] Failed to send email. Status: {response.status_code}")
                try:
                    error_response = response.json()
                    logger.error(f"[SENDGRID] Error details: {error_response}")
                except:
                    logger.error(f"[SENDGRID] Error text: {response.text}")
                return False
            
        except requests.exceptions.Timeout:
            logger.warning(f"[SENDGRID] Request timeout")
            return False
        except Exception as e:
            logger.error(f"[SENDGRID] Error sending email: {str(e)}")
            return False

    @staticmethod
    def _extract_plain_text(html_content: str) -> str:
        """Extract plain text from HTML content for better deliverability"""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Replace HTML entities
        html_entities = {
            '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
            '&#13;': '\n', '&#10;': '\n', '&quot;': '"', '&apos;': "'"
        }
        for entity, replacement in html_entities.items():
            text = text.replace(entity, replacement)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove excessive line breaks
        text = re.sub(r'\n\s*\n+', '\n\n', text.strip())
        
        return text

    @staticmethod
    def _create_base_template(content: str, user_email: str, subject: str) -> str:
        """Create base email template"""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="format-detection" content="telephone=no">
    <meta name="format-detection" content="date=no">
    <meta name="format-detection" content="address=no">
    <meta name="format-detection" content="email=no">
    <title>{subject}</title>
    <style>
        body, html {{ margin: 0; padding: 0; font-family: 'Arial', 'Helvetica Neue', Helvetica, sans-serif; line-height: 1.6; color: #333; background-color: #f6f9fc; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px 30px; text-align: center; }}
        .content {{ padding: 40px 30px; }}
        .footer {{ padding: 30px; text-align: center; color: #666; font-size: 12px; background: #f8f9fa; }}
        .button {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 16px 40px; text-decoration: none; border-radius: 8px; display: inline-block; margin: 20px 0; font-weight: 600; font-size: 16px; }}
        .text-center {{ text-align: center; }}
        .legal {{ font-size: 11px; color: #999; margin-top: 20px; border-top: 1px solid #eee; padding-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 32px; font-weight: 700;">Salon Connect</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">Professional Beauty & Wellness Services</p>
        </div>
        <div class="content">
            {content}
        </div>
        <div class="footer">
            <p style="margin: 0 0 10px 0;">© 2024 Salon Connect. All rights reserved.</p>
            <div class="legal">
                <p style="margin: 0 0 5px 0;">This email was sent to {user_email} because you have an account with Salon Connect.</p>
                <p style="margin: 0 0 5px 0;">
                    <a href="{settings.FRONTEND_URL}/unsubscribe" style="color: #666;">Unsubscribe</a> | 
                    <a href="{settings.FRONTEND_URL}/privacy" style="color: #666;">Privacy Policy</a> | 
                    <a href="{settings.FRONTEND_URL}/support" style="color: #666;">Support</a>
                </p>
            </div>
        </div>
    </div>
</body>
</html>"""

    @staticmethod
    def send_verification_email(email: str, first_name: str, verification_url: str) -> bool:
        """Send email verification email - USING USERNAME NOT PHONE"""
        try:
            subject = "Verify Your Salon Connect Account"
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">Welcome to Salon Connect, {first_name}!</h2>
            <p>Thank you for choosing Salon Connect. We're excited to have you on board!</p>
            
            <div style="background: #e7f3ff; border-radius: 8px; padding: 20px; margin: 25px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Complete Your Registration</h3>
                <p>To activate your account, please verify your email address:</p>
            </div>
            
            <div class="text-center">
                <a href="{verification_url}" class="button" style="color: white; text-decoration: none;">
                    Verify Email Address
                </a>
            </div>
            
            <div style="background: #fff3cd; border-radius: 8px; padding: 15px; margin: 20px 0;">
                <strong>Important:</strong> This link expires in 24 hours.
            </div>
            
            <p style="color: #666; font-size: 14px;">
                If the button doesn't work, copy and paste this link into your browser:<br>
                <span style="word-break: break-all; background: #f8f9fa; padding: 10px; border-radius: 4px; display: block; margin-top: 10px;">
                    {verification_url}
                </span>
            </p>
            
            <div style="background: #f8d7da; border-radius: 8px; padding: 15px; margin: 20px 0; color: #721c24;">
                <strong>Email Tip:</strong> Add <strong>{settings.FROM_EMAIL}</strong> to your contacts to ensure delivery.
            </div>
            
            <p style="color: #666; font-size: 14px;">
                If you didn't create this account, please ignore this email.
            </p>
            """
            
            html_content = EmailService._create_base_template(content, email, subject)
            logger.info(f"[SENDGRID] Sending verification email to: {email}")
            return EmailService.send_email(email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending verification email: {str(e)}")
            return False

    @staticmethod
    def send_password_reset_email(email: str, first_name: str, reset_url: str) -> bool:
        """Send password reset email - USING USERNAME NOT PHONE"""
        try:
            subject = "Reset Your Salon Connect Password"
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">Password Reset Request</h2>
            <p>Hello {first_name},</p>
            
            <div style="background: #fff3cd; border-radius: 8px; padding: 20px; margin: 25px 0;">
                <p style="margin: 0;">We received a request to reset your password.</p>
            </div>
            
            <div class="text-center">
                <a href="{reset_url}" class="button" style="color: white; text-decoration: none;">
                    Reset Password
                </a>
            </div>
            
            <div style="background: #fff3cd; border-radius: 8px; padding: 15px; margin: 20px 0;">
                <strong>Security Notice:</strong> This link expires in 1 hour.
            </div>
            
            <p style="color: #666; font-size: 14px;">
                If you didn't request this password reset, please ignore this email or contact support if you're concerned about your account's security.
            </p>
            
            <p style="color: #666; font-size: 14px;">
                If the button doesn't work, copy and paste this link into your browser:<br>
                <span style="word-break: break-all; background: #f8f9fa; padding: 10px; border-radius: 4px; display: block; margin-top: 10px;">
                    {reset_url}
                </span>
            </p>
            """
            
            html_content = EmailService._create_base_template(content, email, subject)
            logger.info(f"[SENDGRID] Sending password reset email to: {email}")
            return EmailService.send_email(email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending password reset email: {str(e)}")
            return False

    @staticmethod
    def send_otp_email(email: str, first_name: str, otp: str) -> bool:
        """Send OTP for login - USING USERNAME NOT PHONE"""
        try:
            subject = "Your Salon Connect Verification Code"
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">Login Verification</h2>
            <p>Hello {first_name},</p>
            
            <div style="background: #e7f3ff; border-radius: 8px; padding: 20px; margin: 25px 0;">
                <p style="margin-bottom: 15px;">Use this verification code to complete your login:</p>
            </div>
            
            <div style="background: #2c3e50; color: white; padding: 25px; font-size: 36px; font-weight: bold; text-align: center; letter-spacing: 10px; margin: 25px 0; border-radius: 8px; font-family: 'Courier New', monospace;">
                {otp}
            </div>
            
            <div style="background: #fff3cd; border-radius: 8px; padding: 15px; margin: 20px 0;">
                <strong>Security Information:</strong> This code expires in 10 minutes.
            </div>
            
            <div style="background: #f8d7da; border-radius: 8px; padding: 15px; margin: 20px 0; color: #721c24;">
                <strong>Important:</strong> Never share this code with anyone. Salon Connect will never ask for it.
            </div>
            
            <p style="color: #666; font-size: 14px;">
                If you didn't request this login, please secure your account immediately.
            </p>
            """
            
            html_content = EmailService._create_base_template(content, email, subject)
            logger.info(f"[SENDGRID] Sending OTP email to: {email}")
            return EmailService.send_email(email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending OTP email: {str(e)}")
            return False

    @staticmethod
    def send_booking_confirmation(customer_email: str, customer_name: str, booking: Dict[str, Any], salon: Dict[str, Any]) -> bool:
        """Send booking confirmation email to customer"""
        try:
            subject = "Booking Confirmation - Salon Connect"
            
            # Format booking date
            booking_date = booking.get('booking_date', 'Unknown date')
            if isinstance(booking_date, datetime):
                booking_date = booking_date.strftime("%B %d, %Y at %I:%M %p")
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">Booking Confirmed! 🎉</h2>
            <p>Hello {customer_name},</p>
            <p>Your booking has been successfully confirmed.</p>
            
            <div style="background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 20px; margin: 25px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Booking Details</h3>
                <p><strong>Salon:</strong> {salon.get('name', 'Unknown Salon')}</p>
                <p><strong>Date & Time:</strong> {booking_date}</p>
                <p><strong>Booking ID:</strong> #{booking.get('id', 'N/A')}</p>
                <p><strong>Total Amount:</strong> GH₵{booking.get('total_amount', 0):,.2f}</p>
                <p><strong>Status:</strong> Confirmed</p>
            </div>
            
            <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <strong>📍 Salon Address:</strong><br>
                {salon.get('address', 'Address not available')}<br>
                <strong>📞 Contact:</strong> {salon.get('phone_number', 'N/A')}
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <strong>📝 Reminder:</strong> Please arrive 10 minutes before your appointment time.
            </div>
            
            <p>Thank you for choosing Salon Connect! We look forward to serving you.</p>
            """
            
            html_content = EmailService._create_base_template(content, customer_email, subject)
            logger.info(f"[SENDGRID] Sending booking confirmation to: {customer_email}")
            return EmailService.send_email(customer_email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending booking confirmation: {str(e)}")
            return False

    @staticmethod
    def send_booking_notification_to_vendor(vendor_email: str, vendor_name: str, booking: Dict[str, Any], customer: Dict[str, Any], salon: Dict[str, Any]) -> bool:
        """Send booking notification email to vendor"""
        try:
            subject = "New Booking Received - Salon Connect"
            
            # Format booking date
            booking_date = booking.get('booking_date', 'Unknown date')
            if isinstance(booking_date, datetime):
                booking_date = booking_date.strftime("%B %d, %Y at %I:%M %p")
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">New Booking Alert! 🔔</h2>
            <p>Hello {vendor_name},</p>
            <p>You have received a new booking for your salon.</p>
            
            <div style="background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 20px; margin: 25px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Booking Details</h3>
                <p><strong>Customer:</strong> {customer.get('first_name', '')} {customer.get('last_name', '')}</p>
                <p><strong>Customer Email:</strong> {customer.get('email', '')}</p>
                <p><strong>Customer Phone:</strong> {customer.get('phone_number', 'N/A')}</p>
                <p><strong>Salon:</strong> {salon.get('name', 'Your Salon')}</p>
                <p><strong>Booking Date:</strong> {booking_date}</p>
                <p><strong>Booking ID:</strong> #{booking.get('id', 'N/A')}</p>
                <p><strong>Total Amount:</strong> GH₵{booking.get('total_amount', 0):,.2f}</p>
            </div>
            
            <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>📋 Next Steps:</strong></p>
                <ol style="margin: 10px 0; padding-left: 20px;">
                    <li>Review the booking details</li>
                    <li>Confirm availability</li>
                    <li>Prepare for the appointment</li>
                </ol>
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>💡 Tip:</strong> Log in to your vendor dashboard to manage this booking and view all appointments.</p>
            </div>
            
            <p>Best regards,<br>The Salon Connect Team</p>
            """
            
            html_content = EmailService._create_base_template(content, vendor_email, subject)
            logger.info(f"[SENDGRID] Sending booking notification to vendor: {vendor_email}")
            return EmailService.send_email(vendor_email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending vendor notification: {str(e)}")
            return False

    @staticmethod
    def send_payment_confirmation(email: str, name: str, payment: Dict[str, Any], booking: Dict[str, Any]) -> bool:
        """Send payment confirmation email"""
        try:
            subject = "Payment Confirmed - Salon Connect"
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">Payment Confirmed! ✅</h2>
            <p>Hello {name},</p>
            <p>Your payment has been successfully processed.</p>
            
            <div style="background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 20px; margin: 25px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Payment Details</h3>
                <p><strong>Payment Reference:</strong> {payment.get('reference', 'N/A')}</p>
                <p><strong>Amount Paid:</strong> GH₵{payment.get('amount', 0):,.2f}</p>
                <p><strong>Booking ID:</strong> #{booking.get('id', 'N/A')}</p>
                <p><strong>Payment Method:</strong> {payment.get('payment_method', 'N/A')}</p>
                <p><strong>Transaction Date:</strong> {payment.get('paid_at', 'N/A')}</p>
                <p><strong>Status:</strong> Successful</p>
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>📋 Your Booking:</strong> #{booking.get('id', 'N/A')} is now confirmed and ready.</p>
            </div>
            
            <p>Thank you for your payment. We look forward to serving you!</p>
            
            <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>📞 Need Help?</strong> Contact our support team if you have any questions.</p>
            </div>
            """
            
            html_content = EmailService._create_base_template(content, email, subject)
            logger.info(f"[SENDGRID] Sending payment confirmation to: {email}")
            return EmailService.send_email(email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending payment confirmation: {str(e)}")
            return False

    @staticmethod
    def send_vendor_welcome_email(email: str, first_name: str, business_name: str, verification_url: str) -> bool:
        """Send vendor welcome email"""
        try:
            subject = "Welcome to Salon Connect - Business Account"
            
            content = f"""
            <h2 style="color: #2c3e50; margin-bottom: 20px;">Welcome to Salon Connect! 🏢</h2>
            <p>Hello {first_name},</p>
            <p>Thank you for registering your business, <strong>{business_name}</strong>, on Salon Connect!</p>
            
            <div style="background: #e8f5e9; border-left: 4px solid #4CAF50; padding: 20px; margin: 25px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">Get Started</h3>
                <p>First, please verify your email address to activate your business account:</p>
                
                <div class="text-center" style="margin: 20px 0;">
                    <a href="{verification_url}" class="button" style="color: white; text-decoration: none;">
                        Verify Business Email
                    </a>
                </div>
            </div>
            
            <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 25px 0;">
                <h3 style="margin-top: 0; color: #2c3e50;">What You Can Do:</h3>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>Create your salon profile</li>
                    <li>Add services and set prices</li>
                    <li>Manage your availability</li>
                    <li>Accept online bookings</li>
                    <li>Receive payments</li>
                    <li>Track your business analytics</li>
                </ul>
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>🎁 Special Offer:</strong> All new vendors start with a <strong>30-Day Free Trial</strong> of our premium features!</p>
            </div>
            
            <p>We're excited to help you grow your business!</p>
            <p>Best regards,<br>The Salon Connect Team</p>
            """
            
            html_content = EmailService._create_base_template(content, email, subject)
            logger.info(f"[SENDGRID] Sending vendor welcome email to: {email}")
            return EmailService.send_email(email, subject, html_content)
            
        except Exception as e:
            logger.error(f"Error sending vendor welcome email: {str(e)}")
            return False

    # Token Generation and Verification Methods
    @staticmethod
    def generate_verification_token(email: str) -> str:
        """Generate JWT token for email verification"""
        payload = {
            'email': email,
            'exp': datetime.utcnow() + timedelta(hours=24),
            'type': 'email_verification'
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        return token

    @staticmethod
    def generate_reset_token(email: str) -> str:
        """Generate JWT token for password reset"""
        payload = {
            'email': email,
            'exp': datetime.utcnow() + timedelta(hours=1),
            'type': 'password_reset'
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        return token

    @staticmethod
    def verify_token(token: str, token_type: str) -> Optional[Dict]:
        """Verify JWT token"""
        try:
            # Handle bytes token
            if isinstance(token, bytes):
                token = token.decode('utf-8')
            elif token.startswith("b'") and token.endswith("'"):
                token = token[2:-1]
            
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            if payload.get('type') != token_type:
                return None
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def verify_reset_token(token: str) -> Optional[Dict]:
        """Verify password reset token"""
        return EmailService.verify_token(token, 'password_reset')

    @staticmethod
    def generate_otp() -> str:
        """Generate 6-digit OTP"""
        return ''.join(random.choices(string.digits, k=6))

    # Helper method for backward compatibility
    @staticmethod
    def send_verification_email_legacy(user, verification_url: str) -> bool:
        """Legacy method for backward compatibility"""
        email = getattr(user, 'email', '')
        first_name = getattr(user, 'first_name', 'there')
        return EmailService.send_verification_email(email, first_name, verification_url)

    @staticmethod
    def send_password_reset_email_legacy(user, reset_url: str) -> bool:
        """Legacy method for backward compatibility"""
        email = getattr(user, 'email', '')
        first_name = getattr(user, 'first_name', 'there')
        return EmailService.send_password_reset_email(email, first_name, reset_url)

    @staticmethod
    def send_otp_email_legacy(user, otp: str) -> bool:
        """Legacy method for backward compatibility"""
        email = getattr(user, 'email', '')
        first_name = getattr(user, 'first_name', 'there')
        return EmailService.send_otp_email(email, first_name, otp)
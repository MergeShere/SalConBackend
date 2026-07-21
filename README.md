# Salon Connect API

A FastAPI-based salon booking marketplace backend. Customers discover salons and book multi-service appointments, vendors manage their salon profile and analytics, and admins verify vendor identity via KYC with AI face matching.

---

## Live Deployments

- Primary: https://salonconnect-qzne.onrender.com
- Swagger UI: https://salonconnect-qzne.onrender.com/docs
- Health check: https://salonconnect-qzne.onrender.com/health

---

## Features

- **Auth** — JWT access + refresh tokens, Google OAuth, role-based access (Customer, Vendor, Admin)
- **Salon discovery** — search with filters, featured listings, nearby by coordinates, reviews
- **Multi-service bookings** — real-time availability, booking lifecycle (Pending → Confirmed → Completed → Cancelled)
- **Payments** — Paystack integration: initiate, verify, webhook handling with signature verification
- **KYC / Identity verification** — two paths:
  - Legacy: document upload + OCR + DeepFace face matching
  - MetaMap: hosted SDK widget with Ghana card dedup and 30-day trial
- **Vendor dashboard** — revenue analytics, booking summaries, demand forecasting, customer churn risk
- **Admin panel** — user/vendor/salon/booking/payment management, KYC review, content moderation
- **AI automation** — Claude-powered salon recommendations, pricing suggestions, demand forecasts
- **File uploads** — images via Cloudinary; email via SendGrid

---

## Project Layout

```
app/
  main.py            # App factory, CORS/session middleware, router mounting
  database.py        # SQLAlchemy engine + session; falls back to SQLite if no DATABASE_URL
  core/
    config.py        # Pydantic Settings loaded from .env
    security.py      # JWT creation/verification, password hashing
    cloudinary.py    # Image upload utilities
    dependencies.py  # FastAPI DI: get_db, get_current_user, role checks
  models/            # SQLAlchemy ORM models (user, salon, booking, payment, kyc, vendor)
  schemas/           # Pydantic v2 request/response schemas
  routes/            # HTTP routers (auth, users, salons, bookings, payments, vendor, kyc, admin, ai_routes, google_oauth, favorites)
  services/          # Business logic (auth, booking, payment, salon, kyc, metamap, ai, email, paystack, google_oauth)
  utils/             # Shared validators/helpers
  templates/         # Jinja2 HTML (KYC portal)
alembic/             # DB migrations
```

---

## Installation & Setup

1. Clone the repository:
```bash
git clone git@github.com:doanane/SalonConnect.git
cd SalonConnect
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows
venv\Scripts\Activate.ps1
```

3. Install dependencies:
```bash
# Development (includes ML/CV stack for DeepFace KYC)
pip install -r requirements.txt

# Production (no ML stack)
pip install -r requirements-prod.txt
```

4. Create a `.env` in the project root (see Environment Variables below).

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the development server:
```bash
python run.py
# or
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Environment Variables

```env
SECRET_KEY=
DATABASE_URL=postgresql://...          # omit for SQLite fallback
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=
PAYSTACK_SECRET_KEY=
PAYSTACK_PUBLIC_KEY=
SENDGRID_API_KEY=
FROM_EMAIL=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
AWS_ACCESS_KEY_ID=                     # used for KYC/S3
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
ADMIN_EMAILS=admin@example.com
```

Without `DATABASE_URL`, the app falls back to SQLite (`salon_connect.db`) for zero-config local dev.

---

## API Overview

Authentication header for protected endpoints:
```
Authorization: Bearer <access_token>
```

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login and receive tokens |
| POST | `/api/auth/refresh` | Refresh access token |
| POST | `/api/auth/logout` | Logout |
| POST | `/api/auth/forgot-password` | Request password reset |
| POST | `/api/auth/reset-password` | Reset using token |
| GET | `/api/auth/google` | Google OAuth login |

### Users
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users/me` | Get current user |
| PUT | `/api/users/me/profile` | Update profile |
| GET | `/api/users/customer/dashboard` | Customer dashboard |

### Salons
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/salons/` | Browse salons (filters: city, rating, services) |
| GET | `/api/salons/featured` | Featured salons |
| GET | `/api/salons/nearby` | Nearby salons by coordinates |
| GET | `/api/salons/{salon_id}` | Salon detail |
| POST | `/api/salons/{salon_id}/reviews` | Create review (Customer) |

### Bookings
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/bookings/` | Create booking (multi-service) |
| GET | `/api/bookings/` | List user bookings |
| GET | `/api/bookings/{booking_id}` | Booking detail |
| PUT | `/api/bookings/{booking_id}` | Update booking |

### Payments
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/payments/initiate` | Start Paystack payment |
| POST | `/api/payments/verify` | Verify payment |
| GET | `/api/payments/{payment_id}` | Payment detail |
| POST | `/api/payments/webhook/paystack` | Paystack webhook |

### Vendor
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/vendor/salons` | Create salon |
| GET | `/api/vendor/salons` | List own salons |
| PUT | `/api/vendor/salons/{id}` | Update salon |
| GET | `/api/vendor/dashboard` | Revenue & booking analytics |

### KYC
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/kyc/status` | Current KYC status |
| POST | `/api/kyc/upload` | Upload documents (legacy) |
| GET | `/api/kyc/portal` | Legacy KYC portal (HTML) |
| POST | `/api/kyc/metamap/initiate` | Start MetaMap verification |
| POST | `/api/kyc/metamap/webhook` | MetaMap webhook |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/dashboard` | Platform overview |
| GET | `/api/admin/users` | User management |
| GET | `/api/admin/vendors` | Vendor management + KYC review |
| POST | `/api/admin/kyc/{id}/approve` | Approve vendor KYC |
| POST | `/api/admin/kyc/{id}/reject` | Reject vendor KYC |
| GET | `/api/admin/salons` | Salon management |
| GET | `/api/admin/bookings` | Booking management |
| GET | `/api/admin/payments` | Payment management |
| GET | `/api/admin/reports` | Platform analytics |
| DELETE | `/api/admin/reviews/{id}` | Remove review (moderation) |

### AI Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/ai/recommendations/salons` | AI salon recommendations (Customer) |
| GET | `/api/ai/pricing/suggestions` | Pricing suggestions (Vendor) |
| GET | `/api/ai/bookings/summary` | Booking summary (Vendor) |
| GET | `/api/ai/demand/forecast` | Demand forecast (Vendor) |
| GET | `/api/ai/customers/churn-risk` | Customer churn risk |

### Favorites
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users/favorites` | List favorites |
| POST | `/api/users/favorites/{salon_id}` | Add favorite |
| DELETE | `/api/users/favorites/{salon_id}` | Remove favorite |

---

## Quick curl Examples

Register a user:
```bash
curl -X POST "https://salonconnect-qzne.onrender.com/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123", "first_name": "John", "last_name": "Doe", "role": "customer"}'
```

Login:
```bash
curl -X POST "https://salonconnect-qzne.onrender.com/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'
```

Browse salons:
```bash
curl "https://salonconnect-qzne.onrender.com/api/salons/?city=Lagos&min_rating=4.0"
```

---

## Database Models

- **User & UserProfile** — identity, roles, authentication
- **Salon, Service, SalonImage, Review** — salon catalog and metadata
- **Booking & BookingItem** — master/detail booking records
- **Payment** — Paystack transactions with webhook state
- **VendorKYC & KYCAuditLog** — identity verification records and audit trail

---

## Deployment

Deployed on Render.com:
1. Push to GitHub and connect the repo in Render.
2. Set environment variables in the Render dashboard.
3. Use managed Postgres and run `alembic upgrade head` on deploy.
4. Production server: `gunicorn -c gunicorn.conf.py app.main:app`

`IS_PRODUCTION` is auto-detected from `RENDER=True` or `RENDER_EXTERNAL_URL` — controls HTTPS cookies and keep-alive behavior.

---

## Contributing

- Business logic goes in `services/`, exposed via thin route handlers in `routes/`, validated with Pydantic schemas in `schemas/`.
- Use Alembic migrations for all schema changes.
- Open a pull request with a clear description of the change.

---

## Contact

Email: anane365221@gmail.com

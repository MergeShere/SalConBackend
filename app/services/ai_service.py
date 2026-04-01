"""
AI automation service using Google Gemini.

Features:
  - Smart salon recommendations based on customer history and preferences
  - Review sentiment analysis
  - Automated vendor pricing suggestions
  - Booking demand forecasting
  - Fraud / suspicious activity detection
  - AI-generated booking summaries for vendors
  - Customer churn risk scoring
"""

import json
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent?key={key}"
)


class AIService:
    """Wrapper around the Gemini REST API for all AI automation tasks."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model = settings.GEMINI_MODEL or "gemini-1.5-flash-latest"

    # ------------------------------------------------------------------
    # Core helper
    # ------------------------------------------------------------------

    async def _generate(self, prompt: str, temperature: float = 0.4) -> str:
        """
        Send a prompt to Gemini and return the text response.
        Returns an empty string if the API key is not configured or the call fails.
        """
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured — AI features disabled")
            return ""

        url = GEMINI_API_URL.format(model=self.model, key=self.api_key)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 1024,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
        except Exception as exc:
            logger.error("Gemini API call failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # 1. Salon recommendations
    # ------------------------------------------------------------------

    async def get_salon_recommendations(
        self,
        customer_name: str,
        past_services: list[str],
        location: str,
        available_salons: list[dict],
    ) -> dict:
        """
        Rank and explain salon recommendations for a customer.

        available_salons should be a list of dicts with keys:
            name, city, services (list[str]), average_rating, total_reviews
        """
        salons_text = "\n".join(
            f"- {s['name']} ({s.get('city', '')}) | Rating: {s.get('average_rating', 'N/A')} "
            f"| Services: {', '.join(s.get('services', []))}"
            for s in available_salons[:20]
        )

        prompt = f"""
You are a beauty concierge AI for Salon Connect, a salon booking marketplace in Ghana.

Customer: {customer_name}
Location: {location}
Previously booked services: {', '.join(past_services) if past_services else 'None yet'}

Available salons:
{salons_text}

Based on the customer's history and location, recommend the top 3 salons with a short reason for each.
Return ONLY valid JSON in this format:
{{
  "recommendations": [
    {{"rank": 1, "salon_name": "...", "reason": "..."}},
    {{"rank": 2, "salon_name": "...", "reason": "..."}},
    {{"rank": 3, "salon_name": "...", "reason": "..."}}
  ]
}}
"""
        raw = await self._generate(prompt, temperature=0.3)
        try:
            # Strip possible markdown code fences
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)
        except Exception:
            return {"recommendations": [], "raw": raw}

    # ------------------------------------------------------------------
    # 2. Review sentiment analysis
    # ------------------------------------------------------------------

    async def analyze_review_sentiment(self, review_text: str) -> dict:
        """
        Classify a review as positive / neutral / negative and extract key topics.
        """
        prompt = f"""
Analyse this salon review and return ONLY valid JSON:
{{
  "sentiment": "positive" | "neutral" | "negative",
  "score": <float 0.0-1.0 where 1.0 is most positive>,
  "topics": ["..."],
  "summary": "one sentence"
}}

Review: "{review_text}"
"""
        raw = await self._generate(prompt, temperature=0.1)
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)
        except Exception:
            return {"sentiment": "neutral", "score": 0.5, "topics": [], "summary": "", "raw": raw}

    # ------------------------------------------------------------------
    # 3. Pricing suggestions
    # ------------------------------------------------------------------

    async def suggest_pricing(
        self,
        service_name: str,
        duration_minutes: int,
        city: str,
        current_price_ghs: float,
        competitor_prices: list[float],
    ) -> dict:
        """
        Suggest an optimal price for a service based on market data.
        """
        comp_text = (
            f"Competitor prices: GHS {', '.join(str(p) for p in competitor_prices)}"
            if competitor_prices
            else "No competitor data available."
        )

        prompt = f"""
You are a pricing analyst for a Ghanaian beauty salon marketplace.

Service: {service_name}
Duration: {duration_minutes} minutes
City: {city}
Current price: GHS {current_price_ghs}
{comp_text}

Suggest an optimal price and brief reasoning. Return ONLY valid JSON:
{{
  "suggested_price_ghs": <float>,
  "min_price_ghs": <float>,
  "max_price_ghs": <float>,
  "reasoning": "..."
}}
"""
        raw = await self._generate(prompt, temperature=0.2)
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)
        except Exception:
            return {
                "suggested_price_ghs": current_price_ghs,
                "reasoning": "AI suggestion unavailable",
                "raw": raw,
            }

    # ------------------------------------------------------------------
    # 4. Booking summary for vendor
    # ------------------------------------------------------------------

    async def generate_booking_summary(self, booking: dict) -> str:
        """
        Generate a human-readable summary of a booking for the vendor dashboard.
        booking dict keys: customer_name, services, booking_date, total_amount, special_requests
        """
        prompt = f"""
Write a short, professional 2-sentence booking summary for a salon owner.

Customer: {booking.get('customer_name')}
Services: {', '.join(booking.get('services', []))}
Date: {booking.get('booking_date')}
Total: GHS {booking.get('total_amount')}
Special requests: {booking.get('special_requests') or 'None'}

Keep it concise and factual.
"""
        return await self._generate(prompt, temperature=0.5)

    # ------------------------------------------------------------------
    # 5. Fraud / suspicious booking detection
    # ------------------------------------------------------------------

    async def assess_booking_risk(self, booking_data: dict) -> dict:
        """
        Score a new booking for fraud risk.

        booking_data keys:
            customer_age_days (account age), total_bookings_history,
            booking_amount_ghs, services, payment_method,
            bookings_last_24h (int)
        """
        prompt = f"""
You are a fraud detection system for an online salon booking platform in Ghana.

Booking details:
- Customer account age: {booking_data.get('customer_age_days', 0)} days
- Past bookings: {booking_data.get('total_bookings_history', 0)}
- Bookings in last 24h: {booking_data.get('bookings_last_24h', 0)}
- Amount: GHS {booking_data.get('booking_amount_ghs', 0)}
- Services: {', '.join(booking_data.get('services', []))}
- Payment method: {booking_data.get('payment_method', 'unknown')}

Assess the risk level. Return ONLY valid JSON:
{{
  "risk_level": "low" | "medium" | "high",
  "risk_score": <float 0.0-1.0>,
  "flags": ["..."],
  "recommendation": "allow" | "review" | "block"
}}
"""
        raw = await self._generate(prompt, temperature=0.1)
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)
        except Exception:
            return {"risk_level": "low", "risk_score": 0.1, "flags": [], "recommendation": "allow"}

    # ------------------------------------------------------------------
    # 6. Customer churn risk
    # ------------------------------------------------------------------

    async def predict_churn_risk(self, customer_data: dict) -> dict:
        """
        Predict whether a customer is at risk of churning.

        customer_data keys:
            days_since_last_booking, total_bookings, avg_rating_given,
            cancellation_rate (0-1), months_active
        """
        prompt = f"""
You are a customer retention analyst for a salon booking app.

Customer stats:
- Days since last booking: {customer_data.get('days_since_last_booking', 0)}
- Total bookings: {customer_data.get('total_bookings', 0)}
- Average rating given: {customer_data.get('avg_rating_given', 5)}
- Cancellation rate: {customer_data.get('cancellation_rate', 0):.0%}
- Months active: {customer_data.get('months_active', 0)}

Predict churn risk and suggest a retention action. Return ONLY valid JSON:
{{
  "churn_risk": "low" | "medium" | "high",
  "churn_probability": <float 0.0-1.0>,
  "retention_action": "..."
}}
"""
        raw = await self._generate(prompt, temperature=0.2)
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)
        except Exception:
            return {"churn_risk": "low", "churn_probability": 0.1, "retention_action": ""}

    # ------------------------------------------------------------------
    # 7. Peak hour / demand forecast
    # ------------------------------------------------------------------

    async def forecast_demand(self, historical_data: list[dict]) -> dict:
        """
        Given daily booking counts for the past N days, forecast the next 7 days.

        historical_data: list of {"date": "YYYY-MM-DD", "bookings": int}
        """
        data_text = "\n".join(
            f"{r['date']}: {r['bookings']} bookings"
            for r in historical_data[-30:]
        )

        prompt = f"""
You are a demand forecasting model for a salon booking platform.

Historical daily booking data:
{data_text}

Forecast the next 7 days and identify the 2 peak days. Return ONLY valid JSON:
{{
  "forecast": [
    {{"date": "YYYY-MM-DD", "predicted_bookings": <int>}}
  ],
  "peak_days": ["YYYY-MM-DD"],
  "trend": "increasing" | "stable" | "decreasing"
}}
"""
        raw = await self._generate(prompt, temperature=0.2)
        try:
            cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return json.loads(cleaned)
        except Exception:
            return {"forecast": [], "peak_days": [], "trend": "stable", "raw": raw}


# Module-level singleton
ai_service = AIService()

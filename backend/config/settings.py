# =============================================================================
# VIDATECH WIFI — Backend Configuration
# backend/config/settings.py
# =============================================================================
# Do NOT commit real values to GitHub.
# All secrets must live in environment variables.
# Copy .env.example to .env and fill in your values.
# =============================================================================

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):

    # -------------------------------------------------------------------------
    # APPLICATION
    # -------------------------------------------------------------------------
    APP_NAME: str = "Vidatech WiFi"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "production"] = "development"
    DEBUG: bool = False

    # -------------------------------------------------------------------------
    # SECURITY
    # -------------------------------------------------------------------------
    # Generate a strong secret: python -c "import secrets; print(secrets.token_hex(64))"
    JWT_SECRET_KEY: str = "REPLACE_WITH_STRONG_RANDOM_SECRET"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60        # 1 hour for admin sessions
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Number of failed logins before account lockout
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30

    # Allowed CORS origins (your Cloudflare Pages URL goes here)
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",                      # local dev
        "https://REPLACE_WITH_YOUR_CLOUDFLARE_PAGES_URL",
    ]

    # -------------------------------------------------------------------------
    # DATABASE — Supabase PostgreSQL
    # -------------------------------------------------------------------------
    SUPABASE_URL: str = "https://REPLACE_WITH_YOUR_SUPABASE_URL.supabase.co"
    SUPABASE_ANON_KEY: str = "REPLACE_WITH_YOUR_SUPABASE_ANON_KEY"
    SUPABASE_SERVICE_ROLE_KEY: str = "REPLACE_WITH_YOUR_SUPABASE_SERVICE_ROLE_KEY"

    # Direct PostgreSQL connection string (from Supabase → Settings → Database)
    DATABASE_URL: str = "postgresql://postgres:REPLACE_WITH_PASSWORD@db.REPLACE.supabase.co:5432/postgres"

    # -------------------------------------------------------------------------
    # DARAJA API — Safaricom M-Pesa
    # -------------------------------------------------------------------------
    DARAJA_ENV: Literal["sandbox", "production"] = "sandbox"

    # Sandbox base URL
    DARAJA_SANDBOX_URL: str = "https://sandbox.safaricom.co.ke"
    # Production base URL
    DARAJA_PRODUCTION_URL: str = "https://api.safaricom.co.ke"

    DARAJA_CONSUMER_KEY: str = "REPLACE_WITH_DARAJA_CONSUMER_KEY"
    DARAJA_CONSUMER_SECRET: str = "REPLACE_WITH_DARAJA_CONSUMER_SECRET"

    # STK Push settings
    DARAJA_SHORTCODE: str = "REPLACE_WITH_YOUR_TILL_OR_PAYBILL_NUMBER"
    DARAJA_PASSKEY: str = "REPLACE_WITH_YOUR_LIPA_NA_MPESA_PASSKEY"

    # The publicly accessible URL Daraja will POST the payment result to
    # Must be HTTPS — your Render backend URL
    DARAJA_CALLBACK_URL: str = "https://REPLACE_WITH_YOUR_RENDER_URL.onrender.com/api/payments/callback"

    # -------------------------------------------------------------------------
    # ROUTER — ZLT X17U
    # -------------------------------------------------------------------------
    ROUTER_IP: str = "192.168.1.1"
    ROUTER_USERNAME: str = "admin"
    ROUTER_PASSWORD: str = "REPLACE_WITH_YOUR_ROUTER_PASSWORD"
    ROUTER_TIMEOUT_SECONDS: int = 10

    # -------------------------------------------------------------------------
    # KEEPALIVE — Prevents Render free tier from sleeping
    # -------------------------------------------------------------------------
    KEEPALIVE_ENABLED: bool = True
    KEEPALIVE_INTERVAL_SECONDS: int = 600           # ping every 10 minutes
    KEEPALIVE_URL: str = "https://REPLACE_WITH_YOUR_RENDER_URL.onrender.com/health"

    # -------------------------------------------------------------------------
    # ADMIN
    # -------------------------------------------------------------------------
    # Your personal admin account — created on first startup
    ADMIN_PHONE: str = "REPLACE_WITH_YOUR_PHONE_NUMBER"   # e.g. 0712345678
    ADMIN_EMAIL: str = "REPLACE_WITH_YOUR_EMAIL"
    ADMIN_PASSWORD: str = "REPLACE_WITH_STRONG_ADMIN_PASSWORD"

    # Your MAC addresses — these devices bypass the portal entirely
    # Format: ["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"]
    ADMIN_MAC_ADDRESSES: list[str] = [
        "REPLACE_WITH_YOUR_DEVICE_1_MAC",
        "REPLACE_WITH_YOUR_DEVICE_2_MAC",
    ]

    # -------------------------------------------------------------------------
    # PORTAL
    # -------------------------------------------------------------------------
    PORTAL_TITLE: str = "VIDATECH WIFI"
    PORTAL_TAGLINE: str = "Fast. Affordable. Reliable."
    SESSION_GRACE_PERIOD_MINUTES: int = 5           # grace after expiry before hard cut

    # -------------------------------------------------------------------------
    # INTERNAL
    # -------------------------------------------------------------------------
    @property
    def DARAJA_BASE_URL(self) -> str:
        if self.DARAJA_ENV == "production":
            return self.DARAJA_PRODUCTION_URL
        return self.DARAJA_SANDBOX_URL

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.ENVIRONMENT == "production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Single instance used across the entire backend
@lru_cache()
def get_settings() -> Settings:
    return Settings()

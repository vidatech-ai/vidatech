# =============================================================================
# VIDATECH WIFI — Database Client
# backend/db.py
# =============================================================================

from functools import lru_cache
from supabase import create_client, Client
from config import get_settings

settings = get_settings()


@lru_cache()
def get_db() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

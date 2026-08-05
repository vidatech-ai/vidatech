# =============================================================================
# VIDATECH WIFI — Keepalive Background Task
# backend/utils/keepalive.py
# =============================================================================
# Pings the backend's own /health endpoint every N seconds.
# Prevents Render free tier from spinning down due to inactivity.
# =============================================================================

import asyncio
import logging

import httpx

logger = logging.getLogger("vidatech.keepalive")


async def _ping(url: str, client: httpx.AsyncClient) -> None:
    try:
        response = await client.get(url, timeout=10)
        if response.status_code == 200:
            logger.debug(f"Keepalive OK → {url}")
        else:
            logger.warning(f"Keepalive unexpected status {response.status_code} → {url}")
    except httpx.RequestError as e:
        logger.warning(f"Keepalive ping failed: {e}")


async def _keepalive_loop(url: str, interval: int) -> None:
    async with httpx.AsyncClient() as client:
        while True:
            await _ping(url, client)
            await asyncio.sleep(interval)


async def start_keepalive(url: str, interval: int) -> None:
    """
    Launches the keepalive loop as a background asyncio task.
    Called once during app startup from main.py lifespan.
    """
    asyncio.create_task(_keepalive_loop(url, interval))
    logger.info(f"Keepalive scheduled every {interval}s → {url}")

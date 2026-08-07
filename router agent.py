#!/usr/bin/env python3
# =============================================================================
# VIDATECH WIFI — Local Router Agent
# scripts/router_agent.py
# =============================================================================
# Runs on your laptop (or Raspberry Pi / Android phone later).
# Every 30 seconds:
#   1. Logs into ZLT X17U router
#   2. Fetches all connected devices
#   3. Pushes them to Supabase
#   4. Checks which devices have active paid sessions
#   5. Blocks unpaid devices, allows paid devices
# =============================================================================

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from supabase import create_client

# ---------------------------------------------------------------------------
# Config — reads from environment or .env file
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), 'backend/.env'))
except ImportError:
    pass

ROUTER_IP       = os.getenv('ROUTER_IP', '192.168.1.1')
ROUTER_USER     = os.getenv('ROUTER_USERNAME', 'admin')
ROUTER_PASS     = os.getenv('ROUTER_PASSWORD', '')
SUPABASE_URL    = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY    = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
POLL_INTERVAL   = int(os.getenv('POLL_INTERVAL', '30'))

# ZLT X17U command UUIDs (from reverse engineering)
CMD_LOGIN       = 'd2aa9843-494b-4947-9621-a46ec652ecd9'
CMD_GET_TOKEN   = '3830c61a-620d-47da-ae47-33d8401401c4'
CMD_DHCP        = '5332f5ee-5be9-4843-b85f-1b251aa5f4ff'
CMD_MAC_CTRL    = 'b3313335-2a88-4818-bddd-3abfd602b455'
CMD_BANDWIDTH   = '382'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger('vidatech.agent')


# ---------------------------------------------------------------------------
# Router client
# ---------------------------------------------------------------------------
class ZLTRouter:
    def __init__(self):
        self.base = f'http://{ROUTER_IP}'
        self.session_id = ''
        self.token = ''
        self.client = httpx.AsyncClient(timeout=10)

    async def _post(self, payload: dict) -> dict:
        r = await self.client.post(
            f'{self.base}/cgi-bin/http.cgi',
            json=payload,
        )
        return r.json()

    async def login(self) -> bool:
        try:
            # Step 1: get token
            data = await self._post({
                'cmd': CMD_GET_TOKEN,
                'method': 'GET',
                'sessionId': '',
            })
            token = data.get('token', '')

            # Step 2: hash password
            pwd_hash = hashlib.sha256(
                (token + ROUTER_PASS).encode()
            ).hexdigest()

            # Step 3: login
            result = await self._post({
                'cmd': CMD_LOGIN,
                'method': 'POST',
                'sessionId': '',
                'token': token,
                'username': ROUTER_USER,
                'passwd': pwd_hash,
            })

            self.session_id = result.get('sessionId', '')
            self.token = result.get('token', '')

            if self.session_id:
                logger.info('Router login successful.')
                return True

            logger.error(f'Router login failed: {result}')
            return False

        except Exception as e:
            logger.error(f'Router login error: {e}')
            return False

    async def get_connected_devices(self) -> list:
        try:
            data = await self._post({
                'cmd': CMD_DHCP,
                'method': 'GET',
                'sessionId': self.session_id,
            })
            return data.get('dhcp_list_info', [])
        except Exception as e:
            logger.error(f'Failed to get devices: {e}')
            return []

    async def block_mac(self, mac: str) -> bool:
        try:
            # Get current MAC list
            data = await self._post({
                'cmd': CMD_MAC_CTRL,
                'method': 'GET',
                'sessionId': self.session_id,
                'subcmd': '1',
            })
            current = data.get('datas', {}).get('maclist', [])

            # Add to blacklist if not already there
            if not any(d['mac'] == mac for d in current):
                current.append({'mac': mac, 'remarks': 'Blocked-Unpaid'})

            await self._post({
                'cmd': CMD_MAC_CTRL,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'subcmd': '1',
                'success': True,
                'datas': {
                    'maclist': current,
                    'macfilter': 'deny',
                },
            })
            logger.info(f'Blocked MAC: {mac}')
            return True
        except Exception as e:
            logger.error(f'Failed to block MAC {mac}: {e}')
            return False

    async def allow_mac(self, mac: str) -> bool:
        try:
            # Get current MAC list
            data = await self._post({
                'cmd': CMD_MAC_CTRL,
                'method': 'GET',
                'sessionId': self.session_id,
                'subcmd': '1',
            })
            current = data.get('datas', {}).get('maclist', [])

            # Remove from blacklist
            current = [d for d in current if d['mac'] != mac]

            await self._post({
                'cmd': CMD_MAC_CTRL,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'subcmd': '1',
                'success': True,
                'datas': {
                    'maclist': current,
                    'macfilter': 'close',
                },
            })
            logger.info(f'Allowed MAC: {mac}')
            return True
        except Exception as e:
            logger.error(f'Failed to allow MAC {mac}: {e}')
            return False

    async def set_speed(self, ip: str, download_kbps: int, upload_kbps: int) -> bool:
        try:
            await self._post({
                'cmd': CMD_BANDWIDTH,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'success': True,
                'datas': [{
                    'enableRule': True,
                    'ippro': 'IPV4',
                    'ip': ip,
                    'maxSpeed': download_kbps,
                }],
            })
            logger.info(f'Speed set for {ip}: {download_kbps} KB/s down')
            return True
        except Exception as e:
            logger.error(f'Failed to set speed for {ip}: {e}')
            return False

    async def close(self):
        await self.client.aclose()


# ---------------------------------------------------------------------------
# Supabase sync
# ---------------------------------------------------------------------------
def get_db():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


async def sync_devices(router: ZLTRouter, devices: list):
    """Push connected devices to Supabase."""
    db = get_db()
    now = utcnow()

    for device in devices:
        mac = device.get('mac', '').lower()
        ip  = device.get('ip', '')
        hostname = device.get('hostname', '')

        if not mac:
            continue

        try:
            db.table('devices').upsert({
                'mac_address': mac,
                'ip_address': ip,
                'hostname': hostname,
                'last_seen_at': now,
            }, on_conflict='mac_address').execute()
        except Exception as e:
            logger.error(f'Failed to sync device {mac}: {e}')


async def enforce_access(router: ZLTRouter, devices: list):
    """
    For each connected device:
    - If they have an active paid session → allow + apply speed
    - If they don't → block
    """
    db = get_db()
    now = utcnow()

    for device in devices:
        mac = device.get('mac', '').lower()
        ip  = device.get('ip', '')

        if not mac:
            continue

        try:
            # Check for active session
            result = db.table('sessions').select(
                '*, packages(download_kbps, upload_kbps)'
            ).eq('mac_address', mac).eq('status', 'active').gt(
                'expires_at', now
            ).limit(1).execute()

            if result.data:
                # Paid and active — allow
                session = result.data[0]
                pkg = session.get('packages', {})
                await router.allow_mac(mac)

                # Apply speed limit
                if ip and pkg:
                    await router.set_speed(
                        ip,
                        pkg.get('download_kbps', 512),
                        pkg.get('upload_kbps', 256),
                    )

                # Update device status
                db.table('devices').update({
                    'status': 'allowed',
                    'ip_address': ip,
                }).eq('mac_address', mac).execute()

            else:
                # Not paid or expired — check if device is permanently whitelisted first
                user_result = db.table('users').select(
                    'is_whitelisted'
                ).contains('mac_addresses', [mac]).execute()

                if user_result.data and user_result.data[0].get('is_whitelisted'):
                    logger.info(f'Whitelisted admin device: {mac}')
                    await router.allow_mac(mac)
                    continue

                await router.block_mac(mac)
                db.table('devices').update({
                    'status': 'blocked',
                    'ip_address': ip,
                }).eq('mac_address', mac).execute()

        except Exception as e:
            logger.error(f'Enforcement error for {mac}: {e}')


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
async def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.')
        return

    if not ROUTER_PASS:
        logger.error('ROUTER_PASSWORD must be set.')
        return

    logger.info(f'Vidatech Router Agent starting — polling every {POLL_INTERVAL}s')
    logger.info(f'Router: {ROUTER_IP}')

    router = ZLTRouter()

    while True:
        try:
            # Login (re-login every cycle in case session expired)
            logged_in = await router.login()

            if logged_in:
                devices = await router.get_connected_devices()
                logger.info(f'Connected devices: {len(devices)}')

                if devices:
                    await sync_devices(router, devices)
                    await enforce_access(router, devices)
            else:
                logger.warning('Could not login to router. Retrying next cycle.')

        except Exception as e:
            logger.error(f'Agent cycle error: {e}')

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    asyncio.run(main())
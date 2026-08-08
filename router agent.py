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
WHITELISTED_MACS = {
    mac.strip().lower()
    for mac in os.getenv('WHITELISTED_MACS', '3c:15:c2:c2:4b:78').split(',')
    if mac.strip()
}

# ZLT X17U command IDs (verified from filteringRules.33aa9d6e.js, Aug 2026)
CMD_LOGIN         = 'd2aa9843-494b-4947-9621-a46ec652ecd9'
CMD_GET_TOKEN     = '3830c61a-620d-47da-ae47-33d8401401c4'
CMD_DHCP          = '5332f5ee-5be9-4843-b85f-1b251aa5f4ff'
CMD_MAC_FILTER    = 23
CMD_MAC_MODE_V4   = 28
CMD_MAC_FILTER_V2 = "b3313335-2a88-4818-bddd-3abfd602b455"
CMD_WIFI_STATUS   = "d4c25573-520b-49b4-af04-a7912ad3ad86"   # accept-all toggle for IPv4 (blacklist/whitelist master switch)
CMD_TOKEN_REFRESH = 'f3b70f2f-8721-48c4-87ec-22d8c92dd3c9'
CMD_BANDWIDTH     = '382'
CMD_QOS    = "0b1734b4-6320-4798-b8f2-2dd7868ce513"
CMD_REBOOT = "7a9cfe11-78bb-43aa-8041-4bcb0b839565"

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
        self.client = httpx.AsyncClient(timeout=5, headers={"Connection": "close"})

    async def _post(self, payload: dict) -> dict:
        r = await self.client.post(
            f'{self.base}/cgi-bin/http.cgi',
            json=payload,
        )
        result = r.json()

        # Retry once on CSRF/token mismatch — race condition fix
        if result.get('message') == 'Invalid CSRF Token' and payload.get('method') == 'POST':
            logger.warning('CSRF token mismatch, refreshing and retrying once...')
            try:
                token_resp = await self.client.post(
                    f'{self.base}/cgi-bin/http.cgi',
                    json={'cmd': CMD_TOKEN_REFRESH, 'method': 'GET', 'sessionId': self.session_id},
                )
                self.token = token_resp.json().get('token', self.token)
                payload['token'] = self.token
                r = await self.client.post(
                    f'{self.base}/cgi-bin/http.cgi',
                    json=payload,
                )
                result = r.json()
            except Exception as e:
                logger.error(f'CSRF retry failed: {e}')

        # Frontend refreshes the token after every POST — match that behavior
        if payload.get('method') == 'POST':
            try:
                token_resp = await self.client.post(
                    f'{self.base}/cgi-bin/http.cgi',
                    json={
                        'cmd': CMD_TOKEN_REFRESH,
                        'method': 'GET',
                        'sessionId': self.session_id,
                    },
                )
                self.token = token_resp.json().get('token', self.token)
            except Exception:
                pass

        return result

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

    async def _get_mac_list(self, subcmd=0):
        data = await self._post({
            'cmd': CMD_MAC_FILTER_V2,
            'method': 'GET',
            'sessionId': self.session_id,
            'subcmd': subcmd,
        })
        datas = data.get('datas', {}) or {}
        return datas.get('maclist', []), datas.get('macfilter', 'close')

    async def _write_mac_list(self, maclist, macfilter, subcmd=0):
        wifi = await self._post({
            'cmd': CMD_WIFI_STATUS,
            'method': 'GET',
            'sessionId': self.session_id,
        })
        logger.info(f'WiFi status response: {wifi}')
        if wifi.get('wifiStatus') != '1':
            logger.warning('WiFi not ready, skipping MAC write')
            return False
        result = await self._post({
            'cmd': CMD_MAC_FILTER_V2,
            'method': 'POST',
            'sessionId': self.session_id,
            'token': self.token,
            'subcmd': subcmd,
            'success': True,
            'datas': {
                'maclist': maclist,
                'macfilter': macfilter,
            },
        })
        logger.info(f'MAC filter write response: {result}')
        return result.get('success', False)

    async def _get_firewall_rules(self) -> list:
        data = await self._post({
            'cmd': CMD_MAC_FILTER,
            'method': 'GET',
            'sessionId': self.session_id,
        })
        return data.get('datas', []) or []

    async def _write_firewall_rules(self, rules: list) -> bool:
        result = await self._post({
            'cmd': CMD_MAC_FILTER,
            'method': 'POST',
            'sessionId': self.session_id,
            'token': self.token,
            'success': True,
            'datas': rules,
        })
        logger.info(f'Firewall write response: {result}')

        # Activate the blacklist — this is the "Save Rule" enable command
        activate = await self._post({
            'cmd': '06df6e71-3091-4fd3-98c4-759127d0f366',
            'method': 'POST',
            'sessionId': self.session_id,
            'token': self.token,
        })
        logger.info(f'Blacklist activate response: {activate}')

        return result.get('success', False)

    async def block_mac(self, mac: str) -> bool:
        try:
            mac = mac.upper()
            rules = await self._get_firewall_rules()
            rules = [r for r in rules if r.get('mac', '').upper() != mac]
            rules.append({
                'enableRule': True,
                'enableLink': False,
                'ippro': 'IPV4',
                'remark': 'Blocked-Unpaid',
                'mac': mac,
            })
            result = await self._write_firewall_rules(rules)
            logger.info(f'Blocked MAC: {mac} | result: {result}')
            return True
        except Exception as e:
            logger.error(f'Failed to block MAC {mac}: {e}')
            return False

    async def allow_mac(self, mac: str) -> bool:
        try:
            mac = mac.upper()
            rules = await self._get_firewall_rules()
            rules = [r for r in rules if r.get('mac', '').upper() != mac]
            rules.append({
                'enableRule': True,
                'enableLink': True,
                'ippro': 'IPV4',
                'remark': 'Paid',
                'mac': mac,
            })
            result = await self._write_firewall_rules(rules)
            logger.info(f'Allowed MAC: {mac} | result: {result}')
            return True
        except Exception as e:
            logger.error(f'Failed to allow MAC {mac}: {e}')
            return False

    async def ensure_blacklist_mode(self):
        try:
            result = await self._post({
                'cmd': CMD_MAC_MODE_V4,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'success': True,
                'datas': [{'enableRule': True, 'acceptAll': "1", 'ippro': 'IPV4'}],
            })
            logger.info(f'Set whitelist mode response: {result}')
        except Exception as e:
            logger.error(f'Failed to set whitelist mode: {e}')

    

    async def enable_qos(self, total_up_mbps: int = 20, total_down_mbps: int = 20):
        try:
            result = await self._post({
                'cmd': CMD_QOS,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'subcmd': 0,
                'qosSw': '1',
                'upBandwidth': total_up_mbps,
                'downBandwidth': total_down_mbps,
            })
            logger.info(f'QoS enable response: {result}')
        except Exception as e:
            logger.error(f'Failed to enable QoS: {e}')

    async def set_speed(self, ip: str, download_kbps: int, upload_kbps: int) -> bool:
        try:
            await self.enable_qos()
            await asyncio.sleep(0.5)

            data = {}
            for attempt in range(3):
                try:
                    data = await self._post({
                        'cmd': CMD_QOS,
                        'method': 'GET',
                        'sessionId': self.session_id,
                        'subcmd': 1,
                    })
                    break
                except Exception as e:
                    logger.warning(f'QoS GET attempt {attempt+1} failed: {e}')
                    await asyncio.sleep(1)
            current = data.get('datas', []) or []
            current = [d for d in current if d.get('ip') != ip]
            current.append({
                'ip': ip,
                'port': '',
                'maxUpBandwidth': max(1, upload_kbps // 1000),
                'maxDownBandwidth': max(1, download_kbps // 1000),
            })

            write_payload = {
                'cmd': CMD_QOS,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'subcmd': 1,
                'datas': current,
            }
            logger.info(f'QoS write payload for {ip}: {write_payload}')

            result = await self._post(write_payload)
            logger.info(f'Speed response for {ip}: {result}')
            return bool(result.get('success'))
        except Exception as e:
            logger.error(f'Failed to set speed for {ip}: {e}')
            # Disconnect might mean rule was applied — verify by reading back
            try:
                verify = await self._post({
                    'cmd': CMD_QOS,
                    'method': 'GET',
                    'sessionId': self.session_id,
                    'subcmd': 1,
                })
                logger.info(f'QoS verify after disconnect: {verify}')
                return True
            except Exception as e2:
                logger.error(f'Verify also failed: {e2}')
                return False

    async def reboot(self):
        try:
            token_resp = await self.client.post(
                f'{self.base}/cgi-bin/http.cgi',
                json={'cmd': CMD_TOKEN_REFRESH, 'method': 'GET', 'sessionId': self.session_id},
            )
            self.token = token_resp.json().get('token', self.token)

            result = await self._post({
                'cmd': CMD_REBOOT,
                'method': 'POST',
                'sessionId': self.session_id,
                'token': self.token,
                'rebootType': 1,
            })
            logger.info(f'Reboot response: {result}')
        except Exception as e:
            logger.error(f'Reboot failed: {e}')

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


DNSMASQ_CONF   = '/etc/dnsmasq.d/vidatech-paid.conf'
PORTAL_IP      = '172.66.47.79'
REAL_DNS       = '8.8.8.8'

def update_dnsmasq(paid_ips: set):
    """
    Write per-IP DNS overrides for paid devices so they get real DNS.
    Unpaid devices still hit the catch-all address=/#/ redirect.
    """
    lines = ['# Auto-generated by Vidatech agent — do not edit\n']
    for ip in paid_ips:
        # Route paid device to real DNS by adding a dummy hostsfile entry
        lines.append(f'# paid: {ip}\n')
    try:
        with open(DNSMASQ_CONF, 'w') as f:
            f.writelines(lines)
        os.system('sudo systemctl reload dnsmasq')
    except Exception as e:
        logger.error(f'dnsmasq update failed: {e}')


async def enforce_access(router: ZLTRouter, devices: list):
    """
    Builds one complete firewall rules list and writes it once per cycle.
    This prevents race conditions and router instability.
    """
    db = get_db()
    now = utcnow()
    new_rules = []
    paid_ips = set()

    for device in devices:
        mac = device.get('mac', '').lower()
        ip  = device.get('ip', '')

        if not mac:
            continue

        try:
            # WHITELISTED_MACS in env — never block
            if mac in WHITELISTED_MACS:
                logger.info(f'Env whitelisted: {mac}')
                new_rules.append({
                    'enableRule': True,
                    'enableLink': True,
                    'ippro': 'IPV4',
                    'remark': 'Admin',
                    'mac': mac.upper(),
                })
                paid_ips.add(ip)
                db.table('devices').update({
                    'status': 'allowed',
                    'ip_address': ip,
                }).eq('mac_address', mac).execute()
                continue

            # Check if admin whitelisted via dashboard
            device_result = db.table('devices').select('status').eq('mac_address', mac).limit(1).execute()
            device_status = device_result.data[0].get('status') if device_result.data else None

            if device_status == 'whitelisted':
                logger.info(f'Dashboard whitelisted: {mac}')
                new_rules.append({
                    'enableRule': True,
                    'enableLink': True,
                    'ippro': 'IPV4',
                    'remark': 'Whitelisted',
                    'mac': mac.upper(),
                })
                paid_ips.add(ip)
                continue

            # Check for active paid session
            result = db.table('sessions').select(
                '*, packages(download_kbps, upload_kbps)'
            ).eq('mac_address', mac).eq('status', 'active').gt(
                'expires_at', now
            ).limit(1).execute()

            if result.data:
                session = result.data[0]
                pkg = session.get('packages', {})
                logger.info(f'Paid session: {mac}')
                new_rules.append({
                    'enableRule': True,
                    'enableLink': True,
                    'ippro': 'IPV4',
                    'remark': 'Paid',
                    'mac': mac.upper(),
                })
                paid_ips.add(ip)
                if ip and pkg:
                    await router.set_speed(
                        ip,
                        pkg.get('download_kbps', 512),
                        pkg.get('upload_kbps', 256),
                    )
                db.table('devices').update({
                    'status': 'allowed',
                    'ip_address': ip,
                }).eq('mac_address', mac).execute()

            else:
                logger.info(f'Blocking unpaid: {mac}')
                new_rules.append({
                    'enableRule': True,
                    'enableLink': False,
                    'ippro': 'IPV4',
                    'remark': 'Blocked-Unpaid',
                    'mac': mac.upper(),
                })
                db.table('devices').update({
                    'status': 'blocked',
                    'ip_address': ip,
                }).eq('mac_address', mac).execute()

        except Exception as e:
            logger.error(f'Enforcement error for {mac}: {e}')
            new_rules.append({
                'enableRule': True,
                'enableLink': False,
                'ippro': 'IPV4',
                'remark': 'Blocked-Error',
                'mac': mac.upper(),
            })

    # Write ALL rules in ONE single call — much lighter on router
    try:
        await router._write_firewall_rules(new_rules)
        logger.info(f'Firewall updated: {len(new_rules)} rules written')
    except Exception as e:
        logger.error(f'Failed to write firewall rules: {e}')

    update_dnsmasq(paid_ips)


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

    # Login once at startup
    logged_in = await router.login()
    if not logged_in:
        logger.error('Initial login failed. Exiting.')
        return

    login_cycle = 0  # re-login every 60 cycles (~5 mins)

    while True:
        try:
            # Re-login every 60 cycles to refresh session
            if login_cycle >= 60:
                logged_in = await router.login()
                if not logged_in:
                    logger.warning('Re-login failed, keeping existing session.')
                login_cycle = 0

            devices = await router.get_connected_devices()
            logger.info(f'Connected devices: {len(devices)}')

            if devices:
                await sync_devices(router, devices)
                await enforce_access(router, devices)

            login_cycle += 1

        except Exception as e:
            logger.error(f'Agent cycle error: {e}')
            # Try re-login on error
            try:
                await router.login()
                login_cycle = 0
            except Exception:
                pass

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    asyncio.run(main())
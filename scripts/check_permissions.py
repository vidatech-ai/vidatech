#!/usr/bin/env python3
# =============================================================================
# VIDATECH WIFI — Router Permission Checker
# scripts/check_permissions.py
# =============================================================================
# Logs into the ZLT X17U using the SAME flow as router_agent.py, then probes
# a curated list of GET endpoints to see which ones the current account
# level can actually read/act on vs which come back LIMITED_ACCESS / NO_AUTH.
#
# Usage:
#   python3 check_permissions.py
#
# Reads ROUTER_IP / ROUTER_USERNAME / ROUTER_PASSWORD from env or
# backend/.env, same as router_agent.py.
# =============================================================================

import asyncio
import hashlib
import os

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), 'backend/.env'))
except ImportError:
    pass

ROUTER_IP   = os.getenv('ROUTER_IP', '192.168.1.1')
ROUTER_USER = os.getenv('ROUTER_USERNAME', 'admin')
ROUTER_PASS = os.getenv('ROUTER_PASSWORD', '')

CMD_LOGIN     = 'd2aa9843-494b-4947-9621-a46ec652ecd9'
CMD_GET_TOKEN = '3830c61a-620d-47da-ae47-33d8401401c4'

# Endpoints worth checking — label them by what they actually control so the
# report is readable. Add/remove UUIDs here as you find more in the wild
# (e.g. via the browser Network tab while clicking through admin pages).
ENDPOINTS_TO_CHECK = {
    'dhcp_list (connected devices)':      '5332f5ee-5be9-4843-b85f-1b251aa5f4ff',
    'mac_filter_ctrl (block/allow MAC)':  'b3313335-2a88-4818-bddd-3abfd602b455',
    'bandwidth_ctrl (speed limit)':       '382',
    'sys_info (from earlier capture)':    '2ee26212-96cc-45d3-8f0d-808e4cde884a',
    'login_state / account_level':        '55f29f9b-20cd-4d72-ab20-63ba0b4d2a7a',
    'upgrade_from_web (firmware)':        '203e2658-b445-4eb7-bd2b-ba63063dcdbc',
    'set_hash (password/security)':       '34ba4378-19c4-41f5-a93f-566a56e7d6ba',
}


class ZLTRouter:
    def __init__(self):
        self.base = f'http://{ROUTER_IP}'
        self.session_id = ''
        self.token = ''
        self.client = httpx.AsyncClient(timeout=10)

    async def _post(self, payload: dict) -> dict:
        r = await self.client.post(f'{self.base}/cgi-bin/http.cgi', json=payload)
        return r.json()

    async def login(self, debug: bool = True) -> bool:
        data = await self._post({'cmd': CMD_GET_TOKEN, 'method': 'GET', 'sessionId': ''})
        if debug:
            print(f'[debug] token request raw response: {data}')
        token = data.get('token', '')
        if not token:
            print('[debug] No token returned — token endpoint UUID may be wrong, '
                  'or router requires a different first step.')
            return False

        pwd_hash = hashlib.sha256((token + ROUTER_PASS).encode()).hexdigest()
        if debug:
            print(f'[debug] token={token}')
            print(f'[debug] password being hashed (check for typos!): {ROUTER_PASS!r}')
            print(f'[debug] computed passwd hash={pwd_hash}')

        result = await self._post({
            'cmd': CMD_LOGIN,
            'method': 'POST',
            'sessionId': '',
            'token': token,
            'username': ROUTER_USER,
            'passwd': pwd_hash,
        })
        if debug:
            print(f'[debug] login raw response: {result}')

        self.session_id = result.get('sessionId', '')
        self.token = result.get('token', '')
        return bool(self.session_id)

    async def probe(self, cmd: str) -> dict:
        return await self._post({'cmd': cmd, 'method': 'GET', 'sessionId': self.session_id})

    async def close(self):
        await self.client.aclose()


def classify(result: dict) -> str:
    """Turn a raw response into a plain-English verdict."""
    success = result.get('success')
    message = str(result.get('message', '')).upper()

    if success is False and 'LIMITED_ACCESS' in message:
        return 'BLOCKED (limited access — needs higher user_level)'
    if success is False and 'NO_AUTH' in message:
        return 'BLOCKED (auth rejected — bad session/token)'
    if success is False:
        return f'FAILED ({result.get("message", "unknown error")})'
    if success is True:
        extra_keys = [k for k in result.keys() if k not in ('success', 'cmd', 'message')]
        return f'OK — returned {len(extra_keys)} field(s): {extra_keys[:6]}{"..." if len(extra_keys) > 6 else ""}'
    return f'UNKNOWN response shape: {list(result.keys())}'


async def main():
    if not ROUTER_PASS:
        print('ROUTER_PASSWORD not set — export it or put it in backend/.env')
        return

    router = ZLTRouter()
    print(f'Logging into {ROUTER_IP} as {ROUTER_USER} ...')
    ok = await router.login()
    if not ok:
        print('Login failed — check ROUTER_PASSWORD / network.')
        await router.close()
        return
    print(f'Logged in. sessionId={router.session_id[:12]}...\n')

    print(f'{"ENDPOINT":42} | VERDICT')
    print('-' * 100)
    for label, cmd in ENDPOINTS_TO_CHECK.items():
        try:
            result = await router.probe(cmd)
            verdict = classify(result)
        except Exception as e:
            verdict = f'ERROR calling endpoint: {e}'
        print(f'{label:42} | {verdict}')

    await router.close()


if __name__ == '__main__':
    asyncio.run(main())

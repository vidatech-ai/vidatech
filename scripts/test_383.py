#!/usr/bin/env python3
import asyncio
from router_agent import ZLTRouter, logger

MAC = "E2:46:AD:CE:28:39"
ALLOWED_URL = "vidatech-wifi.pages.dev"

async def main():
    router = ZLTRouter()
    if not await router.login():
        logger.error("Login failed")
        return

    rules = [{
        'enableRule': True,
        'mac': MAC.upper(),
        'url': ALLOWED_URL,
        'enableLink': True,
    }]

    result = await router._post({
        'cmd': 383,
        'method': 'POST',
        'sessionId': router.session_id,
        'token': router.token,
        'success': True,
        'datas': rules,
    })
    logger.info(f'Write result: {result}')

    check = await router._post({
        'cmd': 383,
        'method': 'GET',
        'sessionId': router.session_id,
        'getfun': True,
    })
    logger.info(f'Current rules: {check}')

    await router.close()
    print(f"\nNow test from device with MAC {MAC}:")
    print(f"  - Try {ALLOWED_URL} -> should work")
    print(f"  - Try google.com or any other site -> does it fail or work?")

if __name__ == '__main__':
    asyncio.run(main())

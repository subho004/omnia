"""Start PublicEgressProxy and perform CDP snapshot check on Zepto."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from claw_orchestrator.auth import Principal
from claw_orchestrator.config import Settings
from claw_orchestrator.db import Database
from claw_orchestrator.egress_proxy import PublicEgressProxy
from claw_orchestrator.gateway import GatewayClient


class DirectGuard:
    async def run(self, operation):
        return await operation


async def main():
    settings = Settings()

    # 1. Start PublicEgressProxy on 0.0.0.0:18490
    proxy = PublicEgressProxy(host="0.0.0.0", port=settings.egress_proxy_port)
    await proxy.start()
    print(f"PublicEgressProxy listening on 0.0.0.0:{settings.egress_proxy_port}")

    db = Database(settings.database_url)
    await db.open()

    async with db.connection() as conn:
        row = await conn.fetchrow("SELECT * FROM instances WHERE owner_user_id='user1'")

    principal = Principal(
        "browser-cdp-test",
        row["owner_user_id"],
        "",
        datetime.now(UTC) + timedelta(minutes=5),
        str(row["id"]),
    )
    gateway = GatewayClient(SimpleNamespace(settings=settings), principal, dict(row), DirectGuard())
    gateway.scopes = ["operator.admin"]

    await gateway.open()
    print("Gateway WebSocket connected")

    async def call_browser(method, path, body=None):
        params = {
            "method": method,
            "path": path,
            "target": "host",
            "query": {"profile": "openclaw"},
            "timeoutMs": 45000,
        }
        if body is not None:
            params["body"] = body
        request_id = str(uuid4())
        await gateway.socket.send(
            json.dumps(
                {"type": "req", "id": request_id, "method": "browser.request", "params": params}
            )
        )
        async with asyncio.timeout(50):
            while True:
                frame = await gateway.receive()
                if frame.get("type") == "res" and frame.get("id") == request_id:
                    if frame.get("ok") is not True:
                        raise RuntimeError(f"Browser request failed: {frame.get('error')}")
                    return frame.get("payload", {})

    try:
        # Open a new tab for Zepto
        print("Navigating to https://www.zepto.com via browser.request...")
        tab = await call_browser("POST", "/tabs/open", {"url": "https://www.zepto.com"})
        target_id = tab.get("targetId")
        print(f"Tab opened with targetId: {target_id}")

        print("Waiting 6 seconds for network & page render...")
        await asyncio.sleep(6)

        # Get tabs
        tabs = await call_browser("GET", "/tabs")
        print("Open tabs list:")
        for t in tabs.get("tabs", []):
            print(f" - [{t.get('targetId')}] {t.get('title')}: {t.get('url')}")

        # Fetch snapshot
        print("\nFetching /snapshot via CDP...")
        snapshot = await call_browser("GET", "/snapshot")
        print("Snapshot title/URL:", snapshot.get("url"))
        print("\n--- SNAPSHOT CONTENT ---")
        content = snapshot.get("snapshot", "")
        print(content[:3000])
        print("--- END SNAPSHOT ---\n")

    finally:
        await gateway.close()
        await db.close()
        await proxy.close()
        print("Closed gateway, DB, and proxy.")


if __name__ == "__main__":
    asyncio.run(main())

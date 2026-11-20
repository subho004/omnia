"""Direct CDP check on Zepto via OpenClaw's native browser control protocol."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from claw_orchestrator.auth import Principal
from claw_orchestrator.config import Settings
from claw_orchestrator.db import Database
from claw_orchestrator.gateway import GatewayClient


class DirectGuard:
    async def run(self, operation):
        return await operation


async def main():
    settings = Settings()
    db = Database(settings.database_url)
    await db.open()

    async with db.connection() as conn:
        row = await conn.fetchrow("SELECT * FROM instances WHERE owner_user_id='user1'")
    if not row:
        print("User 1 instance not found in database")
        await db.close()
        return

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
    print("Gateway WebSocket opened for user1")

    async def call_browser(method, path, body=None, query=None):
        q = {"profile": "openclaw"}
        if query:
            q.update(query)
        params = {
            "method": method,
            "path": path,
            "target": "host",
            "query": q,
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
                        print("Error response frame:", json.dumps(frame, indent=2))
                        raise RuntimeError(f"Browser request failed: {frame.get('error')}")
                    return frame.get("payload", {})

    try:
        print("Stopping any existing browser instance...")
        try:
            stopped = await call_browser("POST", "/stop", {})
            print("Stopped response:", json.dumps(stopped))
        except Exception as e:
            print("Stop error (may already be stopped):", e)

        await asyncio.sleep(2)

        print("Starting fresh browser...")
        started = await call_browser("POST", "/start", {})
        print("Start response:", json.dumps(started))

        print("Opening tab for https://www.zepto.com...")
        tab = await call_browser("POST", "/tabs/open", {"url": "https://www.zepto.com"})
        print("Opened tab result:", json.dumps(tab))
        target_id = tab.get("targetId")

        print("Waiting 5 seconds for page to load...")
        await asyncio.sleep(5)

        print("Listing open tabs...")
        tabs = await call_browser("GET", "/tabs")
        print("Tabs:", json.dumps(tabs, indent=2))

        print("Fetching /snapshot from CDP...")
        try:
            snapshot = await call_browser(
                "GET", "/snapshot", query={"targetId": target_id} if target_id else None
            )
            print("Snapshot format:", snapshot.get("format"))
            print("Snapshot url:", snapshot.get("url"))
            print("Snapshot content:\n", snapshot.get("snapshot"))
        except Exception as e:
            print("Snapshot call error:", e)

    finally:
        await gateway.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

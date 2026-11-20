"""Pair dedicated server scheduler identities for existing ready demo workspaces."""

import asyncio

from claw_orchestrator.config import Settings
from claw_orchestrator.db import Database
from claw_orchestrator.runtime.nemoclaw import NemoClawRuntime


async def main():
    settings = Settings()
    db = Database(settings.database_url)
    await db.open()
    runtime = NemoClawRuntime(settings)
    try:
        async with db.connection() as conn:
            rows = await conn.fetch("SELECT * FROM instances WHERE status='ready'")
        for row in rows:
            await runtime.prepare_automation_access(dict(row))
            print(f"{row['owner_user_id']}: scheduler identity paired")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

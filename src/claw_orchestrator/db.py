from importlib.resources import files

import asyncpg


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def open(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.url,
            min_size=1,
            max_size=6,
            command_timeout=5,
            server_settings={"search_path": "claw,public", "application_name": "claw-orchestrator"},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(532807120)")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            for path in sorted(
                files("claw_orchestrator").joinpath("migrations").iterdir(),
                key=lambda item: item.name,
            ):
                if not path.name.endswith(".sql"):
                    continue
                if not await conn.fetchval(
                    "SELECT 1 FROM schema_migrations WHERE version=$1", path.name
                ):
                    await conn.execute(path.read_text())
                    await conn.execute(
                        "INSERT INTO schema_migrations(version) VALUES($1)", path.name
                    )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def connection(self):
        assert self.pool is not None
        return self.pool.acquire(timeout=5)

import asyncio
import logging

from .db import Database
from .runtime import Runtime

log = logging.getLogger(__name__)


async def provision_one(db: Database, runtime: Runtime) -> bool:
    if not runtime.available:
        return False
    async with db.connection() as conn, conn.transaction():
        job = await conn.fetchrow(
            "SELECT * FROM provisioning_jobs WHERE status='pending' OR "
            "(status='running' AND lease_until<now()) FOR UPDATE SKIP LOCKED LIMIT 1"
        )
        if not job:
            return False
        iid = job["instance_id"]
        if job["attempts"] >= 3:
            await conn.execute(
                "UPDATE provisioning_jobs SET status='failed',lease_until=NULL,"
                "error_code='RECOVERY_LIMIT' WHERE instance_id=$1",
                iid,
            )
            await conn.execute(
                "UPDATE instances SET status='failed',error_code='RECOVERY_LIMIT',"
                "updated_at=now() WHERE id=$1",
                iid,
            )
            return True
        await conn.execute(
            "UPDATE provisioning_jobs SET status='running', attempts=attempts+1,"
            "lease_until=now()+interval '660 seconds' WHERE instance_id=$1",
            iid,
        )
        row = await conn.fetchrow(
            "UPDATE instances SET status='provisioning',updated_at=now() WHERE id=$1 RETURNING *",
            iid,
        )
    try:
        async with asyncio.timeout(630):
            result = await runtime.provision(dict(row))
            candidate = {
                **dict(row),
                "runtime_id": result.runtime_id,
                "upstream_url": result.upstream_url,
            }
            if not await runtime.probe(candidate):
                raise RuntimeError("readiness failed")
        async with db.connection() as conn, conn.transaction():
            await conn.execute(
                "UPDATE instances SET status='ready',runtime_id=$2,upstream_url=$3,"
                "container_name=$4,"
                "error_code=NULL,updated_at=now() WHERE id=$1",
                iid,
                result.runtime_id,
                result.upstream_url,
                result.container_name,
            )
            await conn.execute(
                "UPDATE provisioning_jobs SET status='done',lease_until=NULL WHERE instance_id=$1",
                iid,
            )
    except Exception:
        # Runtime exceptions may contain credentials/CLI output. Never send or log their text.
        log.warning("instance provisioning failed", extra={"instance_id": str(iid)})
        async with db.connection() as conn, conn.transaction():
            await conn.execute(
                "UPDATE instances SET status='failed',error_code='PROVISIONING_FAILED',"
                "updated_at=now() WHERE id=$1",
                iid,
            )
            await conn.execute(
                "UPDATE provisioning_jobs SET status='failed',error_code='PROVISIONING_FAILED',"
                "lease_until=NULL WHERE instance_id=$1",
                iid,
            )
    return True


async def recover_retained(db: Database, runtime: Runtime) -> int:
    """Recheck existing unavailable workloads; never provision or adopt resources."""
    if not runtime.available:
        return 0
    async with db.connection() as conn:
        rows = await conn.fetch(
            "SELECT * FROM instances WHERE status='unavailable' "
            "AND runtime_id IS NOT NULL AND upstream_url IS NOT NULL "
            "AND container_name IS NOT NULL"
        )
    recovered = 0
    for row in rows:
        try:
            async with asyncio.timeout(20):
                healthy = await runtime.probe(dict(row))
        except Exception:
            healthy = False
        if not healthy:
            continue
        async with db.connection() as conn:
            updated = await conn.fetchval(
                "UPDATE instances SET status='ready',error_code=NULL,updated_at=now() "
                "WHERE id=$1 AND owner_user_id=$2 AND status='unavailable' "
                "AND runtime_id=$3 AND upstream_url=$4 AND container_name=$5 RETURNING id",
                row["id"],
                row["owner_user_id"],
                row["runtime_id"],
                row["upstream_url"],
                row["container_name"],
            )
        recovered += updated is not None
    return recovered


async def worker(db: Database, runtime: Runtime) -> None:
    next_recovery = 0.0
    while True:
        try:
            worked = await provision_one(db, runtime)
            now = asyncio.get_running_loop().time()
            if now >= next_recovery:
                await recover_retained(db, runtime)
                next_recovery = asyncio.get_running_loop().time() + 10
        except Exception:
            log.warning("provisioning worker dependency unavailable")
            worked = False
        if not worked:
            await asyncio.sleep(1)

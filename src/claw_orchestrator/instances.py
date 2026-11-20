import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from .auth import Auth, Principal, digest
from .config import Settings
from .db import Database
from .errors import APIError
from .runtime import Runtime


def public_instance(row) -> dict:
    return {
        "instance": {
            "id": str(row["id"]),
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "error_code": row["error_code"],
        }
    }


class Instances:
    def __init__(self, settings: Settings, db: Database, auth: Auth, runtime: Runtime):
        self.settings, self.db, self.auth, self.runtime = settings, db, auth, runtime

    async def own(self, user_id: str):
        async with self.db.connection() as conn:
            row = await conn.fetchrow("SELECT * FROM instances WHERE owner_user_id=$1", user_id)
        if not row:
            raise APIError(404, "INSTANCE_NOT_CREATED", "You haven't created an instance yet.")
        return row

    async def create(self, principal: Principal):
        # No placeholder instances/jobs when real provisioning is unavailable.
        if not self.runtime.available:
            raise APIError(503, "RUNTIME_NOT_CONFIGURED", self.runtime.reason)
        iid = uuid4()
        async with self.db.connection() as conn, conn.transaction():
            if not await conn.fetchval(
                "SELECT 1 FROM sessions WHERE sid=$1 AND user_id=$2 AND revoked_at IS NULL "
                "AND expires_at>now() FOR SHARE",
                principal.sid,
                principal.user_id,
            ):
                raise APIError(401, "INVALID_SESSION", "Your session has ended.")
            row = await conn.fetchrow(
                "INSERT INTO instances(id,owner_user_id,status,sandbox_name,volume_name) "
                "VALUES($1,$2,'pending',$3,$4) ON CONFLICT(owner_user_id) DO NOTHING RETURNING *",
                iid,
                principal.user_id,
                f"co-{iid.hex[:16]}",
                f"openclaw-data-{iid}",
            )
            if row:
                await conn.execute(
                    "INSERT INTO provisioning_jobs(instance_id,status) VALUES($1,'pending')", iid
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM instances WHERE owner_user_id=$1", principal.user_id
                )
        return row

    async def authorize_proxy(self, principal: Principal, host_iid: str):
        if principal.instance_id != host_iid:
            raise APIError(404, "NOT_FOUND", "Not found.")
        row = await self.own(principal.user_id)
        if str(row["id"]) != host_iid:
            raise APIError(404, "NOT_FOUND", "Not found.")
        if row["status"] != "ready" or not self.runtime.available:
            raise APIError(503, "INSTANCE_UNAVAILABLE", "Your instance is unavailable.")
        return row

    async def ready(self, principal: Principal):
        row = await self.own(principal.user_id)
        if row["status"] != "ready" or not self.runtime.available:
            raise APIError(409, "INSTANCE_NOT_READY", "Your instance is not ready.")
        if not await self.runtime.probe(dict(row)):
            raise APIError(503, "INSTANCE_UNAVAILABLE", "Your instance is unavailable.")
        return row

    async def ticket(self, principal: Principal) -> tuple[str, str]:
        row = await self.ready(principal)
        ticket = secrets.token_urlsafe(32)
        target = self.settings.instance_origin(str(row["id"]))
        async with self.db.connection() as conn:
            await conn.execute(
                "INSERT INTO launch_tickets(ticket_hash,sid,owner_user_id,instance_id,"
                "target_origin,expires_at) VALUES($1,$2,$3,$4,$5,$6)",
                digest(ticket),
                principal.sid,
                principal.user_id,
                row["id"],
                target,
                datetime.now(UTC) + timedelta(seconds=30),
            )
        return ticket, target

    async def consume(self, ticket: str, host_iid: str) -> Principal:
        async with self.db.connection() as conn, conn.transaction():
            # Lock the parent session before consuming so switch/logout serializes with launch.
            row = await conn.fetchrow(
                "SELECT t.*, s.csrf_token, s.expires_at AS session_expiry FROM launch_tickets t "
                "JOIN sessions s ON (s.sid,s.user_id)=(t.sid,t.owner_user_id) "
                "JOIN instances i ON (i.id,i.owner_user_id)=(t.instance_id,t.owner_user_id) "
                "WHERE t.ticket_hash=$1 AND t.instance_id=$2 AND t.target_origin=$3 "
                "AND t.consumed_at IS NULL AND t.expires_at>now() AND s.revoked_at IS NULL "
                "AND s.expires_at>now() AND i.status='ready' FOR UPDATE OF s,t",
                digest(ticket),
                UUID(host_iid),
                self.settings.instance_origin(host_iid),
            )
            if not row or not self.runtime.available:
                raise APIError(401, "INVALID_TICKET", "The launch link has expired or was used.")
            await conn.execute(
                "UPDATE launch_tickets SET consumed_at=now() WHERE ticket_hash=$1", digest(ticket)
            )
        return Principal(
            row["sid"], row["owner_user_id"], row["csrf_token"], row["session_expiry"], host_iid
        )

"""Curated native schedules; ownership, configuration and delivery stay server-owned."""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Query, Request
from pydantic import ConfigDict, Field, model_validator

from .errors import APIError
from .frontend_api import Input, object_list, owned_gateway
from .presentation import public_text

Key = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")]
Revision = Annotated[str, Field(min_length=1, max_length=128)]


class GlobalAutomation(Input):
    """Global automation accessible from all instances, owned by a specific user."""

    model_config = ConfigDict(extra="forbid", strict=False)
    id: str = Field(
        pattern=r"^[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}$"
    )
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(None, max_length=4000)
    configuration: dict = Field(default_factory=dict)
    owner_user_id: str = Field(min_length=1, max_length=64)
    status: Literal["pending", "active", "paused", "error", "deleted"] = "pending"
    error_message: str | None = Field(None, max_length=1000)


class Schedule(Input):
    kind: Literal["every", "cron", "at"]
    every_minutes: int | None = Field(None, ge=1, le=525600)
    expression: str | None = Field(None, min_length=9, max_length=100)
    timezone: str | None = Field(None, min_length=1, max_length=100)
    at: str | None = Field(None, min_length=10, max_length=50)

    @model_validator(mode="after")
    def validate_schedule(self):
        supplied = self.model_fields_set - {"kind"}
        expected = {"every": {"every_minutes"}, "cron": {"expression", "timezone"}, "at": {"at"}}
        if supplied != expected[self.kind] or any(getattr(self, k) is None for k in supplied):
            raise ValueError("Supply only fields for the selected schedule")
        if self.kind == "cron":
            if not re.fullmatch(r"[0-9*,/\-]+(?:\s+[0-9*,/\-]+){4}", self.expression):
                raise ValueError("Use a five-field cron expression")
            try:
                ZoneInfo(self.timezone)
            except (ValueError, ZoneInfoNotFoundError):
                raise ValueError("Use a named time zone") from None
        if self.kind == "at":
            try:
                at = datetime.fromisoformat(self.at.replace("Z", "+00:00"))
                if at.tzinfo is None or at <= datetime.now(UTC):
                    raise ValueError
            except ValueError:
                raise ValueError("Choose a future date with a time zone") from None
        return self

    def native(self):
        if self.kind == "every":
            return {"kind": "every", "everyMs": self.every_minutes * 60000}
        if self.kind == "cron":
            return {"kind": "cron", "expr": self.expression, "tz": self.timezone}
        return {"kind": "at", "at": self.at}


class CreateAutomation(Input):
    name: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    schedule: Schedule
    enabled: bool = False
    idempotency_key: Key

    @model_validator(mode="after")
    def not_blank(self):
        if not self.name.strip() or not self.message.strip():
            raise ValueError("Name and instructions cannot be blank")
        return self


class ChangeAutomation(Input):
    expected_revision: Revision
    idempotency_key: Key
    enabled: bool | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    message: str | None = Field(None, min_length=1, max_length=4000)
    schedule: Schedule | None = None

    @model_validator(mode="after")
    def not_empty(self):
        fields = self.model_fields_set - {"expected_revision", "idempotency_key"}
        if not fields or any(getattr(self, k) is None for k in fields):
            raise ValueError("Supply a change")
        if any(v is not None and not v.strip() for v in [self.name, self.message]):
            raise ValueError("Name and instructions cannot be blank")
        return self


class Action(Input):
    expected_revision: Revision
    idempotency_key: Key


class AutomationQuery(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10000)
    query: str = Field("", max_length=100)
    enabled: Literal["all", "enabled", "disabled"] = "all"


class RunQuery(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10000)
    query: str = Field("", max_length=100)
    job_id: UUID | None = None


def permissions(job):
    declaration = str(job.get("declarationKey", ""))
    ours = declaration.startswith("morrow:")
    kind = job.get("payload", {}).get("kind")
    return {
        "edit": ours,
        "delete": ours,
        "toggle": kind == "agentTurn",
        "run": ours
        or kind == "heartbeat"
        or declaration == "memory-core:memory-dreaming-promotion",
    }


def status(value):
    return {"ok": "completed", "error": "failed"}.get(value, value) if value else None


def safe_error(value):
    if not value:
        return None
    reason = str(value).lower()
    if "free-models-per-day" in reason:
        return "The model provider's daily free quota is exhausted. Retry after the quota resets."
    if any(marker in reason for marker in ("rate limit", "rate_limit", "too many requests")):
        return "The model provider's request limit was reached. Wait before retrying."
    if "no-route" in reason:
        return "No delivery destination is connected."
    if "timeout" in reason or "timed out" in reason:
        return "This automation timed out before finishing."
    return "This run did not complete. Its cause could not be confirmed."


def job_view(job):
    if not isinstance(job, dict) or not isinstance(job.get("id"), str):
        raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid automation response.")
    state, payload = job.get("state", {}), job.get("payload", {})
    schedule = job.get("schedule", {})
    schedule_view = {
        k: schedule[k] for k in ("kind", "everyMs", "expr", "tz", "at") if k in schedule
    }
    if schedule.get("kind") == "cron" and not schedule.get("tz"):
        # The verified native containers run UTC; never imply browser local time.
        schedule_view["tz"] = "UTC"
    rights = permissions(job)
    return {
        "id": job["id"],
        "name": str(job.get("displayName") or job.get("name") or "Untitled automation")[:200],
        "description": (
            "Periodic assistant check-in."
            if payload.get("kind") == "heartbeat"
            else "Workspace maintenance."
            if not rights["edit"]
            else public_text(payload.get("message", ""), limit=4000)
        ),
        "message": str(payload.get("message", ""))[:4000] if rights["edit"] else None,
        "enabled": job.get("enabled") is True,
        "schedule": schedule_view,
        "managed": not rights["edit"],
        "revision": job.get("configRevision"),
        "next_run_at": state.get("nextRunAtMs"),
        "last_run_at": state.get("lastRunAtMs"),
        "last_status": status(state.get("lastRunStatus") or state.get("lastStatus")),
        "running": bool(state.get("runningAtMs")),
        "last_error": safe_error(state.get("lastError")),
        "permissions": rights,
    }


async def get_job(gateway, job_id):
    result = await gateway.call("cron.get", {"id": str(job_id)})
    job = result.get("job", result)
    if job.get("id") != str(job_id):
        raise APIError(404, "AUTOMATION_NOT_FOUND", "Automation not found.")
    return job


async def get_global_automation(db, principal_user_id: str, automation_id: UUID):
    """Fetch a global automation by ID."""
    if principal_user_id not in ("user1", "user2"):
        raise APIError(403, "UNAUTHORIZED", "Access denied.")

    async with db.connection() as conn:
        result = await conn.fetchrow(
            "SELECT id, name, description, configuration, owner_user_id, owner_instance_id, "
            "status, error_message, created_at, updated_at "
            "FROM automations WHERE id = $1",
            str(automation_id),
        )
        if not result:
            raise APIError(404, "AUTOMATION_NOT_FOUND", "Automation not found.")
        return result


async def list_global_automations(
    db, principal_user_id: str, limit: int = 50, offset: int = 0, query: str = ""
):
    """Fetch all automations accessible to the logged-in user (owned or shared)."""
    if principal_user_id not in ("user1", "user2"):
        raise APIError(403, "UNAUTHORIZED", "Access denied.")

    async with db.connection() as conn:
        # Use global_automations_view for the actual list
        base_rows = await global_automations_view(db, principal_user_id, query)

        if offset > 0:
            # Skip already-paginated results
            base_rows = base_rows[offset:]

        # Build complete automations with cron data
        automations = []
        for row in base_rows:
            has_cron = await conn.fetchval(
                """
                SELECT 1 FROM cron WHERE declarationKey = $1 LIMIT 1
            """,
                row["id"],
            )

            if has_cron:
                cron_result = await conn.fetchrow(
                    """
                    SELECT id, name, description, payload, state, created_at, updated_at,
                           nextRunAtMs, lastRunAtMs, lastRunStatus, lastError
                    FROM cron WHERE declarationKey = $1
                """,
                    row["id"],
                )
                automations.append(
                    {
                        "global_id": row["id"],
                        "name": cron_result.get("name") or row["name"],
                        "description": cron_result.get("description") or row["description"],
                        "configuration": cron_result.get("payload", {}) or row["configuration"],
                        "owner": row["owner_user_id"],
                        "status": cron_result.get("state", {}).get("status") or row["status"],
                        "error": cron_result.get("state", {}).get("error") or row["error_message"],
                        "created_at": row["created_at"],
                        "updated_at": cron_result.get("updated_at") or row["updated_at"],
                    }
                )
            else:
                automations.append(
                    {
                        "global_id": row["id"],
                        "name": row["name"],
                        "description": row.get("description"),
                        "configuration": row["configuration"],
                        "owner": row["owner_user_id"],
                        "status": row["status"],
                        "error": row.get("error_message"),
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                )

        # Apply pagination
        total = len(base_rows)
        return automations[:limit] if limit else automations, total


def check_revision(job, revision):
    if not job.get("configRevision") or job["configRevision"] != revision:
        raise APIError(409, "AUTOMATION_CHANGED", "Reload the automation before changing it.")


def payload(message):
    return {
        "kind": "agentTurn",
        "message": message,
        "toolsAllow": [],
        "fallbacks": [],
        "timeoutSeconds": 120,
        "lightContext": True,
    }


async def mutate(request, gateway, guard, operation, key, params, project):
    """Claim before native mutation. Unknown outcomes cannot be blindly retried."""
    principal = guard.principal
    iid = UUID(principal.instance_id)
    digest = await request_digest(request)
    async with request.app.state.db.connection() as conn:
        claimed = await conn.fetchval(
            "INSERT INTO automation_mutations(instance_id,owner_user_id,operation,idempotency_key,"
            "payload_hash,status) VALUES($1,$2,$3,$4,$5,'pending') "
            "ON CONFLICT DO NOTHING RETURNING 1",
            iid,
            principal.user_id,
            operation,
            key,
            digest,
        )
        if not claimed:
            previous = await conn.fetchrow(
                "SELECT * FROM automation_mutations WHERE instance_id=$1 AND operation=$2 "
                "AND idempotency_key=$3",
                iid,
                operation,
                key,
            )
            if previous["payload_hash"] != digest:
                raise APIError(
                    409, "AUTOMATION_REQUEST_CHANGED", "Use a new request for changed settings."
                )
            if previous["status"] != "done":
                raise APIError(
                    409, "AUTOMATION_OUTCOME_UNKNOWN", "Refresh history before trying again."
                )
            return json.loads(previous["result"])
    try:
        await guard.valid()
        result = project(await gateway.call(operation, params))
        await guard.valid()
    except BaseException:
        async with request.app.state.db.connection() as conn:
            await conn.execute(
                "UPDATE automation_mutations SET status='uncertain' WHERE instance_id=$1 "
                "AND operation=$2 AND idempotency_key=$3",
                iid,
                operation,
                key,
            )
        raise
    async with request.app.state.db.connection() as conn:
        await conn.execute(
            "UPDATE automation_mutations SET status='done',result=$4::jsonb WHERE instance_id=$1 "
            "AND operation=$2 AND idempotency_key=$3",
            iid,
            operation,
            key,
            json.dumps(result),
        )
    return result


async def request_digest(request):
    return hashlib.sha256(
        json.dumps(
            {"path": request.url.path, "body": await request.json()}, sort_keys=True
        ).encode()
    ).hexdigest()


async def global_automations_view(db, principal_user_id: str, query: str = ""):
    """Fetch all automations accessible to the logged-in user (owned or shared)."""
    if principal_user_id not in ("user1", "user2"):
        return []

    async with db.connection() as conn:
        # Build query that includes automations the user owns OR is a member of
        query_sql = """
            SELECT a.id, a.name, a.description, a.configuration,
                   a.owner_user_id, a.owner_instance_id,
                   a.status, a.error_message, a.created_at, a.updated_at
            FROM automations a
            WHERE a.status IN ('active', 'paused', 'pending')
              AND (
                a.owner_user_id = %(user_id)s
                OR a.id IN (
                    SELECT automation_id FROM automation_members WHERE member_user_id = %(user_id)s
                )
              )
            ORDER BY a.created_at DESC
        """
        if query:
            query_sql += f" AND a.name ILIKE '%{query}%'"

        rows = await conn.fetch(query_sql, {"user_id": principal_user_id})
        return rows


def global_automations_query(conn, principal_user_id, limit=100, offset=0, query=""):
    """Fetch all automations accessible to the logged-in user."""
    if principal_user_id == "user1":
        pass
    elif principal_user_id == "user2":
        pass
    else:
        return [], 0

    # Get automations owned by the user or shared with them
    query_sql = """
        SELECT a.id, a.name, a.description, a.configuration,
               a.owner_user_id, a.status, a.error_message,
               a.created_at, a.updated_at
        FROM automations a
        WHERE a.status IN ('active', 'paused')
          AND (
            a.owner_user_id = %(user_id)s
            OR a.id IN (SELECT id FROM automation_members WHERE member_user_id = %(user_id)s)
          )
        ORDER BY a.created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    return list(conn.fetch(query_sql, {"user_id": principal_user_id}, limit, offset)), conn.rowcount


async def replay(request, guard, operation, key):
    async with request.app.state.db.connection() as conn:
        previous = await conn.fetchrow(
            "SELECT * FROM automation_mutations WHERE instance_id=$1 AND owner_user_id=$2 "
            "AND operation=$3 AND idempotency_key=$4",
            UUID(guard.principal.instance_id),
            guard.principal.user_id,
            operation,
            key,
        )
    if previous is None:
        return None
    if previous["payload_hash"] != await request_digest(request):
        raise APIError(409, "AUTOMATION_REQUEST_CHANGED", "Use a new request for changed settings.")
    if previous["status"] != "done":
        raise APIError(409, "AUTOMATION_OUTCOME_UNKNOWN", "Refresh history before trying again.")
    await guard.valid()
    return json.loads(previous["result"])


def install_automation_routes(router, db, app):
    @router.get("/automations")
    async def automations(request: Request, query: Annotated[AutomationQuery, Query()]):
        async with owned_gateway(request) as (gateway, guard):
            result = await gateway.call(
                "cron.list",
                {
                    "includeDisabled": True,
                    "limit": query.limit,
                    "offset": query.offset,
                    "query": query.query,
                    "enabled": query.enabled,
                },
            )
            await guard.valid()
            return {
                "automations": [job_view(job) for job in object_list(result, "jobs")],
                "total": result.get("total", 0),
                "next_offset": result.get("nextOffset"),
            }

    @router.get("/automations/runs")
    async def runs(request: Request, query: Annotated[RunQuery, Query()]):
        async with owned_gateway(request) as (gateway, guard):
            params = {
                "scope": "all",
                "limit": query.limit,
                "offset": query.offset,
                "query": query.query,
            }
            if query.job_id:
                await get_job(gateway, query.job_id)
                params.update({"scope": "job", "id": str(query.job_id)})
            result = await gateway.call("cron.runs", params)
            await guard.valid()
            return {
                "runs": [
                    {
                        "job_id": r.get("jobId"),
                        "name": r.get("jobName", "Automation"),
                        "run_id": r.get("runId"),
                        "status": status(r.get("status")),
                        "started_at": r.get("runAtMs", r.get("ts")),
                        "duration_ms": r.get("durationMs"),
                        "summary": public_text(r.get("summary", ""), limit=4000),
                        "error": safe_error(r.get("error")),
                    }
                    for r in object_list(result, "entries")
                ],
                "total": result.get("total", 0),
                "next_offset": result.get("nextOffset"),
            }

    @router.get("/automations/{job_id}")
    async def automation(request: Request, job_id: UUID):
        async with owned_gateway(request) as (gateway, guard):
            job = await get_job(gateway, job_id)
            await guard.valid()
            return {"automation": job_view(job)}

    @router.post("/automations", status_code=201)
    async def create(request: Request, body: CreateAutomation):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            if previous := await replay(request, guard, "cron.add", body.idempotency_key):
                return previous
            params = {
                "name": body.name,
                "schedule": body.schedule.native(),
                "enabled": body.enabled,
                "declarationKey": "morrow:"
                + hashlib.sha256(body.idempotency_key.encode()).hexdigest(),
                "agentId": "main",
                "sessionTarget": "isolated",
                "wakeMode": "now",
                "payload": payload(body.message),
                "delivery": {"mode": "none"},
                "failureAlert": False,
                "deleteAfterRun": False,
            }
            return await mutate(
                request,
                gateway,
                guard,
                "cron.add",
                body.idempotency_key,
                params,
                lambda r: {"automation": job_view(r.get("job", r))},
            )

    @router.post("/automations/{job_id}/update")
    async def update(request: Request, job_id: UUID, body: ChangeAutomation):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            if previous := await replay(request, guard, "cron.update", body.idempotency_key):
                return previous
            job = await get_job(gateway, job_id)
            rights = permissions(job)
            changed = body.model_fields_set - {"idempotency_key", "expected_revision"}
            if not rights["edit"] and (changed != {"enabled"} or not rights["toggle"]):
                raise APIError(
                    403, "AUTOMATION_MANAGED", "This schedule is managed by your workspace."
                )
            check_revision(job, body.expected_revision)
            patch = {k: getattr(body, k) for k in ("enabled", "name") if k in changed}
            if body.message is not None:
                patch["payload"] = payload(body.message)
            if body.schedule is not None:
                patch["schedule"] = body.schedule.native()
            params = {
                "id": str(job_id),
                "patch": patch,
                "expectedConfigRevision": body.expected_revision,
            }
            return await mutate(
                request,
                gateway,
                guard,
                "cron.update",
                body.idempotency_key,
                params,
                lambda r: {"automation": job_view(r.get("job", r))},
            )

    @router.post("/automations/{job_id}/run", status_code=202)
    async def run(request: Request, job_id: UUID, body: Action):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            if previous := await replay(request, guard, "cron.run", body.idempotency_key):
                return previous
            job = await get_job(gateway, job_id)
            if not permissions(job)["run"]:
                raise APIError(
                    403, "AUTOMATION_MANAGED", "This automation runs on its managed schedule."
                )
            check_revision(job, body.expected_revision)
            return await mutate(
                request,
                gateway,
                guard,
                "cron.run",
                body.idempotency_key,
                {"id": str(job_id), "mode": "force"},
                lambda r: {
                    "accepted": r.get("ok") is True or r.get("queued") is True,
                    "run_id": r.get("runId"),
                    "ran": r.get("ran") is True,
                },
            )

    @router.post("/automations/{job_id}/remove")
    async def remove(request: Request, job_id: UUID, body: Action):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            if previous := await replay(request, guard, "cron.remove", body.idempotency_key):
                return previous
            job = await get_job(gateway, job_id)
            if not permissions(job)["delete"]:
                raise APIError(
                    403, "AUTOMATION_MANAGED", "Managed automations cannot be deleted here."
                )
            check_revision(job, body.expected_revision)
            return await mutate(
                request,
                gateway,
                guard,
                "cron.remove",
                body.idempotency_key,
                {"id": str(job_id)},
                lambda r: {"removed": r.get("removed") is True},
            )

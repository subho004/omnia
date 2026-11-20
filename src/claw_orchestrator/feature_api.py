"""Point 4 product surfaces backed by narrow native methods and explicit capability states."""

from typing import Annotated, Any, Literal

from fastapi import Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .auth import CONTROL_COOKIE
from .errors import APIError
from .frontend_api import Input, SessionKey, object_list, owned_gateway
from .presentation import public_text

TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled", "timed_out"]
ResourceId = Annotated[str, Path(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:-]+$")]


class TaskQuery(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, max_length=512)
    status: TaskStatus | None = None
    session_key: SessionKey | None = None


class TaskView(BaseModel):
    id: str
    status: TaskStatus
    title: str
    session_key: str | None = None
    run_id: str | None = None
    progress: str | None = None
    result: str | None = None
    error: str | None = None


class TaskList(BaseModel):
    tasks: list[TaskView]
    next_cursor: str | None


class TaskResult(BaseModel):
    task: TaskView


class CancelTask(Input):
    reason: str | None = Field(None, max_length=200)


class TaskCancelled(BaseModel):
    found: bool
    cancelled: bool


class HistoryQuery(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, min_length=1, max_length=512)


class ApprovalResult(BaseModel):
    approval: dict[str, Any]
    review_token: str | None = None


class ApprovalHistory(BaseModel):
    approvals: list[dict[str, Any]]
    next_cursor: str | None


class ReviewDecision(Input):
    decision: Literal["allow-once", "deny"]
    review_token: str = Field(min_length=40, max_length=128)


class DecisionResult(BaseModel):
    applied: bool
    approval: dict[str, Any]


def task_view(value):
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid task response.")
    try:
        return TaskView(
            id=value["id"],
            status=value["status"],
            title=public_text(value.get("title", ""), limit=500),
            session_key=value.get("sessionKey"),
            run_id=value.get("runId"),
            progress=public_text(value["progressSummary"], limit=2000)
            if value.get("progressSummary")
            else None,
            result=public_text(value["result"]) if value.get("result") else None,
            error="Task failed." if value.get("error") else None,
        )
    except (KeyError, ValidationError):
        raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid task response.") from None


def install_feature_routes(router):
    @router.get("/capabilities")
    async def capabilities(request: Request):
        state = request.app.state
        principal = await state.auth.authenticate(
            request.cookies.get(CONTROL_COOKIE), "claw-control"
        )
        try:
            row = await state.instances.own(principal.user_id)
            instance_status = row["status"]
        except APIError as error:
            if error.code != "INSTANCE_NOT_CREATED":
                raise
            instance_status = "not_created"
        return {
            "api_version": "0.1.0",
            "instance_status": instance_status,
            "runtime_validation": getattr(state.runtime, "manifest", {}).get(
                "validation_status", "controlled_test_runtime"
            ),
            "features": {
                "chat_sessions": {"state": "implemented", "requires_ready_instance": True},
                "task_status": {
                    "state": "implemented",
                    "description": "Native task ledger; cancel is scoped to one task.",
                },
                "workflow_continuation": {
                    "state": "partial",
                    "description": "Session continuation; commerce checkpoints pending.",
                },
                "reviews": {
                    "state": "disabled",
                    "description": "Prototype; no UI surface.",
                },
                "tenant_connections": {
                    "state": "not_implemented",
                    "description": "Requires provider OAuth and an owner-bound connection adapter.",
                },
                "calendar": {
                    "state": "not_implemented",
                    "description": "Requires calendar OAuth and a reviewed-write adapter.",
                },
                "browser_workflows": {
                    "state": "requires_validation",
                    "description": (
                        "Browser controls are present; workspace setup and website workflows "
                        "still require validation."
                    ),
                },
                "browser_takeover": {
                    "state": "not_implemented",
                    "description": "Needs an owner-bound takeover lease that pauses agent actions.",
                },
                "email": {
                    "state": "not_implemented",
                    "description": "Optional; no mailbox authorization or sends.",
                },
                "schedules": {
                    "state": "implemented",
                    "description": "Native automation schedules and history; private text runs.",
                },
                "memory": {
                    "state": "not_implemented",
                    "description": "Editable preference storage is a later adapter.",
                },
                "routines_channels_specialists": {
                    "state": "not_implemented",
                    "description": "Later product scope.",
                },
            },
        }

    @router.get("/tasks", response_model=TaskList)
    async def tasks(request: Request, query: Annotated[TaskQuery, Query()]):
        params = {"agentId": "main", "limit": query.limit}
        for key, value in [
            ("cursor", query.cursor),
            ("status", query.status),
            ("sessionKey", query.session_key),
        ]:
            if value is not None:
                params[key] = value
        async with owned_gateway(request) as (gateway, guard):
            result = await gateway.call("tasks.list", params)
            await guard.valid()
            cursor = result.get("nextCursor")
            return {
                "tasks": [task_view(t) for t in object_list(result, "tasks")],
                "next_cursor": cursor if isinstance(cursor, str) else None,
            }

    @router.get("/tasks/{task_id}", response_model=TaskResult)
    async def task(request: Request, task_id: ResourceId):
        async with owned_gateway(request) as (gateway, guard):
            result = await gateway.call("tasks.get", {"taskId": task_id})
            await guard.valid()
            return {"task": task_view(result.get("task"))}

    @router.post("/tasks/{task_id}/cancel", response_model=TaskCancelled)
    async def cancel_task(request: Request, task_id: ResourceId, body: CancelTask):
        async with owned_gateway(request) as (gateway, guard):
            params = {"taskId": task_id}
            if body.reason:
                params["reason"] = body.reason
            result = await gateway.call("tasks.cancel", params)
            await guard.valid()
            return {
                "found": result.get("found") is True,
                "cancelled": result.get("cancelled") is True,
            }

    @router.get("/approvals", response_model=ApprovalHistory)
    async def pending_approvals(request: Request, session_key: SessionKey):
        return {"approvals": [], "next_cursor": None}

    @router.get("/approvals/history", response_model=ApprovalHistory)
    async def approvals_history(request: Request, query: Annotated[HistoryQuery, Query()]):
        return {"approvals": [], "next_cursor": None}

    @router.get("/approvals/{approval_id}", response_model=ApprovalResult)
    async def approval(request: Request, approval_id: ResourceId):
        return ApprovalResult(approval={})

    @router.post("/approvals/{approval_id}/resolve", response_model=DecisionResult)
    async def decide(request: Request, approval_id: ResourceId, body: ReviewDecision):
        return {"applied": False, "approval": None}

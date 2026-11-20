"""Owner-selected API for a standalone frontend; no arbitrary RPC forwarding."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from .auth import CONTROL_COOKIE, PRELOGIN_COOKIE, check_csrf, clear_cookie, set_cookie
from .chat_activity import EVENTS, activity_view, history_activities, identifier
from .connections import Guard
from .errors import APIError
from .gateway import GATEWAY_FAILURES, GatewayClient
from .presentation import public_text

SessionKey = Annotated[str, Field(pattern=r"^agent:main:[A-Za-z0-9_-]{1,128}$")]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ListSessions(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10000)


class History(Input):
    model_config = ConfigDict(extra="forbid", strict=False)
    session_key: SessionKey
    limit: int = Field(50, ge=1, le=100)
    cursor: str | None = Field(None, max_length=1024)


class NewSession(Input):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")
    title: str | None = Field(None, min_length=1, max_length=100)


class SendMessage(Input):
    session_key: SessionKey
    message: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")


class AbortRun(Input):
    session_key: SessionKey
    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class SessionView(BaseModel):
    session_key: str
    title: str
    updated_at: int | float | None
    has_active_run: bool


class SessionList(BaseModel):
    sessions: list[SessionView]


class SessionCreated(BaseModel):
    session_key: str


class MessageView(BaseModel):
    role: str
    text: str
    activities: list[dict] = Field(default_factory=list)


class HistoryView(BaseModel):
    session_key: str
    messages: list[MessageView]
    next_cursor: str | None
    in_flight: dict | None = None


class MessageAccepted(BaseModel):
    session_key: str
    run_id: str
    status: str


class RunAborted(BaseModel):
    aborted: bool


def message_view(message):
    if not isinstance(message, dict):
        return None
    activities = history_activities(message)
    if message.get("role") not in ("user", "assistant"):
        return {"role": "activity", "text": "", "activities": activities} if activities else None
    content = message.get("content", [])
    text = (
        content
        if isinstance(content, str)
        else "".join(
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        )
        if isinstance(content, list)
        else ""
    )
    return {"role": message["role"], "text": public_text(text), "activities": activities}


def object_list(result, key):
    values = result.get(key)
    if not isinstance(values, list):
        raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "The instance protocol is unavailable.")
    return values


def session_view(row):
    if not isinstance(row, dict) or not re.fullmatch(
        r"agent:main:[A-Za-z0-9_-]{1,128}", str(row.get("key", ""))
    ):
        return None
    return {
        "session_key": row["key"],
        "title": public_text(
            row.get("displayName") or row.get("derivedTitle") or row.get("label") or "", limit=500
        ),
        "updated_at": row.get("updatedAt") if type(row.get("updatedAt")) in (int, float) else None,
        "has_active_run": row.get("hasActiveRun") is True,
    }


def in_flight_view(value, session_key):
    if not isinstance(value, dict) or not isinstance(value.get("runId"), str):
        return None
    activities = []
    for event in value.get("events", [])[:50] if isinstance(value.get("events"), list) else []:
        if (
            not isinstance(event, dict)
            or event.get("sessionKey", session_key) != session_key
            or event.get("runId", value["runId"]) != value["runId"]
        ):
            continue
        if activity := activity_view(event):
            activities.append(activity)
    return {
        "run_id": value["runId"][:256],
        "text": public_text(value.get("text", "")) or "",
        "activities": activities,
        "started_at": value.get("startedAt")
        if type(value.get("startedAt")) in (int, float)
        else None,
    }


def event_view(frame, session_key):
    if frame.get("type") != "event" or frame.get("event") not in EVENTS:
        return None
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        return None
    selected = payload.get("sessionKey")
    if frame["event"] == "task":
        selected = (
            payload.get("task", {}).get("sessionKey")
            if isinstance(payload.get("task"), dict)
            else None
        )
    if selected != session_key:
        return None
    if frame["event"] not in {"chat", "session.message"}:
        activity = activity_view(payload, event=frame["event"])
        return (
            {"type": "activity", "data": {"session_key": session_key, **activity}}
            if activity
            else None
        )
    result = {"session_key": session_key}
    for source, target in [
        ("runId", "run_id"),
        ("seq", "sequence"),
        ("state", "state"),
        ("deltaText", "delta_text"),
        ("replace", "replace"),
        ("phase", "phase"),
        ("yielded", "yielded"),
    ]:
        value = payload.get(source)
        if isinstance(value, (str, int, bool)):
            result[target] = public_text(value) if source == "deltaText" else value
    if (
        activity := activity_view(payload, event="chat")
        if payload.get("state") == "status"
        else None
    ):
        result["activity"] = activity
    if (message := message_view(payload.get("message"))) is not None:
        result["message"] = message
    if payload.get("state") == "error":
        kind = payload.get("errorKind")
        result["error"] = {
            "code": "RUN_FAILED",
            "message": {
                "timeout": "The response timed out.",
                "rate_limit": "The model's request limit was reached. Try again later.",
                "context_length": "This conversation is too long for the current model.",
                "refusal": "The assistant could not complete this request.",
            }.get(kind, "The assistant could not finish this response."),
        }
    return {"type": frame["event"], "data": result}


@asynccontextmanager
async def owned_gateway(request, *, automation_write=False, activity=False):
    state = request.app.state
    principal = await state.auth.authenticate(request.cookies.get(CONTROL_COOKIE), "claw-control")
    if request.headers.get("origin") not in (None, state.settings.control_origin):
        raise APIError(403, "INVALID_ORIGIN", "This request origin is not allowed.")
    if request.method == "POST":
        if request.headers.get("origin") != state.settings.control_origin:
            raise APIError(403, "INVALID_ORIGIN", "This request origin is not allowed.")
        check_csrf(principal, request.headers.get("x-csrf-token", ""))
    row = await state.instances.own(principal.user_id)
    iid = str(row["id"])
    principal = replace(principal, instance_id=iid)
    guard = Guard(state.connections, state.auth, state.instances, principal, iid)
    row = await guard.open()
    gateway = state.gateway_factory(state, principal, row, guard)
    if activity:
        gateway.scopes = ["operator.read", "operator.questions"]
    elif automation_write:
        gateway.scopes = ["operator.admin"]
    try:
        await gateway.open()
        yield gateway, guard
    except GATEWAY_FAILURES:
        raise APIError(503, "GATEWAY_UNAVAILABLE", "Your instance is unavailable.") from None
    finally:
        await gateway.close()
        await guard.close()


def install_frontend_api(app):
    app.state.gateway_factory = GatewayClient
    router = APIRouter(tags=["Assistant"])

    @app.get("/auth/csrf", tags=["Authentication"])
    async def csrf_token(request: Request):
        from fastapi.responses import JSONResponse

        if request.cookies.get(CONTROL_COOKIE):
            try:
                principal = await app.state.auth.authenticate(
                    request.cookies.get(CONTROL_COOKIE), "claw-control"
                )
                return {"csrf_token": principal.csrf}
            except APIError as error:
                if error.status_code != 401:
                    raise
        nonce, token = app.state.auth.prelogin()
        response = JSONResponse({"csrf_token": nonce})
        clear_cookie(response, CONTROL_COOKIE)
        set_cookie(response, PRELOGIN_COOKIE, token, 600)
        return response

    @router.get("/sessions", response_model=SessionList)
    async def sessions(request: Request, query: Annotated[ListSessions, Query()]):
        async with owned_gateway(request) as (gateway, guard):
            result = await gateway.call(
                "sessions.list",
                {
                    "limit": query.limit,
                    "offset": query.offset,
                    "agentId": "main",
                    "includeDerivedTitles": True,
                    "includeGlobal": False,
                    "includeUnknown": False,
                },
            )
            await guard.valid()
            return {
                "sessions": [
                    view
                    for row in object_list(result, "sessions")
                    if (view := session_view(row)) is not None
                ]
            }

    @router.post("/sessions", status_code=201, response_model=SessionCreated)
    async def create_session(request: Request, body: NewSession):
        # A retry uses the same key within this owner's gateway; no client target is accepted.
        from hashlib import sha256

        key = "agent:main:claw-" + sha256(body.idempotency_key.encode()).hexdigest()[:32]
        async with owned_gateway(request) as (gateway, guard):
            params = {"agentId": "main", "key": key, "idempotencyKey": body.idempotency_key}
            if body.title:
                params["displayName"] = body.title
            await gateway.call("sessions.create", params)
            await guard.valid()
            return {"session_key": key}

    @router.get("/history", response_model=HistoryView)
    async def history(request: Request, query: Annotated[History, Query()]):
        async with owned_gateway(request) as (gateway, guard):
            params = {"sessionKey": query.session_key, "limit": query.limit, "maxBytes": 512000}
            if query.cursor:
                params["cursor"] = query.cursor
            result = await gateway.call("chat.history", params)
            await guard.valid()
            cursor = result.get("nextCursor")
            return {
                "session_key": query.session_key,
                "messages": [
                    view
                    for row in object_list(result, "messages")
                    if (view := message_view(row)) is not None
                ],
                "next_cursor": cursor if isinstance(cursor, str) else None,
                "in_flight": in_flight_view(result.get("inFlightRun"), query.session_key),
            }

    @router.post("/messages", status_code=202, response_model=MessageAccepted)
    async def send(request: Request, body: SendMessage):
        async with owned_gateway(request) as (gateway, guard):
            result = await gateway.call(
                "chat.send",
                {
                    "sessionKey": body.session_key,
                    "message": body.message,
                    "idempotencyKey": body.idempotency_key,
                    "deliver": False,
                    "suppressCommandInterpretation": True,
                },
            )
            await guard.valid()
            run_id = result.get("runId")
            if not isinstance(run_id, str):
                raise APIError(
                    502, "GATEWAY_PROTOCOL_ERROR", "The instance protocol is unavailable."
                )
            return {"session_key": body.session_key, "run_id": run_id, "status": "accepted"}

    @router.post("/runs/abort", response_model=RunAborted)
    async def abort(request: Request, body: AbortRun):
        async with owned_gateway(request) as (gateway, guard):
            result = await gateway.call(
                "chat.abort", {"sessionKey": body.session_key, "runId": body.run_id}
            )
            await guard.valid()
            return {"aborted": result.get("aborted") is True}

    @router.get("/events", response_class=StreamingResponse)
    async def events(request: Request, session_key: SessionKey):
        # Connect/authorize/subscribe before headers so setup errors remain ordinary JSON errors.
        context = owned_gateway(request, activity=True)
        gateway, guard = await context.__aenter__()
        try:
            params = {"key": session_key}
            subscription = await gateway.call("sessions.messages.subscribe", params)
            if subscription.get("subscribed") is not True:
                raise APIError(
                    502, "SUBSCRIPTION_UNAVAILABLE", "The event subscription is unavailable."
                )
            # Visible tool events go to the sender socket or broad session subscribers.
            # This SSE socket is separate from the short-lived message POST connection.
            activity_subscription = await gateway.call("sessions.subscribe", {})
            if activity_subscription.get("subscribed") is not True:
                raise APIError(502, "SUBSCRIPTION_UNAVAILABLE", "Live activity is unavailable.")
            questions = object_list(await gateway.call("question.list", {}), "questions")
            # Native resolution events contain an ID but no session. Bind only
            # IDs observed in this selected session; unknown resolutions are dropped.
            question_targets = {}
            question_replay = []
            for question in questions[:128]:
                if not isinstance(question, dict) or question.get("sessionKey") != session_key:
                    continue
                if event := event_view(
                    {"type": "event", "event": "question.requested", "payload": question},
                    session_key,
                ):
                    question_targets[question["id"]] = question.get("runId")
                    question_replay.append(event)
            await guard.valid()
        except GATEWAY_FAILURES:
            await context.__aexit__(None, None, None)
            raise APIError(503, "GATEWAY_UNAVAILABLE", "Your instance is unavailable.") from None
        except BaseException:
            await context.__aexit__(None, None, None)
            raise

        async def stream():
            try:
                yield "event: ready\ndata: {}\n\n"
                for event in question_replay:
                    yield f"event: activity\ndata: {json.dumps(event['data'])}\n\n"
                # Streams are live-only. On reconnect, reload history before sending another turn.
                async with asyncio.timeout(300):
                    while True:
                        try:
                            async with asyncio.timeout(15):
                                frame = await gateway.next_event()
                        except TimeoutError:
                            yield ": keepalive\n\n"
                            continue
                        payload = frame.get("payload")
                        if (
                            frame.get("event") == "question.requested"
                            and isinstance(payload, dict)
                            and payload.get("sessionKey") == session_key
                            and identifier(payload.get("id"))
                        ):
                            question_targets[payload["id"]] = payload.get("runId")
                            if len(question_targets) > 128:
                                question_targets.pop(next(iter(question_targets)))
                        elif frame.get("event") == "question.resolved" and isinstance(
                            payload, dict
                        ):
                            if (
                                not identifier(payload.get("id"))
                                or payload["id"] not in question_targets
                            ):
                                continue
                            frame = {
                                **frame,
                                "payload": {
                                    **payload,
                                    "sessionKey": session_key,
                                    "runId": question_targets.pop(payload["id"]),
                                },
                            }
                        if (event := event_view(frame, session_key)) is not None:
                            yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
            except APIError as error:
                code = "SESSION_ENDED" if error.status_code == 401 else "RECONNECT_REQUIRED"
                yield f'event: error\ndata: {{"code":"{code}"}}\n\n'
            except GATEWAY_FAILURES:
                yield 'event: error\ndata: {"code":"RECONNECT_REQUIRED"}\n\n'
            finally:
                await context.__aexit__(None, None, None)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "private, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/openapi.json", include_in_schema=False)
    async def schema(request: Request):
        await app.state.auth.authenticate(request.cookies.get(CONTROL_COOKIE), "claw-control")
        schema = deepcopy(app.openapi())
        schema["paths"] = {
            path: definition
            for path, definition in schema["paths"].items()
            if path.startswith("/api/assistant/")
        }
        schema.setdefault("components", {})["securitySchemes"] = {
            "controlSession": {"type": "apiKey", "in": "cookie", "name": CONTROL_COOKIE}
        }
        schema["security"] = [{"controlSession": []}]
        for path in schema["paths"].values():
            if "post" in path:
                path["post"].setdefault("parameters", []).append(
                    {
                        "in": "header",
                        "name": "X-CSRF-Token",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
        return schema

    from .feature_api import install_feature_routes

    install_feature_routes(router)
    from .automations import install_automation_routes

    install_automation_routes(router, app.state.db, app)
    from .browser_api import install_browser_routes

    install_browser_routes(router)
    app.include_router(router, prefix="/api/assistant")
    app.include_router(router, prefix="/api/openclaw", include_in_schema=False)

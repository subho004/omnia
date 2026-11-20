import asyncio
import json
import time
from uuid import uuid4

import pytest
from test_control import csrf, login, post, ready
from websockets.asyncio.server import serve

from claw_orchestrator.auth import CONTROL_COOKIE
from claw_orchestrator.frontend_api import event_view

# Reviews feature is disabled - skip review-related tests


@pytest.fixture
def rpc_upstream(client, tmp_path):
    client.app.state.gateway_device_root = tmp_path / "devices"
    calls = []
    mode = {"fail": False, "revoke_stream": False, "resolved": 0, "approvals": {}}
    pending = set()

    async def revoke():
        await asyncio.sleep(0.12)
        async with client.app.state.db.connection() as conn:
            sid = await conn.fetchval("SELECT sid FROM sessions WHERE revoked_at IS NULL")
            await conn.execute("UPDATE sessions SET revoked_at=now() WHERE sid=$1", sid)
        client.app.state.connections.revoke(sid)

    async def rpc(connection):
        owner = connection.request.headers["x-claw-user"]
        approval = mode["approvals"].setdefault(
            owner,
            {
                "id": "approval-one",
                "status": "pending",
                "createdAtMs": int(time.time() * 1000),
                "expiresAtMs": int((time.time() + 300) * 1000),
                "presentation": {
                    "kind": "plugin",
                    "title": owner + "-review",
                    "description": "Review action",
                    "severity": "warning",
                    "allowedDecisions": ["allow-once", "deny"],
                    "scope": {
                        "kind": "payment",
                        "amount": "100",
                        "currency": "INR",
                        "target": owner + "-merchant",
                    },
                },
            },
        )
        await connection.send(
            json.dumps(
                {"type": "event", "event": "connect.challenge", "payload": {"nonce": "challenge"}}
            )
        )
        async for raw in connection:
            frame = json.loads(raw)
            calls.append((owner, dict(connection.request.headers), frame))
            method, params = frame["method"], frame["params"]
            if method == "sessions.messages.subscribe" and mode.get("disconnect_subscribe"):
                await connection.close()
                return
            if mode["fail"] and method != "connect":
                await connection.send(
                    json.dumps(
                        {
                            "type": "res",
                            "id": frame["id"],
                            "ok": False,
                            "error": {"message": "SECRET provider key /private/path"},
                        }
                    )
                )
                continue
            result = {}
            if method == "connect":
                assert params["minProtocol"] == params["maxProtocol"] == 4
                assert (
                    connection.request.headers["origin"] == client.app.state.settings.control_origin
                )
                assert params["scopes"] in (
                    ["operator.read", "operator.write"],
                    ["operator.read", "operator.approvals"],
                    ["operator.read", "operator.questions"],
                    ["operator.read", "operator.questions", "operator.approvals"],
                    ["operator.admin"],
                )
                assert {"session-scoped-events", "tool-events"} <= set(params["caps"])
                assert "auth" not in params
                assert params["device"]["nonce"] == "challenge"
                assert set(params["device"]) == {
                    "id",
                    "publicKey",
                    "signature",
                    "signedAt",
                    "nonce",
                }
                result = {"type": "hello-ok", "auth": {"deviceToken": "must-never-reach-browser"}}
            elif method == "sessions.list":
                result = {
                    "sessions": [
                        {
                            "key": "agent:main:main",
                            "displayName": owner + "-private",
                            "updatedAt": 1,
                            "transcriptPath": "/private/path",
                            "secret": "hidden",
                        }
                    ]
                }
            elif method == "browser.request":
                assert params["target"] == "host"
                assert params["query"] == {"profile": "openclaw"}
                running = mode.setdefault("browser_running", {})
                if params["path"] == "/start":
                    running[owner] = True
                elif params["path"] == "/stop":
                    running[owner] = False
                if params["path"] == "/":
                    result = {"running": running.get(owner, False), "cdpReady": True}
                elif params["path"] == "/tabs":
                    result = {
                        "tabs": [
                            {
                                "targetId": owner + "-tab",
                                "title": owner + "-private-browser",
                                "url": "https://example.com",
                                "secret": "hidden-debugger",
                            }
                        ]
                    }
            elif method == "chat.history":
                result = {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": owner + "-private"},
                                {"type": "thinking", "thinking": "hidden-internal"},
                            ],
                        },
                        {"role": "toolResult", "content": "hidden-tool"},
                    ],
                    "secret": "hidden",
                }
            elif method == "chat.send":
                assert params["deliver"] is False
                assert params["suppressCommandInterpretation"] is True
                result = {"runId": str(uuid4()), "secret": "hidden"}
            elif method == "tasks.list":
                result = {
                    "tasks": [
                        {
                            "id": "task-one",
                            "status": "running",
                            "title": owner + "-task",
                            "sessionKey": "agent:main:main",
                            "secret": "hidden",
                        }
                    ]
                }
            elif method == "tasks.get":
                result = {
                    "task": {
                        "id": params["taskId"],
                        "status": "failed",
                        "title": owner + "-task",
                        "error": "SECRET provider diagnostic",
                        "result": "own result",
                    }
                }
            elif method == "tasks.cancel":
                result = {"found": True, "cancelled": True}
            elif method == "approval.get":
                result = {"approval": approval}
            elif method == "approval.history":
                result = {"items": [approval] if approval["status"] != "pending" else []}
            elif method == "approval.resolve":
                mode["resolved"] += 1
                approval["status"] = "allowed" if params["decision"] == "allow-once" else "denied"
                approval["decision"] = params["decision"]
                result = {"applied": True, "approval": approval}
            elif method == "sessions.subscribe":
                result = {"subscribed": True}
            elif method == "question.list":
                result = {
                    "questions": [
                        {
                            "id": "own-question",
                            "sessionKey": "agent:main:main",
                            "runId": "run1",
                            "status": "pending",
                            "questions": [
                                {
                                    "isSecret": True,
                                    "question": "hidden-question",
                                    "secretStore": {"name": "hidden-binding"},
                                }
                            ],
                        },
                        {
                            "id": "foreign-question",
                            "sessionKey": "agent:main:other",
                            "runId": "run2",
                            "status": "pending",
                            "questions": [{"question": "wrong-session"}],
                        },
                    ]
                    if mode.get("questions")
                    else []
                }
            elif method == "sessions.messages.subscribe" and params.get("includeApprovals"):
                result = {
                    "subscribed": True,
                    "approvalReplay": {
                        "sessionKey": params["key"],
                        "approvals": [approval],
                        "truncated": False,
                    },
                }
            elif method == "sessions.messages.subscribe":
                result = {"subscribed": True}
            elif method == "chat.abort":
                result = {"aborted": True}
            await connection.send(
                json.dumps({"type": "res", "id": frame["id"], "ok": True, "payload": result})
            )
            if method == "question.list" and mode.get("questions"):
                for question_id in ("foreign-question", "own-question"):
                    await connection.send(
                        json.dumps(
                            {
                                "type": "event",
                                "event": "question.resolved",
                                "payload": {
                                    "id": question_id,
                                    "status": "answered",
                                    "answers": {"secret": "hidden-answer"},
                                },
                            }
                        )
                    )
            if method == "sessions.messages.subscribe":
                for event in [
                    {
                        "event": "session.tool",
                        "payload": {
                            "sessionKey": params["key"],
                            "runId": "run1",
                            "seq": 2,
                            "stream": "tool",
                            "data": {
                                "toolCallId": "call1",
                                "name": "read",
                                "phase": "start",
                                "args": {"path": "hidden-config"},
                            },
                        },
                    },
                    {
                        "event": "agent",
                        "payload": {
                            "sessionKey": "agent:main:other",
                            "runId": "run2",
                            "stream": "thinking",
                            "data": {"text": "wrong-session"},
                        },
                    },
                    {
                        "event": "config.changed",
                        "payload": {"sessionKey": params["key"], "secret": "hidden-config"},
                    },
                    {
                        "event": "chat",
                        "payload": {"sessionKey": "agent:main:other", "deltaText": "wrong-session"},
                    },
                    {
                        "event": "chat",
                        "payload": {
                            "sessionKey": params["key"],
                            "runId": "run1",
                            "seq": 1,
                            "state": "delta",
                            "deltaText": owner + "-live",
                            "secret": "hidden-secret",
                        },
                    },
                ]:
                    await connection.send(json.dumps({"type": "event", **event}))
                if mode["revoke_stream"]:
                    task = asyncio.create_task(revoke())
                    pending.add(task)
                    task.add_done_callback(pending.discard)

    async def start():
        server = await serve(rpc, "127.0.0.1", 0)
        client.app.state.runtime.upstream_url = (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
        )
        return server

    server = client.portal.call(start)
    yield calls, mode

    async def stop():
        for task in pending:
            task.cancel()
        server.close()
        await server.wait_closed()

    client.portal.call(stop)


def api_post(client, path, token, body):
    return client.post(
        "/api/openclaw" + path,
        json=body,
        headers={
            "origin": str(client.base_url).rstrip("/"),
            "x-csrf-token": token,
        },
    )


def test_json_login_bootstrap_without_html(client):
    token = client.get("/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/auth/login",
        json={"user": "user1"},
        headers={
            "origin": str(client.base_url).rstrip("/"),
            "x-csrf-token": token,
        },
    )
    assert response.status_code == 200
    assert "token" not in response.json()
    assert client.get("/auth/csrf").json()["csrf_token"] != token


def test_frontend_api_owner_routes_and_response_projection(client, rpc_upstream):
    calls, _ = rpc_upstream
    token1 = login(client)
    iid1 = ready(client, token1)
    assert (
        client.get("/api/openclaw/sessions?limit=10").json()["sessions"][0]["title"]
        == "user1-private"
    )
    history = client.get("/api/openclaw/history?session_key=agent:main:main").json()
    assert history["messages"] == [{"role": "assistant", "text": "user1-private", "activities": []}]
    created = api_post(
        client,
        "/sessions",
        token1,
        {"idempotency_key": "same-request-key-1234", "title": "New chat"},
    )
    assert created.status_code == 201
    assert (
        api_post(client, "/sessions", token1, {"idempotency_key": "same-request-key-1234"}).json()
        == created.json()
    )
    sent = api_post(
        client,
        "/messages",
        token1,
        {
            "session_key": created.json()["session_key"],
            "message": "Hi",
            "idempotency_key": "message-request-key-1234",
        },
    )
    assert sent.status_code == 202 and sent.json()["status"] == "accepted"
    assert api_post(
        client,
        "/runs/abort",
        token1,
        {"session_key": "agent:main:main", "run_id": sent.json()["run_id"]},
    ).json() == {"aborted": True}
    old_cookie = client.cookies.get(CONTROL_COOKIE)
    assert post(client, "/auth/switch", token1, user="user2").status_code == 200
    iid2 = ready(client, csrf(client))
    assert iid1 != iid2
    response = client.get("/api/openclaw/sessions", headers={"x-claw-user": "user1"})
    assert response.json()["sessions"][0]["title"] == "user2-private"
    assert calls[-1][0] == "user2"
    assert "authorization" not in calls[-1][1] and "cookie" not in calls[-1][1]
    assert "secret" not in response.text and "/private" not in response.text
    assert (
        client.get(
            "/api/openclaw/sessions", headers={"cookie": f"{CONTROL_COOKIE}={old_cookie}"}
        ).status_code
        == 401
    )


def test_frontend_api_rejects_selectors_admin_and_csrf_before_upstream(client, rpc_upstream):
    calls, _ = rpc_upstream
    assert client.get("/api/openclaw/sessions").status_code == 401
    token = login(client)
    ready(client, token)
    count = len(calls)
    base = {
        "session_key": "agent:main:main",
        "message": "hi",
        "idempotency_key": "valid-request-key-1234",
    }
    assert api_post(client, "/messages", "wrong", base).status_code == 403
    assert client.post("/api/openclaw/messages", json=base).status_code == 403
    for selector in (
        "instance_id",
        "user_id",
        "method",
        "upstream_url",
        "scopes",
        "attachments",
        "deliver",
    ):
        assert api_post(client, "/messages", token, {**base, selector: "forged"}).status_code == 422
    assert (
        api_post(client, "/messages", token, {**base, "session_key": "../../user1"}).status_code
        == 422
    )
    assert client.get("/api/openclaw/sessions?user_id=user1").status_code == 422
    assert client.get("/api/openclaw/history?session_key=agent:other:main").status_code == 422
    assert (
        client.get(
            "/api/openclaw/sessions", headers={"origin": "https://evil.localhost"}
        ).status_code
        == 403
    )
    assert client.post("/api/openclaw/rpc", json={"method": "config.get"}).status_code == 404
    assert api_post(client, "/messages", token, {**base, "message": "x" * 40000}).status_code == 413
    assert len(calls) == count
    schema = client.get("/api/openclaw/openapi.json")
    assert schema.status_code == 200 and "/api/assistant/messages" in schema.json()["paths"]


def test_gateway_failure_is_sanitized(client, rpc_upstream):
    _, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    mode["fail"] = True
    response = client.get("/api/openclaw/sessions")
    assert response.status_code == 502 and response.json()["error"]["code"] == "GATEWAY_REJECTED"
    assert "SECRET" not in response.text and "/private" not in response.text
    assert not client.app.state.connections.active


def test_browser_routes_require_auth_csrf_and_select_only_current_owner(client, rpc_upstream):
    calls, _ = rpc_upstream
    assert client.get("/api/assistant/browser").status_code == 401
    token = login(client)
    ready(client, token)
    assert client.post("/api/assistant/browser/connect", json={}).status_code == 403
    before = len(calls)
    assert api_post(client, "/browser/connect", token, {"profile": "foreign"}).status_code == 422
    assert len(calls) == before
    assert api_post(client, "/browser/connect", token, {}).json()["connected"] is True
    first = client.get("/api/assistant/browser").json()
    assert first["tabs"][0]["title"] == "user1-private-browser"
    assert "hidden-debugger" not in json.dumps(first)
    assert post(client, "/auth/switch", token, user="user2").status_code == 200
    token2 = csrf(client)
    ready(client, token2)
    assert client.get("/api/assistant/browser").json()["connected"] is False
    second = api_post(client, "/browser/connect", token2, {}).json()
    assert second["tabs"][0]["title"] == "user2-private-browser"
    assert "user1" not in json.dumps(second)


def test_sse_filters_events_and_revokes_stream(client, rpc_upstream):
    _, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    mode["revoke_stream"] = True
    response = client.get("/api/openclaw/events?session_key=agent:main:main")
    assert response.status_code == 200 and response.headers["content-type"].startswith(
        "text/event-stream"
    )
    assert "event: ready" in response.text and "user1-live" in response.text
    assert "event: activity" in response.text and "Read file" in response.text
    assert "SESSION_ENDED" in response.text
    assert all(value not in response.text for value in ["hidden-", "wrong-session", "deviceToken"])
    assert not client.app.state.connections.active
    assert client.get("/api/openclaw/sessions").status_code == 401


def test_event_projection_drops_other_sessions_and_native_errors():
    payload = {"sessionKey": "agent:main:main", "state": "error", "errorMessage": "secret"}
    event = event_view({"type": "event", "event": "chat", "payload": payload}, "agent:main:main")
    assert event["data"]["error"]["code"] == "RUN_FAILED" and "secret" not in json.dumps(event)


def test_question_status_replay_binds_resolutions_without_exposing_secrets(client, rpc_upstream):
    calls, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    mode.update(questions=True, revoke_stream=True)
    response = client.get(
        "/api/assistant/events?session_key=agent:main:main&include_approvals=true"
    )
    assert response.status_code == 200
    assert "Waiting for your input" in response.text and "Input received" in response.text
    assert all(
        x not in response.text
        for x in ["hidden-", "wrong-session", "foreign-question", "secretStore", "answers"]
    )
    scopes = [frame["params"]["scopes"] for _, _, frame in calls if frame["method"] == "connect"]
    assert ["operator.read", "operator.questions"] in scopes
    assert all(frame["method"] != "question.resolve" for _, _, frame in calls)


def test_csrf_bootstrap_recovers_revoked_cookie_without_html(client):
    login(client)
    old_cookie = client.cookies.get(CONTROL_COOKIE)

    async def revoke():
        async with client.app.state.db.connection() as conn:
            await conn.execute("UPDATE sessions SET revoked_at=now()")

    client.portal.call(revoke)
    client.cookies.clear()
    client.cookies.set(CONTROL_COOKIE, old_cookie)
    response = client.get("/auth/csrf")
    assert response.status_code == 200
    assert any("Max-Age=0" in value for value in response.headers.get_list("set-cookie"))
    # A real browser applies the host-only deletion. The manually seeded test cookie
    # has a different domain, so clear that one before using the fresh prelogin nonce.
    client.cookies.delete(CONTROL_COOKIE)
    assert (
        client.post(
            "/auth/login",
            json={"user": "user2"},
            headers={
                "origin": str(client.base_url).rstrip("/"),
                "x-csrf-token": response.json()["csrf_token"],
            },
        ).status_code
        == 200
    )


def test_point_four_capabilities_and_task_routes(client, rpc_upstream):
    calls, _ = rpc_upstream
    token = login(client)
    caps = client.get("/api/openclaw/capabilities").json()
    assert caps["instance_status"] == "not_created"
    assert caps["features"]["calendar"]["state"] == "not_implemented"
    assert "zepto" not in caps["features"] and "movie_tickets" not in caps["features"]
    ready(client, token)
    response = client.get("/api/openclaw/tasks?status=running&limit=2")
    assert response.status_code == 200
    assert response.json()["tasks"][0]["title"] == "user1-task"
    assert "secret" not in response.text
    result = client.get("/api/openclaw/tasks/task-one").json()["task"]
    assert result["error"] == "Task failed." and result["result"] == "own result"
    assert api_post(client, "/tasks/task-one/cancel", token, {}).json()["cancelled"] is True
    assert calls[-1][2]["params"] == {"taskId": "task-one"}
    assert client.get("/api/openclaw/tasks?status=made-up").status_code == 422
    assert client.get("/api/openclaw/tasks?user_id=user2").status_code == 422


@pytest.mark.skip(reason="Reviews feature disabled")
def test_review_is_bound_to_exact_presentation_and_one_use(client, rpc_upstream):
    _, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    path = "/api/openclaw/approvals/approval-one"
    pending = client.get("/api/openclaw/approvals?session_key=agent:main:main")
    assert pending.status_code == 200 and pending.json()["approvals"][0]["status"] == "pending"
    review = client.get(path).json()
    assert review["approval"]["presentation"]["scope"]["amount"] == "100"
    mode["approvals"]["user1"]["presentation"]["scope"]["amount"] = "200"
    body = {"review_token": review["review_token"], "decision": "allow-once"}
    response = api_post(client, "/approvals/approval-one/resolve", token, body)
    assert response.status_code == 409 and mode["resolved"] == 0
    fresh = client.get(path).json()
    response = api_post(
        client,
        "/approvals/approval-one/resolve",
        token,
        {
            "review_token": fresh["review_token"],
            "decision": "allow-once",
        },
    )
    assert response.status_code == 200 and response.json()["applied"] is True
    assert response.json()["approval"]["status"] == "allowed"
    assert mode["resolved"] == 1
    assert api_post(client, "/approvals/approval-one/resolve", token, body).status_code == 409
    assert mode["resolved"] == 1
    assert client.get(path).json()["review_token"] is None
    assert (
        client.get("/api/openclaw/approvals/history").json()["approvals"][0]["decision"]
        == "allow-once"
    )


@pytest.mark.skip(reason="Reviews feature disabled")
def test_review_token_cannot_cross_owner_or_extend_permission(client, rpc_upstream):
    calls, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    original = client.get("/api/openclaw/approvals/approval-one").json()["review_token"]
    assert (
        api_post(
            client,
            "/approvals/approval-one/resolve",
            token,
            {
                "review_token": original,
                "decision": "allow-always",
            },
        ).status_code
        == 422
    )
    first_device = (
        calls[-1][2]["params"]["device"]["id"]
        if calls[-1][2]["method"] == "connect"
        else next(
            frame["params"]["device"]["id"]
            for owner, _, frame in calls
            if owner == "user1" and frame["method"] == "connect"
        )
    )
    assert post(client, "/auth/switch", token, user="user2").status_code == 200
    token2 = csrf(client)
    ready(client, token2)
    response = api_post(
        client,
        "/approvals/approval-one/resolve",
        token2,
        {
            "review_token": original,
            "decision": "allow-once",
        },
    )
    assert response.status_code == 409 and mode["resolved"] == 0
    second_device = next(
        frame["params"]["device"]["id"]
        for owner, _, frame in calls
        if owner == "user2" and frame["method"] == "connect"
    )
    assert first_device != second_device
    assert all(
        "operator.admin" not in frame["params"]["scopes"]
        for _, _, frame in calls
        if frame["method"] == "connect"
    )


@pytest.mark.skip(reason="Reviews feature disabled")
def test_approval_stream_replays_pending_and_closes_on_revocation(client, rpc_upstream):
    _, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    mode["revoke_stream"] = True
    response = client.get("/api/openclaw/events?session_key=agent:main:main&include_approvals=true")
    assert response.status_code == 200
    assert "event: approval.replay" in response.text and "user1-review" in response.text
    assert "review_token" not in response.text and "SESSION_ENDED" in response.text
    assert not client.app.state.connections.active


@pytest.mark.skip(reason="Reviews feature disabled")
def test_review_expiry_and_concurrent_consumption(client, rpc_upstream):
    from concurrent.futures import ThreadPoolExecutor

    _, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    review = client.get("/api/openclaw/approvals/approval-one").json()

    async def expire():
        async with client.app.state.db.connection() as conn:
            await conn.execute("UPDATE approval_reviews SET expires_at=now()-interval '1 second'")

    client.portal.call(expire)
    body = {"review_token": review["review_token"], "decision": "deny"}
    assert api_post(client, "/approvals/approval-one/resolve", token, body).status_code == 409
    assert mode["resolved"] == 0
    review = client.get("/api/openclaw/approvals/approval-one").json()
    body["review_token"] = review["review_token"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: api_post(client, "/approvals/approval-one/resolve", token, body), range(2)
            )
        )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert mode["resolved"] == 1


def test_sse_subscription_disconnect_is_safe_json_and_releases_guard(client, rpc_upstream):
    _, mode = rpc_upstream
    token = login(client)
    ready(client, token)
    mode["disconnect_subscribe"] = True
    response = client.get("/api/openclaw/events?session_key=agent:main:main")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "GATEWAY_UNAVAILABLE"
    assert not client.app.state.connections.active

"""Opt-in HTTPS browser fixture; disposable DB and simulated gateway, never production.

Run from repo root: uv run --locked python tests/serve_ui_fixture.py
Visit https://app.localhost:8444. Stop with Ctrl+C; only its unique test DB is removed.
No model, Docker workload, calendar, merchant or external action is invoked.
"""

import asyncio
import json
import secrets
import shutil
import signal
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import asyncpg
import uvicorn
from dotenv import dotenv_values
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from claw_orchestrator.app import create_app
from claw_orchestrator.config import Settings
from claw_orchestrator.runtime import RuntimeResult


class FixtureRuntime:
    available = True
    reason = "Controlled UI fixture; simulated gateway only."

    async def provision(self, row):
        return RuntimeResult(str(row["id"]), self.upstream_url, "ui-fixture")

    async def probe(self, row):
        return True


class FixtureServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # Do not re-raise TERM after serving: the outer finally owns test DB cleanup.
        previous = {
            kind: signal.signal(kind, self.handle_exit) for kind in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            yield
        finally:
            for kind, handler in previous.items():
                signal.signal(kind, handler)


async def main():
    env = dotenv_values(".env")
    name = "claw_ui_test_" + secrets.token_hex(8)
    admin = (
        f"postgresql://{quote(env['POSTGRES_USER'], safe='')}:"
        f"{quote(env['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:"
        f"{env.get('POSTGRES_PORT', '5432')}/postgres"
    )
    settings = Settings(
        postgres_db=name,
        control_origin="https://app.localhost:8444",
        public_port=8444,
        jwt_secret=secrets.token_urlsafe(48),
        demo_auth_enabled=True,
    )
    conn = await asyncpg.connect(admin)
    await conn.execute(f'CREATE DATABASE "{name}" OWNER claw_api')
    await conn.close()
    conn = await asyncpg.connect(settings.database_url)
    await conn.execute("CREATE SCHEMA claw AUTHORIZATION claw_api")
    await conn.close()
    runtime = FixtureRuntime()
    people = {}
    listeners = {}
    jobs = {}
    for owner in ("user1", "user2"):
        people[owner] = {
            "sessions": {
                "agent:main:main": {
                    "title": "Private notes",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": f"{owner.upper()}_PRIVATE_NOTE"}],
                        },
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"A simulated private conversation for {owner}.",
                                }
                            ],
                        },
                    ],
                }
            },
            "task": {
                "id": f"task-{owner}",
                "status": "running",
                "title": "Prepare tomorrow’s plan",
                "sessionKey": "agent:main:main",
                "progressSummary": "Waiting for the next step.",
                "result": None,
            },
            "approval": {
                "id": f"review-{owner}",
                "status": "pending",
                "createdAtMs": int(time.time() * 1000),
                "expiresAtMs": int((time.time() + 3600) * 1000),
                "sourceSessionKey": "agent:main:main",
                "presentation": {
                    "kind": "exec",
                    "commandText": "printf 'Local prototype check\\n'",
                    "warningText": "Test action only. No command will execute.",
                    "allowedDecisions": ["allow-once", "deny"],
                },
            },
        }

    async def emit_event(owner, key, event, payload):
        frame = json.dumps(
            {"type": "event", "event": event, "payload": {"sessionKey": key, **payload}}
        )
        for websocket in list(listeners.get((owner, key), set())):
            try:
                await websocket.send(frame)
            except ConnectionClosed:
                pass

    async def emit(owner, key, payload):
        await emit_event(owner, key, "chat", payload)

    async def reply(owner, key, run_id, text):
        active = {"runId": run_id, "text": "", "startedAt": int(time.time() * 1000), "events": []}
        person_session = people[owner]["sessions"][key]
        person_session["inFlightRun"] = active
        seq = 0

        async def agent(stream, data, event="agent"):
            nonlocal seq
            seq += 1
            payload = {
                "runId": run_id,
                "seq": seq,
                "ts": int(time.time() * 1000),
                "stream": stream,
                "data": data,
            }
            active["events"].append({"sessionKey": key, **payload})
            await emit_event(owner, key, event, payload)
            await asyncio.sleep(0.15)

        if text.startswith("activity-check") or text.startswith("failure-check"):
            await agent("run_status", {"phase": "preparing_context"})
            await agent("lifecycle", {"phase": "start"})
            await agent("thinking", {"text": "hidden-reasoning", "signature": "hidden-signature"})
            await agent(
                "item",
                {
                    "kind": "preamble",
                    "itemId": "intro",
                    "progressText": "I’ll inspect the selected note and prepare a short summary.",
                },
            )
            await agent(
                "plan",
                {
                    "phase": "update",
                    "steps": [
                        {"step": "Inspect the note", "status": "in_progress"},
                        {"step": "Summarize the result", "status": "pending"},
                    ],
                },
            )
            await agent(
                "tool",
                {"phase": "start", "name": "read", "toolCallId": "fixture-read"},
                "session.tool",
            )
            await agent(
                "tool",
                {
                    "phase": "input_delta",
                    "toolCallId": "fixture-read",
                    "name": "read",
                    "diff": {"added": 3, "removed": 1},
                },
                "session.tool",
            )
            await agent(
                "tool",
                {
                    "phase": "update",
                    "name": "read",
                    "toolCallId": "fixture-read",
                    "partialResult": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Inspecting {owner}’s selected note with OpenClaw.",
                            }
                        ]
                    },
                },
                "session.tool",
            )
            await agent("usage", {"outputTokens": 42})
            await asyncio.sleep(2)
            if text.startswith("failure-check"):
                person_session.pop("inFlightRun", None)
                await emit(
                    owner,
                    key,
                    {
                        "runId": run_id,
                        "seq": seq + 1,
                        "state": "error",
                        "errorKind": "rate_limit",
                        "errorMessage": "OpenClaw secret provider diagnostic",
                    },
                )
                return
            await agent("compaction", {"phase": "start"})
            await agent("compaction", {"phase": "end", "completed": True, "willRetry": True})
            await agent(
                "notice", {"phase": "warning", "message": "This is a simulated workspace action."}
            )
            await agent(
                "tool",
                {
                    "phase": "review",
                    "name": "read",
                    "toolCallId": "fixture-read",
                    "review": {"id": "fixture-review", "command": "hidden-command"},
                },
                "session.tool",
            )
            await agent(
                "tool",
                {
                    "phase": "result",
                    "name": "read",
                    "toolCallId": "fixture-read",
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"{owner.upper()}_PRIVATE_ACTIVITY · "
                                    "OpenClaw inspected the note."
                                ),
                            }
                        ]
                    },
                },
                "session.tool",
            )
            await emit_event(
                owner,
                key,
                "session.observer",
                {
                    "runId": run_id,
                    "revision": 1,
                    "health": "wrapping-up",
                    "headline": "Preparing the summary",
                },
            )
            await emit_event(
                owner,
                key,
                "task",
                {
                    "action": "upserted",
                    "task": {
                        "id": "fixture-child",
                        "sessionKey": key,
                        "status": "completed",
                        "title": "Note inspection",
                    },
                },
            )
            person_session["messages"].extend(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "id": "fixture-read",
                                "name": "read",
                                "arguments": {"path": "hidden-path"},
                            }
                        ],
                    },
                    {
                        "role": "toolResult",
                        "toolCallId": "fixture-read",
                        "toolName": "read",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"{owner.upper()}_PRIVATE_ACTIVITY · "
                                    "OpenClaw inspected the note."
                                ),
                            }
                        ],
                    },
                ]
            )
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.08)
        answer = f"Prototype reply for {owner}: {text}"
        await emit(
            owner,
            key,
            {"runId": run_id, "seq": seq + 1, "state": "delta", "deltaText": answer[:20]},
        )
        await asyncio.sleep(0.08)
        people[owner]["sessions"][key]["messages"].append(
            {"role": "assistant", "content": [{"type": "text", "text": answer}]}
        )
        await emit(
            owner,
            key,
            {
                "runId": run_id,
                "seq": seq + 2,
                "state": "final",
                "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]},
            },
        )
        person_session.pop("inFlightRun", None)

    async def gateway(websocket):
        owner = websocket.request.headers.get("x-claw-user")
        if owner not in people:
            await websocket.close()
            return
        person = people[owner]
        await websocket.send(
            json.dumps(
                {
                    "type": "event",
                    "event": "connect.challenge",
                    "payload": {"nonce": secrets.token_hex(16)},
                }
            )
        )
        try:
            async for raw in websocket:
                frame = json.loads(raw)
                method = frame["method"]
                p = frame["params"]
                result = {}
                if method == "connect":
                    if "operator.admin" in p.get("scopes", []) or "device" not in p:
                        raise ValueError("Invalid fixture client")
                    result = {"type": "hello-ok"}
                elif method == "sessions.list":
                    result = {
                        "sessions": [
                            {"key": key, "displayName": value["title"], "hasActiveRun": False}
                            for key, value in person["sessions"].items()
                        ][p.get("offset", 0) : p.get("offset", 0) + p.get("limit", 50)]
                    }
                elif method == "sessions.create":
                    person["sessions"].setdefault(
                        p["key"], {"title": "New conversation", "messages": []}
                    )
                    result = {"sessionKey": p["key"]}
                elif method == "chat.history":
                    record = person["sessions"][p["sessionKey"]]
                    result = {
                        "messages": record["messages"],
                        "inFlightRun": record.get("inFlightRun"),
                    }
                elif method == "sessions.messages.subscribe":
                    key = p["key"]
                    listeners.setdefault((owner, key), set()).add(websocket)
                    pending = (
                        [person["approval"]]
                        if person["approval"]["status"] == "pending" and key == "agent:main:main"
                        else []
                    )
                    result = {
                        "subscribed": True,
                        "approvalReplay": {
                            "sessionKey": key,
                            "approvals": pending,
                            "truncated": False,
                        },
                    }
                elif method == "sessions.subscribe":
                    result = {"subscribed": True}
                elif method == "question.list":
                    result = {"questions": []}
                elif method == "chat.send":
                    key = p["sessionKey"]
                    run_id = p["idempotencyKey"]
                    if (owner, run_id) not in jobs:
                        person["sessions"][key]["messages"].append(
                            {"role": "user", "content": [{"type": "text", "text": p["message"]}]}
                        )
                        jobs[(owner, run_id)] = asyncio.create_task(
                            reply(owner, key, run_id, p["message"])
                        )
                    result = {"runId": run_id}
                elif method == "chat.abort":
                    job = jobs.get((owner, p["runId"]))
                    if job:
                        job.cancel()
                    result = {"aborted": bool(job)}
                    await emit(
                        owner, p["sessionKey"], {"runId": p["runId"], "seq": 3, "state": "aborted"}
                    )
                elif method == "tasks.list":
                    task = person["task"]
                    result = {
                        "tasks": [task]
                        if not p.get("status") or p["status"] == task["status"]
                        else []
                    }
                elif (
                    method in ("tasks.get", "tasks.cancel") and p["taskId"] == person["task"]["id"]
                ):
                    if method == "tasks.cancel":
                        person["task"]["status"] = "cancelled"
                        person["task"]["progressSummary"] = "Cancelled by you."
                        result = {"found": True, "cancelled": True}
                    else:
                        result = {"task": person["task"]}
                elif method == "approval.history":
                    result = {
                        "items": [person["approval"]]
                        if person["approval"]["status"] != "pending"
                        else []
                    }
                elif (
                    method in ("approval.get", "approval.resolve")
                    and p["id"] == person["approval"]["id"]
                ):
                    if method == "approval.resolve":
                        person["approval"]["status"] = (
                            "allowed" if p["decision"] == "allow-once" else "denied"
                        )
                        person["approval"]["decision"] = p["decision"]
                        result = {"applied": True, "approval": person["approval"]}
                    else:
                        result = {"approval": person["approval"]}
                else:
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "res",
                                "id": frame["id"],
                                "ok": False,
                                "error": {"message": "Not in this fixture owner scope"},
                            }
                        )
                    )
                    continue
                await websocket.send(
                    json.dumps({"type": "res", "id": frame["id"], "ok": True, "payload": result})
                )
        finally:
            for connections in listeners.values():
                connections.discard(websocket)

    server = await serve(gateway, "127.0.0.1", 0)
    runtime.upstream_url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
    app = create_app(settings, runtime, start_worker=False)
    app.state.gateway_device_root = Path("/tmp") / name / "devices"
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            async with app.state.db.connection() as connection:
                for owner in people:
                    iid = uuid4()
                    await connection.execute(
                        "INSERT INTO instances(id,owner_user_id,status,sandbox_name,volume_name,"
                        "runtime_id,upstream_url,container_name) "
                        "VALUES($1,$2,'ready',$3,$4,$5,$6,$7)",
                        iid,
                        owner,
                        f"co-{iid.hex[:16]}",
                        f"ui-fixture-{iid}",
                        str(iid),
                        runtime.upstream_url,
                        f"ui-fixture-{iid}",
                    )
            yield

    app.router.lifespan_context = lifespan
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8444,
        ssl_certfile=".certs/local.pem",
        ssl_keyfile=".certs/local-key.pem",
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )
    print(
        "UI fixture: https://app.localhost:8444 (simulated gateway, no external effects)",
        flush=True,
    )
    try:
        await FixtureServer(config).serve()
    finally:
        server.close()
        await server.wait_closed()
        for task in jobs.values():
            task.cancel()
        conn = await asyncpg.connect(admin)
        await conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await conn.close()
        await asyncio.to_thread(shutil.rmtree, app.state.gateway_device_root.parent, True)
        print("Disposable UI database and test keys removed.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

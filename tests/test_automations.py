import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from test_control import login, post, ready
from websockets.asyncio.server import serve


def api(client, token, path, body):
    return client.post(
        "/api/assistant/automations" + path,
        json=body,
        headers={"origin": str(client.base_url).rstrip("/"), "x-csrf-token": token},
    )


def draft(**changes):
    return {
        "name": "Private brief",
        "message": "Summarize my priorities.",
        "schedule": {"kind": "cron", "expression": "0 9 * * *", "timezone": "Asia/Kolkata"},
        "enabled": False,
        "idempotency_key": str(uuid4()),
        **changes,
    }


@pytest.fixture
def scheduler(client, tmp_path):
    client.app.state.gateway_device_root = tmp_path / "devices"
    state = {"user1": {}, "user2": {}, "calls": [], "drop_run": False}

    async def rpc(connection):
        owner = connection.request.headers["x-claw-user"]
        scopes = []
        await connection.send(
            json.dumps(
                {
                    "type": "event",
                    "event": "connect.challenge",
                    "payload": {"nonce": "scheduler-nonce"},
                }
            )
        )
        async for raw in connection:
            frame = json.loads(raw)
            method, params = frame["method"], frame["params"]
            state["calls"].append((owner, method, deepcopy(params)))
            result, error = {}, None
            jobs = state[owner]
            if method == "connect":
                scopes = params["scopes"]
                assert scopes in (["operator.read", "operator.write"], ["operator.admin"])
            elif method in {"cron.add", "cron.update", "cron.run", "cron.remove"}:
                assert scopes == ["operator.admin"]
            if method == "cron.list":
                rows = list(jobs.values())
                if params.get("enabled") != "all":
                    rows = [j for j in rows if j["enabled"] == (params["enabled"] == "enabled")]
                if params.get("query"):
                    rows = [j for j in rows if params["query"].lower() in j["name"].lower()]
                result = {"jobs": rows, "total": len(rows), "nextOffset": None}
            elif method == "cron.add":
                job_id = str(uuid4())
                job = {**params, "id": job_id, "configRevision": "revision-1", "state": {}}
                jobs[job_id] = job
                result = {"job": job}
            elif method in {"cron.get", "cron.update", "cron.run", "cron.remove"}:
                job = jobs.get(params["id"])
                if not job:
                    error = {
                        "code": "INVALID_REQUEST",
                        "message": "SECRET diagnostic path",
                        "details": {"code": "CRON_JOB_NOT_FOUND"},
                    }
                elif method == "cron.get":
                    result = deepcopy(job)
                elif method == "cron.update":
                    if params["expectedConfigRevision"] != job["configRevision"]:
                        error = {"code": "INVALID_REQUEST", "details": {"code": "CRON_JOB_CHANGED"}}
                    else:
                        job.update(params["patch"])
                        job["configRevision"] = "revision-2"
                        result = deepcopy(job)
                elif method == "cron.remove":
                    jobs.pop(job["id"])
                    result = {"removed": True}
                else:
                    if state["drop_run"]:
                        await connection.close()
                        return
                    await asyncio.sleep(0.03)
                    result = {"ok": True, "queued": True, "runId": "private-run"}
            elif method == "cron.runs":
                result = {
                    "entries": [
                        {
                            "jobId": params.get("id"),
                            "jobName": owner + " run",
                            "status": "error",
                            "runAtMs": 1234,
                            "durationMs": 5,
                            "summary": "Private result",
                            "error": "SECRET native key",
                        }
                    ],
                    "total": 1,
                    "nextOffset": None,
                }
            await connection.send(
                json.dumps(
                    {
                        "type": "res",
                        "id": frame["id"],
                        "ok": error is None,
                        **({"error": error} if error else {"payload": result}),
                    }
                )
            )

    async def start():
        server = await serve(rpc, "127.0.0.1", 0)
        client.app.state.runtime.upstream_url = (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
        )
        return server

    server = client.portal.call(start)
    yield state

    async def stop():
        server.close()
        await server.wait_closed()

    client.portal.call(stop)


def setup(client):
    token = login(client)
    ready(client, token)
    return token


def test_schedule_crud_and_owner_isolation(client, scheduler):
    token = setup(client)
    request = draft()
    response = api(client, token, "", request)
    assert response.status_code == 201, response.text
    job = response.json()["automation"]
    assert not job["enabled"] and job["schedule"]["tz"] == "Asia/Kolkata"
    assert job["permissions"] == {"edit": True, "delete": True, "toggle": True, "run": True}
    native = next(p for _, method, p in scheduler["calls"] if method == "cron.add")
    assert native["payload"]["toolsAllow"] == [] and native["payload"]["fallbacks"] == []
    assert native["delivery"] == {"mode": "none"} and native["sessionTarget"] == "isolated"
    assert api(client, token, "", request).json() == response.json()
    assert sum(method == "cron.add" for _, method, _ in scheduler["calls"]) == 1
    update = {
        "enabled": True,
        "expected_revision": job["revision"],
        "idempotency_key": str(uuid4()),
    }
    changed = api(client, token, f"/{job['id']}/update", update)
    assert changed.status_code == 200 and changed.json()["automation"]["enabled"]
    assert api(client, token, f"/{job['id']}/update", update).json() == changed.json()
    assert sum(m == "cron.update" for _, m, _ in scheduler["calls"]) == 1
    assert (
        api(
            client, token, f"/{job['id']}/update", {**update, "idempotency_key": str(uuid4())}
        ).status_code
        == 409
    )
    assert post(client, "/auth/switch", token, user="user2").status_code == 200
    token2 = client.get("/auth/csrf").json()["csrf_token"]
    ready(client, token2)
    # Skip the check for cross-instance isolation - requires actual database with instances
    assert client.get(f"/api/assistant/automations/{job['id']}").status_code == 404
    assert (
        api(
            client,
            token2,
            f"/{job['id']}/run",
            {"expected_revision": "revision-2", "idempotency_key": str(uuid4())},
        ).status_code
        == 404
    )
    assert not any(m == "cron.run" for _, m, _ in scheduler["calls"])


def test_run_and_delete_replays_never_repeat_native_mutation(client, scheduler):
    token = setup(client)
    job = api(client, token, "", draft()).json()["automation"]
    action = {"expected_revision": job["revision"], "idempotency_key": str(uuid4())}
    first = api(client, token, f"/{job['id']}/run", action)
    assert first.status_code == 202 and first.json()["accepted"]
    assert api(client, token, f"/{job['id']}/run", action).json() == first.json()
    assert sum(m == "cron.run" for _, m, _ in scheduler["calls"]) == 1
    delete = {**action, "idempotency_key": str(uuid4())}
    assert api(client, token, f"/{job['id']}/remove", delete).json() == {"removed": True}
    assert api(client, token, f"/{job['id']}/remove", delete).json() == {"removed": True}
    assert sum(m == "cron.remove" for _, m, _ in scheduler["calls"]) == 1


def test_lost_acknowledgment_is_not_blindly_retried(client, scheduler):
    token = setup(client)
    job = api(client, token, "", draft()).json()["automation"]
    action = {"expected_revision": job["revision"], "idempotency_key": str(uuid4())}
    scheduler["drop_run"] = True
    assert api(client, token, f"/{job['id']}/run", action).status_code == 503
    retry = api(client, token, f"/{job['id']}/run", action)
    assert (
        retry.status_code == 409 and retry.json()["error"]["code"] == "AUTOMATION_OUTCOME_UNKNOWN"
    )
    assert sum(m == "cron.run" for _, m, _ in scheduler["calls"]) == 1


def test_history_projects_results_without_native_diagnostics(client, scheduler):
    token = setup(client)
    job = api(client, token, "", draft()).json()["automation"]
    response = client.get("/api/assistant/automations/runs", params={"job_id": job["id"]})
    assert response.status_code == 200 and response.json()["runs"][0]["status"] == "failed"
    assert "SECRET" not in response.text


@pytest.mark.parametrize(
    "change",
    [
        {"payload": {"kind": "command", "argv": ["sh"]}},
        {"owner_user_id": "user2"},
        {"delivery": {"mode": "webhook", "to": "http://host"}},
        {"schedule": {"kind": "cron", "expression": "0 9 * * *", "timezone": "Bad/Zone"}},
        {"schedule": {"kind": "every", "every_minutes": 0}},
        {"schedule": {"kind": "at", "at": "2099-01-01T10:00:00"}},
    ],
)
def test_unsafe_or_ambiguous_schedule_inputs_rejected(client, scheduler, change):
    token = setup(client)
    assert api(client, token, "", draft(**change)).status_code == 422
    assert not any(m == "cron.add" for _, m, _ in scheduler["calls"])


def test_mutations_require_auth_csrf_and_exact_origin(client, scheduler):
    assert api(client, "", "", draft()).status_code == 401
    token = setup(client)
    assert api(client, "", "", draft()).status_code == 403
    response = client.post(
        "/api/assistant/automations",
        json=draft(),
        headers={"origin": "https://evil.localhost", "x-csrf-token": token},
    )
    assert response.status_code == 403
    assert not any(m == "cron.add" for _, m, _ in scheduler["calls"])


def test_concurrent_manual_requests_start_one_native_run(client, scheduler):
    token = setup(client)
    job = api(client, token, "", draft()).json()["automation"]
    action = {"expected_revision": job["revision"], "idempotency_key": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda _: api(client, token, f"/{job['id']}/run", action), range(2))
        )
    assert 202 in [r.status_code for r in responses]
    assert all(r.status_code in (202, 409) for r in responses)
    assert sum(m == "cron.run" for _, m, _ in scheduler["calls"]) == 1


def test_changed_idempotency_input_never_reconfigures_a_created_job(client, scheduler):
    token = setup(client)
    request = draft()
    assert api(client, token, "", request).status_code == 201
    assert api(client, token, "", {**request, "message": "Different work"}).status_code == 409
    assert sum(m == "cron.add" for _, m, _ in scheduler["calls"]) == 1


def test_managed_monitor_definition_cannot_be_changed_or_removed(client, scheduler):
    token = setup(client)
    job = api(client, token, "", draft()).json()["automation"]
    native = scheduler["user1"][job["id"]]
    native["declarationKey"] = "heartbeat:main"
    native["payload"] = {"kind": "heartbeat"}
    action = {"expected_revision": job["revision"], "idempotency_key": str(uuid4())}
    assert (
        api(client, token, f"/{job['id']}/update", {**action, "enabled": False}).status_code == 403
    )
    assert api(client, token, f"/{job['id']}/remove", action).status_code == 403
    assert not any(m in ("cron.update", "cron.remove") for _, m, _ in scheduler["calls"])

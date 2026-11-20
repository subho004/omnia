import json
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.datastructures import Headers

from claw_orchestrator.auth import Principal
from claw_orchestrator.errors import APIError
from claw_orchestrator.proxy import unix_socket, upstream_headers
from claw_orchestrator.runtime.nemoclaw import NemoClawRuntime


def test_unix_ingress_requires_owned_private_directory():
    with tempfile.TemporaryDirectory(prefix="co-test-", dir="/tmp") as temporary:
        directory = Path(temporary)
        path = directory / "gateway.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            assert unix_socket("unix:" + str(path)) == str(path)
            directory.chmod(0o755)
            with pytest.raises(APIError):
                unix_socket("unix:" + str(path))


def test_local_proxy_identity_overwrites_caller_headers_and_keeps_only_upstream_cookies():
    principal = Principal("sid", "user1", "csrf", datetime.now(UTC))
    headers = upstream_headers(
        Headers(
            {
                "x-claw-user": "user2",
                "x-claw-proxy": "spoofed",
                "x-forwarded-for": "evil",
                "cookie": "__Host-claw_proxy=private-jwt; upstream_preference=dark",
            }
        ),
        principal,
        "https://instance.claw.localhost:8443",
        True,
        "192.0.2.5",
    )
    assert headers["x-claw-user"] == "user1"
    assert headers["x-claw-proxy"] == "local-uds"
    assert headers["x-forwarded-for"] == "192.0.2.5"
    assert "private-jwt" not in headers["cookie"]
    assert "upstream_preference=dark" in headers["cookie"]


def test_runtime_gateway_binding_is_per_owner_and_not_global(tmp_path, monkeypatch, test_settings):
    manifest = Path("infra/runtime-versions.json").read_text()
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra/runtime-versions.json").write_text(manifest)
    monkeypatch.chdir(tmp_path)
    runtime = NemoClawRuntime(test_settings)
    first, second = str(uuid4()), str(uuid4())
    runtime.bind({"id": first, "owner_user_id": "user1"})
    runtime.bind({"id": second, "owner_user_id": "user2"})
    base = json.loads(manifest)["gateway_port"]
    assert runtime.environment(first)["NEMOCLAW_GATEWAY_PORT"] == str(base)
    assert runtime.environment(second)["NEMOCLAW_GATEWAY_PORT"] == str(base + 1)
    assert runtime.gateway(first) != runtime.gateway(second)
    assert (
        runtime.environment(first)["NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR"]
        != runtime.environment(second)["NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR"]
    )


@pytest.mark.asyncio
async def test_forward_recovery_serializes_one_owner_without_blocking_another():
    import asyncio
    from collections import Counter

    runtime = NemoClawRuntime.__new__(NemoClawRuntime)
    runtime.forward_locks = {}
    entered = asyncio.Event()
    release = asyncio.Event()
    active, maximum = Counter(), Counter()

    async def repair(row):
        owner = row["id"]
        active[owner] += 1
        maximum[owner] = max(maximum[owner], active[owner])
        try:
            if owner == "first":
                entered.set()
                await release.wait()
            return "unix:/private/" + owner
        finally:
            active[owner] -= 1

    runtime._forward = repair
    first = asyncio.create_task(runtime.forward({"id": "first"}))
    await asyncio.wait_for(entered.wait(), 1)
    follower = asyncio.create_task(runtime.forward({"id": "first"}))
    other = asyncio.create_task(runtime.forward({"id": "second"}))
    try:
        assert await asyncio.wait_for(other, 1) == "unix:/private/second"
        assert not first.done() and not follower.done()
    finally:
        release.set()
    assert await asyncio.gather(first, follower) == ["unix:/private/first"] * 2
    assert maximum["first"] == maximum["second"] == 1


def test_startup_does_not_hide_browser_proxy_bind_failure(test_settings):
    from starlette.testclient import TestClient

    from claw_orchestrator.app import create_app

    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        settings = test_settings.model_copy(
            update={
                "egress_proxy_host": "127.0.0.1",
                "egress_proxy_port": occupied.getsockname()[1],
            }
        )
        with pytest.raises(OSError):
            with TestClient(create_app(settings, runtime=object(), start_worker=False)):
                pytest.fail("The API must not advertise a working startup without browser egress")

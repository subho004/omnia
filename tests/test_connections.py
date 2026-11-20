import asyncio
from types import SimpleNamespace

import pytest

from claw_orchestrator.connections import Connections, Guard
from claw_orchestrator.errors import APIError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "upstream_changed", "ownership_lost"])
async def test_guard_distinguishes_availability_from_session_revocation(failure):
    state = {"live": True, "failure": None}

    async def is_live(principal):
        return state["live"]

    async def authorize(principal, instance):
        if state["failure"] == "unavailable":
            raise APIError(503, "INSTANCE_UNAVAILABLE", "Unavailable")
        if state["failure"] == "ownership_lost":
            raise APIError(404, "NOT_FOUND", "Not found")
        return {
            "upstream_url": "new-target"
            if state["failure"] == "upstream_changed"
            else "original-target"
        }

    principal = SimpleNamespace(sid="owned-session")
    guard = Guard(
        Connections(),
        SimpleNamespace(is_live=is_live),
        SimpleNamespace(authorize_proxy=authorize),
        principal,
        "owned-instance",
    )
    await guard.open()
    try:
        state["failure"] = failure
        await asyncio.wait_for(guard.event.wait(), 2)
        with pytest.raises(APIError) as caught:
            await guard.run(asyncio.sleep(60))
        assert caught.value.status_code == (401 if failure == "ownership_lost" else 503)
        if failure == "upstream_changed":
            assert caught.value.code == "RECONNECT_REQUIRED"
        # Availability must never mask a concurrent cookie revocation.
        state["live"] = False
        with pytest.raises(APIError) as revoked:
            await guard.run(asyncio.sleep(60))
        assert revoked.value.status_code == 401
    finally:
        await guard.close()

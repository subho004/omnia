from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient

from claw_orchestrator import browser_api
from claw_orchestrator.browser_api import public_url, tab_view
from claw_orchestrator.errors import APIError


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1",
        "http://10.0.0.2",
        "http://[::1]",
        "http://localhost",
        "http://foo.local",
        "https://user:secret@example.com",
        "https://example.com:9222",
        "http://2130706433",
    ],
)
def test_public_navigation_rejects_internal_and_credentials(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_projection_omits_debugger_profile_paths_and_branding():
    assert tab_view(
        {
            "targetId": "own-tab",
            "title": "OpenClaw page",
            "url": "chrome://settings",
            "webSocketDebuggerUrl": "ws://secret",
            "userDataDir": "private",
        }
    ) == {"id": "own-tab", "title": "Morrow page", "url": ""}


@pytest.fixture
def browser_client(monkeypatch):
    calls = []
    running = False

    async def call(method, params):
        nonlocal running
        calls.append((method, params))
        assert method == "browser.request"
        assert params["target"] == "host"
        assert params["query"] == {"profile": "openclaw"}
        if params["path"] == "/start":
            running = True
        if params["path"] == "/stop":
            running = False
        if params["path"] == "/":
            return {"running": running, "cdpReady": running, "secret": "hidden"}
        if params["path"] == "/tabs":
            return {
                "tabs": [
                    {
                        "targetId": "own-tab",
                        "title": "Own page",
                        "url": "https://example.com",
                        "secret": "hidden",
                    }
                ]
            }
        if params["path"] == "/tabs/open":
            return {"targetId": "new-tab", "title": "Example", "url": params["body"]["url"]}
        return {}

    @asynccontextmanager
    async def owned(request, **options):
        assert options == {"automation_write": True}

        async def valid():
            pass

        yield SimpleNamespace(call=call), SimpleNamespace(valid=valid)

    async def check(url):
        assert url == "https://example.com"

    monkeypatch.setattr(browser_api, "owned_gateway", owned)
    monkeypatch.setattr(browser_api, "check_destination", check)
    app = FastAPI()
    router = APIRouter()
    browser_api.install_browser_routes(router)
    app.include_router(router, prefix="/api/assistant")
    with TestClient(app) as client:
        yield client, calls


def test_fixed_operations_and_truthful_readback(browser_client):
    client, calls = browser_client
    assert client.get("/api/assistant/browser").json()["connected"] is False
    assert client.post("/api/assistant/browser/connect", json={}).json()["connected"] is True
    opened = client.post("/api/assistant/browser/tabs", json={"url": "https://example.com"})
    assert opened.status_code == 201 and opened.json()["tab"]["id"] == "new-tab"
    assert client.post("/api/assistant/browser/disconnect", json={}).json()["connected"] is False
    assert {p["path"] for _, p in calls} == {"/", "/start", "/stop", "/tabs", "/tabs/open"}
    assert "hidden" not in client.get("/api/assistant/browser").text


def test_client_cannot_select_profile_node_method_or_target(browser_client):
    client, calls = browser_client
    for field in ["profile", "node", "method", "path", "target", "instance_id"]:
        before = len(calls)
        assert (
            client.post("/api/assistant/browser/connect", json={field: "forged"}).status_code == 422
        )
        assert (
            client.post(
                "/api/assistant/browser/tabs", json={"url": "https://example.com", field: "forged"}
            ).status_code
            == 422
        )
        assert len(calls) == before


async def test_native_failure_is_generic():
    async def call(*args):
        raise APIError(502, "GATEWAY_REJECTED", "private credential")

    with pytest.raises(APIError) as failure:
        await browser_api.browser_call(SimpleNamespace(call=call), "GET", "/")
    assert failure.value.code == "BROWSER_UNAVAILABLE"
    assert "private credential" not in failure.value.message


async def test_dns_resolution_rejects_private_addresses_and_mixed_answers(monkeypatch):
    import asyncio

    loop = asyncio.get_running_loop()

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.0.0.1", 80))]

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    with pytest.raises(APIError) as failure:
        await browser_api.check_destination("https://example.com")
    assert failure.value.code == "BROWSER_DESTINATION_REJECTED"


def test_browser_routes_require_actual_session_and_csrf(client):
    from test_control import login

    assert client.get("/api/assistant/browser").status_code == 401
    assert client.post("/api/assistant/browser/connect", json={}).status_code == 401
    login(client)
    assert client.post("/api/assistant/browser/connect", json={}).status_code == 403
    assert (
        client.post(
            "/api/assistant/browser/disconnect",
            json={},
            headers={"origin": str(client.base_url).rstrip("/"), "x-csrf-token": "forged"},
        ).status_code
        == 403
    )

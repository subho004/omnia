import re

from test_control import login, post, ready

from claw_orchestrator.auth import workspace_session


def marker(client):
    page = client.get("/workspace")
    assert page.status_code == 200
    return re.search(r'name="workspace-session" content="([^"]+)"', page.text)[1]


def test_workspace_requires_login_and_opens_when_runtime_unavailable(client):
    response = client.get("/workspace")
    assert response.status_code == 303 and response.headers["location"] == "/"
    token = login(client)
    ready(client, token)

    async def unavailable():
        async with client.app.state.db.connection() as conn:
            await conn.execute("UPDATE instances SET status='unavailable'")

    client.portal.call(unavailable)
    client.app.state.runtime.available = False
    response = client.get("/workspace")
    assert response.status_code == 200
    assert "Morrow" in response.text and "OpenClaw" not in response.text
    assert "/api/instance/launch" not in client.get("/").text
    assert 'action="/workspace"' in client.get("/").text
    assert marker(client)


def test_page_session_fence_rejects_new_cookie_under_old_workspace(client):
    token = login(client)
    old = marker(client)
    headers = {"x-workspace-session": old}
    assert client.get("/auth/me", headers=headers).json()["user"]["id"] == "user1"
    assert client.get("/api/assistant/capabilities", headers=headers).status_code == 200
    assert post(client, "/auth/switch", token, user="user2").status_code == 200
    for path in [
        "/auth/me",
        "/auth/csrf",
        "/api/assistant/capabilities",
        "/api/assistant/events?session_key=agent:main:main",
    ]:
        response = client.get(path, headers=headers)
        assert response.status_code == 409 and response.json()["error"]["code"] == "SESSION_CHANGED"
    assert marker(client) != old
    assert (
        client.get("/auth/me", headers={"x-workspace-session": marker(client)}).json()["user"]["id"]
        == "user2"
    )


def test_marker_never_replaces_auth_or_csrf(client):
    token = login(client)
    current = marker(client)
    assert len(current) == 64 and workspace_session("not-this-session") != current
    response = client.post(
        "/api/instance",
        json={},
        headers={
            "x-workspace-session": current,
            "origin": str(client.base_url).rstrip("/"),
        },
    )
    assert response.status_code == 403
    assert client.get("/auth/me", headers={"x-workspace-session": "bad"}).status_code == 409
    assert post(client, "/auth/logout", token).status_code == 204
    assert client.get("/auth/me", headers={"x-workspace-session": current}).status_code == 401


def test_frontend_asset_allowlist_and_generic_api_schema(client):
    login(client)
    for name in [
        "workspace.css",
        "workspace.js",
        "workspace-api.js",
        "workspace-views.js",
        "workspace-automations.js",
        "workspace-activity.js",
        "workspace-text.js",
    ]:
        response = client.get("/assets/" + name)
        assert response.status_code == 200
        assert "OpenClaw" not in response.text and "/api/openclaw" not in response.text
    assert client.get("/assets/.env").status_code == 422
    schema = client.get("/api/assistant/openapi.json").json()
    assert schema["info"]["title"] == "Morrow API"
    assert "/api/assistant/messages" in schema["paths"]
    assert all("/api/openclaw" not in path for path in schema["paths"])

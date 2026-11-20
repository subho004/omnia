import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import jwt

from claw_orchestrator.auth import CONTROL_COOKIE, PROXY_COOKIE
from claw_orchestrator.provisioning import provision_one


def csrf(client):
    page = client.get("/")
    assert page.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', page.text)[1]


def login(client, user="user1"):
    response = client.post(
        "/auth/login",
        json={"user": user, "csrf": csrf(client)},
        headers={"origin": str(client.base_url).rstrip("/")},
    )
    assert response.status_code == 200, response.text
    return csrf(client)


def post(client, path, token, **body):
    return client.post(
        path, json={"csrf": token, **body}, headers={"origin": str(client.base_url).rstrip("/")}
    )


def ready(client, token):
    response = post(client, "/api/instance", token)
    assert response.status_code == 202, response.text
    client.portal.call(provision_one, client.app.state.db, client.app.state.runtime)
    return client.get("/api/instance").json()["instance"]["id"]


def launch(client, token, iid):
    response = post(client, "/api/instance/launch", token)
    assert response.status_code == 200, response.text
    ticket = re.search(r'name="ticket" value="([^"]+)"', response.text)[1]
    origin = client.app.state.settings.instance_origin(iid)
    exchange = client.post(
        origin + "/__orchestrator/launch",
        data={"ticket": ticket},
        headers={"origin": str(client.base_url).rstrip("/")},
    )
    assert exchange.status_code == 303, exchange.text
    assert exchange.headers["location"] == "/"
    return origin, ticket


def test_login_switch_logout_revokes_old_token(client):
    assert "Choose a user" in client.get("/").text
    token = login(client)
    old = client.cookies.get(CONTROL_COOKIE)
    page = client.get("/").text
    assert page.index("Visit Morrow") < page.index("Switch to user2") < page.index("Logout")
    response = post(client, "/auth/switch", token, user="user2")
    assert response.status_code == 200
    assert client.get("/auth/me").json()["user"]["id"] == "user2"
    assert client.get("/auth/me", headers={"cookie": f"{CONTROL_COOKIE}={old}"}).status_code == 401
    assert post(client, "/auth/logout", csrf(client)).status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_csrf_origin_and_strict_input(client):
    token = login(client)
    assert client.post("/api/instance", json={"csrf": token}).status_code == 403
    assert post(client, "/api/instance", "forged").status_code == 403
    assert post(client, "/api/instance", token, user_id="user2").status_code == 422
    assert post(client, "/api/instance", token, image="arbitrary").status_code == 422
    assert client.get("/auth/logout").status_code == 405
    assert (
        client.post(
            "/auth/login",
            json={"user": "user3", "csrf": token},
            headers={"origin": str(client.base_url).rstrip("/")},
        ).status_code
        == 422
    )


def test_jwt_cookie_attributes_and_claim_validation(client):
    token = login(client)
    raw = client.cookies.get(CONTROL_COOKIE)
    claims = jwt.decode(raw, options={"verify_signature": False})
    assert {"iss", "aud", "sub", "sid", "iat", "nbf", "exp", "jti"} <= claims.keys()
    secret = client.app.state.settings.jwt_secret.get_secret_value()
    for changes in (
        {"aud": "claw-proxy"},
        {"iss": "other"},
        {"sid": "missing"},
        {"sub": "user2"},
        {"exp": int((datetime.now(UTC) - timedelta(seconds=5)).timestamp())},
    ):
        forged = jwt.encode({**claims, **changes}, secret, algorithm="HS256")
        assert (
            client.get("/auth/me", headers={"cookie": f"{CONTROL_COOKIE}={forged}"}).status_code
            == 401
        )
    response = post(client, "/auth/switch", token, user="user2")
    cookie = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith(CONTROL_COOKIE)
    )
    assert all(value in cookie for value in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"))
    assert "Domain=" not in cookie


def test_concurrent_creation_is_idempotent_and_durable(client):
    token = login(client)
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(lambda _: post(client, "/api/instance", token), range(12)))
    assert all(r.status_code == 202 for r in responses)
    ids = {r.json()["instance"]["id"] for r in responses}
    assert len(ids) == 1
    iid = ids.pop()

    async def check():
        async with client.app.state.db.connection() as conn:
            assert await conn.fetchval("SELECT count(*) FROM instances") == 1
            assert await conn.fetchval("SELECT count(*) FROM provisioning_jobs") == 1
            row = await conn.fetchrow("SELECT * FROM instances")
            assert row["volume_name"] == f"openclaw-data-{iid}"

    client.portal.call(check)
    client.portal.call(provision_one, client.app.state.db, client.app.state.runtime)
    response = post(client, "/api/instance", token)
    assert response.status_code == 200 and response.json()["instance"]["id"] == iid


def test_proxy_owner_selection_and_switch_isolation(client, upstream):
    token1 = login(client)
    iid1 = ready(client, token1)
    origin1, _ = launch(client, token1, iid1)
    response = client.get(origin1 + "/file")
    assert response.status_code == 200 and response.text == "private-marker-for-user1"
    token_proxy1 = client.cookies.get(PROXY_COOKIE)
    assert CONTROL_COOKIE not in upstream[-1].headers.get("cookie", "")
    assert post(client, "/auth/switch", token1, user="user2").status_code == 200
    token2 = csrf(client)
    assert client.get(origin1 + "/file").status_code == 401
    iid2 = ready(client, token2)
    assert iid2 != iid1
    origin2, _ = launch(client, token2, iid2)
    assert client.get(origin2 + "/file").text == "private-marker-for-user2"
    token_proxy2 = next(
        c.value for c in client.cookies.jar if c.name == PROXY_COOKIE and c.domain in origin2
    )
    # Spoof user1's host with user2's valid proxy token: authorization must fail before forwarding.
    before = len(upstream)
    response = client.get(
        origin1 + "/file",
        headers={"cookie": f"{PROXY_COOKIE}={token_proxy2}", "x-claw-user": "user1"},
    )
    assert response.status_code == 404 and len(upstream) == before
    assert (
        client.get(
            origin2 + "/file", headers={"cookie": f"{PROXY_COOKIE}={token_proxy1}"}
        ).status_code
        == 401
    )


def test_launch_ticket_is_one_use_and_host_bound(client):
    token = login(client)
    iid = ready(client, token)
    origin, ticket = launch(client, token, iid)
    replay = client.post(
        origin + "/__orchestrator/launch",
        data={"ticket": ticket},
        headers={"origin": str(client.base_url).rstrip("/")},
    )
    assert replay.status_code == 401
    token2 = post(client, "/api/instance/launch", token)
    ticket2 = re.search(r'name="ticket" value="([^"]+)"', token2.text)[1]
    assert post(client, "/auth/logout", token).status_code == 204
    assert (
        client.post(
            origin + "/__orchestrator/launch",
            data={"ticket": ticket2},
            headers={"origin": str(client.base_url).rstrip("/")},
        ).status_code
        == 401
    )


def test_proxy_origin_and_identity_header_sanitizing(client, upstream):
    token = login(client)
    iid = ready(client, token)
    origin, _ = launch(client, token, iid)
    assert client.post(origin + "/action", json={}).status_code == 403
    assert (
        client.post(
            origin + "/action", json={}, headers={"origin": "https://evil.localhost"}
        ).status_code
        == 403
    )
    response = client.get(
        origin + "/file",
        headers={
            "x-claw-user": "user2",
            "authorization": "leaked",
            "x-forwarded-for": "forged",
            "x-openclaw-scopes": "operator.admin",
        },
    )
    assert response.status_code == 200
    headers = upstream[-1].headers
    assert headers["x-claw-user"] == "user1" and "authorization" not in headers
    assert headers["x-forwarded-for"] == "127.0.0.1" and "x-openclaw-scopes" not in headers
    assert "no-store" in response.headers["cache-control"]
    worker = client.get(origin + "/sw.js", headers={"service-worker": "script"})
    assert worker.status_code == 200 and "registration.unregister()" in worker.text


def test_unknown_host_and_public_client_blocked(client):
    assert client.get("https://unknown.localhost:8443/").status_code == 404
    assert (
        client.get("https://app.localhost:8443/", headers={"host": "evil.example"}).status_code
        == 404
    )


def test_runtime_unavailable_does_not_create_placeholder(client):
    client.app.state.runtime.available = False
    token = login(client)
    assert post(client, "/api/instance", token).status_code == 503
    assert client.get("/api/instance").status_code == 404


def test_proxy_denies_websocket_before_accept(client):
    from uuid import uuid4

    import pytest
    from starlette.testclient import WebSocketDenialResponse

    with pytest.raises(WebSocketDenialResponse) as error:
        with client.websocket_connect(f"wss://{uuid4()}.claw.localhost:8443/"):
            pass
    assert error.value.status_code == 401

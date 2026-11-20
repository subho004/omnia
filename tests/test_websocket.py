import pytest
from starlette.websockets import WebSocketDisconnect
from test_control import launch, login, post, ready
from websockets.asyncio.server import serve


@pytest.fixture
def ws_upstream(client):
    async def echo(connection):
        async for message in connection:
            await connection.send(message)

    async def start():
        server = await serve(echo, "127.0.0.1", 0)
        client.app.state.runtime.upstream_url = (
            f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
        )
        return server

    server = client.portal.call(start)
    yield

    async def stop():
        server.close()
        await server.wait_closed()

    client.portal.call(stop)


def test_websocket_roundtrip_and_switch_disconnect(client, ws_upstream):
    token = login(client)
    iid = ready(client, token)
    origin, _ = launch(client, token, iid)
    with client.websocket_connect(
        origin.replace("https:", "wss:") + "/ws", headers={"origin": origin}
    ) as ws:
        ws.send_text("user1-only")
        assert ws.receive_text() == "user1-only"
        assert post(client, "/auth/switch", token, user="user2").status_code == 200
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_text()
        assert error.value.code == 1008


def test_websocket_live_session_expiry_disconnect(client, ws_upstream):
    token = login(client)
    iid = ready(client, token)
    origin, _ = launch(client, token, iid)
    with client.websocket_connect(
        origin.replace("https:", "wss:") + "/ws", headers={"origin": origin}
    ) as ws:
        ws.send_text("before-expiry")
        assert ws.receive_text() == "before-expiry"

        async def expire():
            async with client.app.state.db.connection() as conn:
                await conn.execute("UPDATE sessions SET expires_at=now()-interval '1 second'")

        client.portal.call(expire)
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_text()
        assert error.value.code == 1008

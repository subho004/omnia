import asyncio

import pytest

from claw_orchestrator.browser_bridge import relay


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
async def test_bridge_uses_fixed_supervisor_destination_and_respects_denial(accepted):
    handshake = asyncio.get_running_loop().create_future()
    closed = asyncio.get_running_loop().create_future()

    async def supervisor(reader, writer):
        try:
            handshake.set_result(await reader.readuntil(b"\r\n\r\n"))
            if not accepted:
                writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                await writer.drain()
                assert await reader.read() == b""
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\nHELLO")
            await writer.drain()
            request = await reader.readexactly(4)
            writer.write(request)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set_result(True)

    upstream = await asyncio.start_server(supervisor, "127.0.0.1", 0)
    supervisor_port = upstream.sockets[0].getsockname()[1]
    bridge = await asyncio.start_server(
        lambda r, w: relay(r, w, 18490, "127.0.0.1", supervisor_port), "127.0.0.1", 0
    )
    port = bridge.sockets[0].getsockname()[1]
    writer = None
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert await asyncio.wait_for(handshake, 2) == (
            b"CONNECT host.openshell.internal:18490 HTTP/1.1\r\n"
            b"Host: host.openshell.internal:18490\r\n\r\n"
        )
        if accepted:
            assert await asyncio.wait_for(reader.readexactly(5), 2) == b"HELLO"
            writer.write(b"PING")
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(4), 2) == b"PING"
        else:
            assert await asyncio.wait_for(reader.read(), 2) == b""
        await asyncio.wait_for(closed, 2)
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        bridge.close()
        upstream.close()
        await bridge.wait_closed()
        await upstream.wait_closed()

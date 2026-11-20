import asyncio

import pytest

from claw_orchestrator.egress_proxy import (
    PublicEgressProxy,
    is_allowed_public_ip,
    resolve_and_verify_destination,
)


@pytest.mark.parametrize(
    "ip,allowed",
    [
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("93.184.216.34", True),
        ("127.0.0.1", False),
        ("127.0.1.1", False),
        ("10.0.0.1", False),
        ("10.200.0.1", False),
        ("172.16.0.1", False),
        ("172.20.0.2", False),
        ("172.20.0.3", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("::1", False),
        ("fe80::1", False),
        ("fc00::1", False),
    ],
)
def test_ip_filtering(ip, allowed):
    assert is_allowed_public_ip(ip) is allowed


@pytest.mark.asyncio
async def test_blocked_ports_and_local_hostnames():
    with pytest.raises(ValueError, match="blocked internal port"):
        await resolve_and_verify_destination("example.com", 5432)

    with pytest.raises(ValueError, match="blocked internal port"):
        await resolve_and_verify_destination("example.com", 18480)

    with pytest.raises(ValueError, match="Local host"):
        await resolve_and_verify_destination("localhost", 443)

    with pytest.raises(ValueError, match="Local host"):
        await resolve_and_verify_destination("host.internal", 443)


@pytest.mark.asyncio
async def test_blocked_ip_literals():
    with pytest.raises(ValueError, match="not an allowed public address"):
        await resolve_and_verify_destination("127.0.0.1", 443)

    with pytest.raises(ValueError, match="not an allowed public address"):
        await resolve_and_verify_destination("172.20.0.3", 443)

    with pytest.raises(ValueError, match="not an allowed public address"):
        await resolve_and_verify_destination("169.254.169.254", 80)


@pytest.mark.asyncio
async def test_proxy_connect_denies_private_destinations():
    proxy = PublicEgressProxy(host="127.0.0.1", port=0)
    await proxy.start()
    port = proxy.server.sockets[0].getsockname()[1]

    try:
        # Test 1: Denial of loopback
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT 127.0.0.1:5432 HTTP/1.1\r\nHost: 127.0.0.1:5432\r\n\r\n")
        await writer.drain()
        response = await reader.read(1024)
        assert b"403 Forbidden" in response
        assert b"Destination blocked by public-only egress policy" in response
        writer.close()
        await writer.wait_closed()

        # Test 2: Denial of tenant 2 IP
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT 172.20.0.3:18790 HTTP/1.1\r\nHost: 172.20.0.3:18790\r\n\r\n")
        await writer.drain()
        response = await reader.read(1024)
        assert b"403 Forbidden" in response
        writer.close()
        await writer.wait_closed()

        # Test 3: Denial of cloud metadata
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"CONNECT 169.254.169.254:80 HTTP/1.1\r\nHost: 169.254.169.254:80\r\n\r\n")
        await writer.drain()
        response = await reader.read(1024)
        assert b"403 Forbidden" in response
        writer.close()
        await writer.wait_closed()
    finally:
        await proxy.close()


@pytest.mark.asyncio
async def test_proxy_connect_tunnels_allowed_public_destination(monkeypatch):
    # Mock resolve_and_verify_destination to return 127.0.0.1 on a dedicated test server
    # to test tunneling bytes end-to-end without real internet
    test_server = await asyncio.start_server(
        lambda r, w: None, "127.0.0.1", 0
    )
    test_port = test_server.sockets[0].getsockname()[1]

    async def mock_echo(reader, writer):
        while True:
            data = await reader.read(1024)
            if not data:
                break
            writer.write(data)
            await writer.drain()
        writer.close()

    test_server.close()
    await test_server.wait_closed()
    test_server = await asyncio.start_server(mock_echo, "127.0.0.1", test_port)

    # Monkeypatch resolver so it returns the test_server address
    async def mock_resolve(host, port):
        return "127.0.0.1"

    monkeypatch.setattr(
        "claw_orchestrator.egress_proxy.resolve_and_verify_destination", mock_resolve
    )

    proxy = PublicEgressProxy(host="127.0.0.1", port=0)
    await proxy.start()
    proxy_port = proxy.server.sockets[0].getsockname()[1]

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(f"CONNECT public.example.com:{test_port} HTTP/1.1\r\n\r\n".encode())
        await writer.drain()

        # Should receive 200 Connection Established
        response = await reader.readuntil(b"\r\n\r\n")
        assert b"200 Connection Established" in response

        # Test bidirectional tunneling
        writer.write(b"PING_TUNNEL_DATA")
        await writer.drain()
        echoed = await reader.read(16)
        assert echoed == b"PING_TUNNEL_DATA"

        writer.close()
        await writer.wait_closed()
    finally:
        await proxy.close()
        test_server.close()
        await test_server.wait_closed()


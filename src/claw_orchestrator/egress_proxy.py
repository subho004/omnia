"""Dedicated public-only egress proxy.

Enforces that tenant browsers and workloads can connect exclusively to
globally routable public internet destinations. All loopback, RFC 1918 private,
link-local, cloud metadata (169.254.169.254), and peer tenant IP ranges are
hard-rejected on resolved addresses before any TCP socket is dialed.
"""

import asyncio
import ipaddress
import logging
import socket
from contextlib import suppress
from urllib.parse import urlsplit

logger = logging.getLogger("claw_orchestrator.egress_proxy")

BLOCKED_PORTS = frozenset({22, 1234, 5432, 18480, 18481, 18789, 18790})

BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def is_allowed_public_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    if not addr.is_global:
        return False

    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    ):
        return False

    return not any(addr in network for network in BLOCKED_NETWORKS)


async def resolve_and_verify_destination(host: str, port: int) -> str:
    """Resolve host and verify all resolved addresses are public.

    Returns the first verified public IP address string.
    Raises ValueError if destination is blocked or unresolvable.
    """
    if port in BLOCKED_PORTS:
        raise ValueError(f"Port {port} is a blocked internal port")

    # Reject obvious local hostnames upfront
    lower_host = host.lower().rstrip(".")
    if (
        lower_host == "localhost"
        or lower_host.endswith((".localhost", ".local", ".internal"))
        or "." not in lower_host
    ):
        raise ValueError(f"Local host {host} is rejected")

    # If already an IP literal
    try:
        literal = ipaddress.ip_address(lower_host)
        if not is_allowed_public_ip(str(literal)):
            raise ValueError(f"IP literal {host} is not an allowed public address")
        return str(literal)
    except ValueError as err:
        if "not an allowed public address" in str(err):
            raise

    # Resolve via host DNS with timeout
    try:
        async with asyncio.timeout(5):
            answers = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
    except (OSError, TimeoutError) as err:
        raise ValueError(f"DNS resolution failed for {host}: {err}") from None

    if not answers:
        raise ValueError(f"No address records found for {host}")

    resolved_ips = [answer[4][0] for answer in answers]
    for ip_str in resolved_ips:
        if not is_allowed_public_ip(ip_str):
            raise ValueError(f"Destination {host} resolved to internal/prohibited address {ip_str}")

    return resolved_ips[0]


class PublicEgressProxy:
    def __init__(self, host: str = "0.0.0.0", port: int = 18490):
        self.host = host
        self.port = port
        self.server: asyncio.Server | None = None
        self._active_tasks: set[asyncio.Task] = set()

    async def start(self):
        self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
        logger.info("Public-only egress proxy listening on %s:%d", self.host, self.port)

    async def close(self):
        if self.server:
            self.server.close()
            with suppress(Exception):
                await self.server.wait_closed()
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            with suppress(Exception):
                await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()

    async def _handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ):
        task = asyncio.current_task()
        if task:
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

        peer = client_writer.get_extra_info("peername")
        logger.debug("Incoming connection from %s", peer)

        try:
            line = await client_reader.readline()
            if not line:
                logger.debug("Empty line from %s", peer)
                client_writer.close()
                return

            req_line = line.decode("latin1", errors="replace").strip()
            logger.debug("Req from %s: %s", peer, req_line)
            parts = req_line.split()
            if len(parts) != 3:
                client_writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                return

            method, target, _ = parts
            if method.upper() == "CONNECT":
                await self._handle_connect(target, client_reader, client_writer)
            else:
                await self._handle_http_forward(
                    method, target, line, client_reader, client_writer
                )
        except Exception as err:
            logger.debug("Egress proxy client error: %s", err)
            with suppress(Exception):
                client_writer.close()

    async def _handle_connect(
        self, target: str, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ):
        # Consume any remaining headers until empty line
        while True:
            header_line = await client_reader.readline()
            if not header_line or header_line in (b"\r\n", b"\n"):
                break

        if ":" in target:
            host_str, port_str = target.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443
        else:
            host_str = target
            port = 443

        try:
            target_ip = await resolve_and_verify_destination(host_str, port)
        except ValueError as denial:
            logger.warning("Egress CONNECT denied for %s:%d: %s", host_str, port, denial)
            client_writer.write(
                b"HTTP/1.1 403 Forbidden\r\n"
                b"Content-Type: text/plain\r\n"
                b"Connection: close\r\n\r\n"
                b"Destination blocked by public-only egress policy\r\n"
            )
            await client_writer.drain()
            client_writer.close()
            return

        try:
            target_reader, target_writer = await asyncio.open_connection(target_ip, port)
        except Exception as err:
            logger.error("Failed to connect to %s (%s): %s", host_str, target_ip, err)
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            return

        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        await self._pipe_bidirectional(
            client_reader, client_writer, target_reader, target_writer
        )

    async def _handle_http_forward(
        self,
        method: str,
        target: str,
        req_line: bytes,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ):
        parsed = urlsplit(target)
        host_str = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        try:
            target_ip = await resolve_and_verify_destination(host_str, port)
        except ValueError as denial:
            logger.warning("Egress HTTP %s denied for %s: %s", method, target, denial)
            client_writer.write(
                b"HTTP/1.1 403 Forbidden\r\n"
                b"Content-Type: text/plain\r\n"
                b"Connection: close\r\n\r\n"
                b"Destination blocked by public-only egress policy\r\n"
            )
            await client_writer.drain()
            client_writer.close()
            return

        try:
            target_reader, target_writer = await asyncio.open_connection(target_ip, port)
        except Exception:
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            return

        # Rewrite target in request line to path-only for origin server
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        target_writer.write(f"{method} {path} HTTP/1.1\r\n".encode("latin1"))

        # Forward headers until body
        while True:
            header_line = await client_reader.readline()
            if not header_line:
                break
            target_writer.write(header_line)
            if header_line in (b"\r\n", b"\n"):
                break
        await target_writer.drain()

        await self._pipe_bidirectional(
            client_reader, client_writer, target_reader, target_writer
        )

    async def _pipe_bidirectional(
        self,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
        target_r: asyncio.StreamReader,
        target_w: asyncio.StreamWriter,
    ):
        async def forward(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except Exception:
                pass
            finally:
                with suppress(Exception):
                    dst.close()

        pipe_c2t = asyncio.create_task(forward(client_r, target_w))
        pipe_t2c = asyncio.create_task(forward(target_r, client_w))
        await asyncio.wait((pipe_c2t, pipe_t2c), return_when=asyncio.FIRST_COMPLETED)
        pipe_c2t.cancel()
        pipe_t2c.cancel()
        with suppress(Exception):
            client_w.close()
        with suppress(Exception):
            target_w.close()


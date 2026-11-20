import asyncio
import os
import stat
from contextlib import suppress
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Request, WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse, Response, StreamingResponse
from websockets.asyncio.client import connect, unix_connect
from websockets.exceptions import ConnectionClosed

from .auth import PROXY_COOKIE, Principal
from .connections import Guard
from .errors import APIError

HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
}
IDENTITY = {
    "authorization",
    "cookie",
    "forwarded",
    "x-real-ip",
    "x-claw-user",
    "x-openclaw-scopes",
    "x-auth-request-email",
    "x-remote-user",
}


def upstream_headers(
    headers,
    principal: Principal,
    origin: str,
    local_uds=False,
    local_client_address: str | None = None,
) -> dict[str, str]:
    connection = {v.strip().lower() for v in headers.get("connection", "").split(",")}
    cleaned = {
        k: v
        for k, v in headers.items()
        if k.lower() not in HOP | IDENTITY | connection
        and not k.lower().startswith(("x-forwarded-", "sec-websocket-", "x-claw-"))
    }
    cleaned.update(
        {
            "x-claw-user": principal.user_id,
            "x-forwarded-proto": "https",
            "x-forwarded-host": urlsplit(origin).netloc,
            "x-forwarded-for": "127.0.0.1",
        }
    )
    if local_uds:
        cleaned.update({"x-claw-proxy": "local-uds", "host": urlsplit(origin).netloc})
        if not local_client_address:
            raise APIError(503, "CLIENT_ATTRIBUTION_UNAVAILABLE", "The local proxy is unavailable.")
        cleaned["x-forwarded-for"] = local_client_address
    cookies = SimpleCookie()
    with suppress(Exception):
        cookies.load(headers.get("cookie", ""))
        allowed = [
            morsel.OutputString()
            for name, morsel in cookies.items()
            if not name.startswith("__Host-claw_")
        ]
        if allowed:
            cleaned["cookie"] = "; ".join(allowed)
    return cleaned


def unix_socket(raw: str) -> str | None:
    if not raw.startswith("unix:"):
        return None
    path = Path(raw.removeprefix("unix:"))
    try:
        parent, info = path.parent.stat(), path.lstat()
        valid = (
            path.is_absolute()
            and path.parent.name.startswith("co-")
            and parent.st_uid == os.getuid()
            and stat.S_IMODE(parent.st_mode) == 0o700
            and info.st_uid == os.getuid()
            and stat.S_ISSOCK(info.st_mode)
        )
    except OSError:
        valid = False
    if not valid:
        raise APIError(503, "INVALID_UPSTREAM", "The private instance connection is unavailable.")
    return str(path)


def checked_upstream(raw: str) -> httpx.URL:
    if unix_socket(raw):
        return httpx.URL("http://openclaw.internal/")
    url = httpx.URL(raw)
    # Runtime adapters must expose a private, authenticated host-side forward.
    # Arbitrary network/DNS targets are not accepted even from persisted metadata.
    if (
        url.scheme != "http"
        or url.host not in ("127.0.0.1", "::1")
        or not url.port
        or url.userinfo
        or url.path != "/"
        or url.query
        or url.fragment
    ):
        raise APIError(503, "INVALID_UPSTREAM", "The private instance connection is unavailable.")
    return url


def target_url(base: str, path: bytes, query: bytes) -> httpx.URL:
    url = checked_upstream(base)
    # copy_with preserves the fixed authority even for paths beginning with '//'.
    return url.copy_with(raw_path=path + (b"?" + query if query else b""))


def response_headers(headers: httpx.Headers, origin: str, base: str) -> list[tuple[bytes, bytes]]:
    result = []
    connection = {v.strip().lower() for v in headers.get("connection", "").split(",")}
    for key, value in headers.multi_items():
        key = key.lower()
        if key in HOP | connection | {
            "cache-control",
            "set-cookie",
            "location",
            "service-worker-allowed",
            "clear-site-data",
            "content-length",
        }:
            continue
        result.append((key.encode("latin1"), value.encode("latin1")))
    if "location" in headers:
        location = headers["location"]
        parsed = urlsplit(location)
        if location.startswith("//") or (parsed.scheme and not location.startswith(base)):
            raise APIError(502, "UNSAFE_REDIRECT", "An unsafe upstream redirect was blocked.")
        if location.startswith(base):
            location = origin + "/" + location[len(base) :].lstrip("/")
        result.append((b"location", location.encode("latin1")))
    for value in headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        with suppress(Exception):
            cookie.load(value)
            for name, morsel in cookie.items():
                if name.startswith("__Host-claw_"):
                    continue
                morsel["domain"] = ""
                morsel["secure"] = True
                morsel["samesite"] = "Lax"
                result.append((b"set-cookie", morsel.OutputString().encode("latin1")))
    result.append((b"cache-control", b"private, no-store"))
    # This local prototype disallows service-worker registration/offline interception.
    result.append((b"content-security-policy", b"worker-src 'self' blob:; frame-ancestors 'none'"))
    return result


async def proxy_http(request: Request):
    state = request.app.state
    iid = request.state.instance_id
    if not iid or request.url.path.startswith("/__orchestrator"):
        raise APIError(404, "NOT_FOUND", "Not found.")
    principal = await state.auth.authenticate(request.cookies.get(PROXY_COOKIE), "claw-proxy")
    origin = state.settings.instance_origin(iid)
    supplied_origin = request.headers.get("origin")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS") or supplied_origin
    ) and supplied_origin != origin:
        raise APIError(403, "INVALID_ORIGIN", "This request origin is not allowed.")
    if request.headers.get("service-worker") == "script":
        await state.instances.authorize_proxy(principal, iid)
        # Satisfy the UI's registration call without caching or intercepting requests.
        # Unregister immediately and clear any old worker-managed cache for this origin.
        return Response(
            "self.addEventListener('install',()=>self.skipWaiting());"
            "self.addEventListener('activate',e=>e.waitUntil(Promise.all(["
            "self.registration.unregister(),caches.keys().then(ks=>Promise.all("
            "ks.map(k=>caches.delete(k))))])));",
            media_type="text/javascript",
            headers={"Cache-Control": "private, no-store"},
        )
    if request.method in ("CONNECT", "TRACE") or request.headers.get("upgrade"):
        raise APIError(405, "METHOD_NOT_ALLOWED", "Unsupported proxy protocol.")
    guard = Guard(state.connections, state.auth, state.instances, principal, iid)
    row = await guard.open()
    upstream = None
    try:
        url = target_url(
            row["upstream_url"], request.scope["raw_path"], request.scope["query_string"]
        )
        total = 0

        async def body():
            nonlocal total
            async for chunk in request.stream():
                total += len(chunk)
                if total > 16 * 1024 * 1024:
                    raise APIError(413, "BODY_TOO_LARGE", "The upload exceeds 16 MiB.")
                yield chunk

        socket_path = unix_socket(row["upstream_url"])
        client = state.http
        if socket_path:
            if socket_path not in state.http_uds:
                state.http_uds[socket_path] = httpx.AsyncClient(
                    transport=httpx.AsyncHTTPTransport(uds=socket_path),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(60, connect=10, pool=5),
                    limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                )
            client = state.http_uds[socket_path]
        req = client.build_request(
            request.method,
            url,
            headers=upstream_headers(
                request.headers,
                principal,
                origin,
                bool(socket_path),
                state.settings.proxy_client_address() if socket_path else None,
            ),
            content=body(),
        )
        upstream = await guard.run(client.send(req, stream=True))
        raw_headers = response_headers(
            upstream.headers, origin, str(checked_upstream(row["upstream_url"]))
        )
        # Recheck after the asynchronous connection setup, before sending response headers.
        await guard.valid()

        async def stream():
            try:
                iterator = upstream.aiter_raw().__aiter__()
                while True:
                    try:
                        chunk = await guard.run(anext(iterator))
                    except StopAsyncIteration:
                        break
                    yield chunk
            except APIError:
                # Headers may already have been sent. End this stream without forwarding
                # additional bytes; a revoked session cannot start another request.
                return
            finally:
                await upstream.aclose()
                await guard.close()

        response = StreamingResponse(stream(), status_code=upstream.status_code)
        response.raw_headers = raw_headers
        return response
    except BaseException:
        if upstream:
            await upstream.aclose()
        await guard.close()
        raise


async def proxy_ws(websocket: WebSocket):
    state, iid = websocket.app.state, websocket.state.instance_id
    guard = None
    upstream = None
    accepted = False
    try:
        if not iid or websocket.url.path.startswith("/__orchestrator"):
            raise APIError(404, "NOT_FOUND", "Not found.")
        principal = await state.auth.authenticate(websocket.cookies.get(PROXY_COOKIE), "claw-proxy")
        row = await state.instances.authorize_proxy(principal, iid)
        origin = state.settings.instance_origin(iid)
        if websocket.headers.get("origin") != origin:
            raise APIError(403, "INVALID_ORIGIN", "This request origin is not allowed.")
        guard = Guard(state.connections, state.auth, state.instances, principal, iid)
        row = await guard.open()
        url = target_url(
            row["upstream_url"], websocket.scope["raw_path"], websocket.scope["query_string"]
        )
        protocols = websocket.scope.get("subprotocols", [])
        socket_path = unix_socket(row["upstream_url"])
        headers = upstream_headers(
            websocket.headers,
            principal,
            origin,
            bool(socket_path),
            state.settings.proxy_client_address() if socket_path else None,
        )
        headers.pop("origin", None)
        headers.pop("host", None)
        options = dict(
            additional_headers=headers,
            origin=origin,
            subprotocols=protocols or None,
            open_timeout=10,
            close_timeout=2,
            max_size=2 * 1024 * 1024,
            max_queue=8,
        )
        if socket_path:
            uri = str(
                url.copy_with(
                    scheme="ws", host=urlsplit(origin).hostname, port=state.settings.public_port
                )
            )
            pending = unix_connect(socket_path, uri=uri, **options)
        else:
            pending = connect(str(url.copy_with(scheme="ws")), proxy=None, **options)
        upstream = await guard.run(pending)
        await guard.valid()
        await websocket.accept(subprotocol=upstream.subprotocol)
        accepted = True

        async def to_upstream():
            while True:
                message = await guard.run(websocket.receive())
                if message["type"] == "websocket.disconnect":
                    return
                value = message.get("text", message.get("bytes"))
                await guard.run(upstream.send(value))

        async def to_browser():
            while True:
                value = await guard.run(upstream.recv())
                if isinstance(value, str):
                    await guard.run(websocket.send_text(value))
                else:
                    await guard.run(websocket.send_bytes(value))

        tasks = [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
    except APIError as exc:
        if not accepted:
            await websocket.send_denial_response(
                JSONResponse({"error": {"code": exc.code, "message": exc.message}}, exc.status_code)
            )
    except (ConnectionClosed, WebSocketDisconnect, OSError, httpx.HTTPError):
        pass
    finally:
        if upstream:
            await upstream.close()
        if guard:
            await guard.close()
        with suppress(RuntimeError, OSError, WebSocketDisconnect):
            await websocket.close(code=1008 if accepted else 1000)

import ipaddress
from uuid import UUID

from starlette.responses import JSONResponse

from .config import Settings


class BoundaryMiddleware:
    """Apply the same host/TLS/local-client boundary to HTTP and WebSockets."""

    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        hosts = [v.decode("latin1") for k, v in scope["headers"] if k.lower() == b"host"]
        client = scope.get("client")
        try:
            local = bool(client and ipaddress.ip_address(client[0]).is_loopback)
        except ValueError:
            local = False
        control = self.settings.control_origin.removeprefix("https://")
        host = hosts[0] if len(hosts) == 1 else ""
        iid = None
        if host != control:
            suffix = f".{self.settings.instance_domain}:{self.settings.public_port}"
            raw = host.removesuffix(suffix) if host.endswith(suffix) else ""
            try:
                parsed = UUID(raw, version=4)
                if str(parsed) == raw:
                    iid = raw
            except ValueError:
                pass
        valid = (
            local and scope["scheme"] in ("https", "wss") and (host == control or iid is not None)
        )
        if not valid:
            response = JSONResponse({"error": {"code": "NOT_FOUND", "message": "Not found."}}, 404)
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await response(scope, receive, send)
            return
        scope.setdefault("state", {})["instance_id"] = iid
        await self.app(scope, receive, send)

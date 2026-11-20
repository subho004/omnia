"""Small, bounded client for the pinned OpenClaw v4 WebSocket RPC protocol."""

import asyncio
import json
from collections import deque
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from starlette.datastructures import Headers
from websockets.asyncio.client import connect, unix_connect
from websockets.exceptions import WebSocketException

from .chat_activity import EVENTS
from .errors import APIError
from .proxy import checked_upstream, unix_socket, upstream_headers
from .runtime.nemoclaw import NemoClawRuntime

METHODS = frozenset(
    {
        "connect",
        "sessions.list",
        "sessions.create",
        "chat.history",
        "chat.send",
        "chat.abort",
        "sessions.messages.subscribe",
        "sessions.subscribe",
        "question.list",
        "browser.request",
        "tasks.list",
        "tasks.get",
        "tasks.cancel",
        "approval.get",
        "approval.history",
        "approval.resolve",
        "cron.list",
        "cron.get",
        "cron.status",
        "cron.runs",
        "cron.add",
        "cron.update",
        "cron.remove",
        "cron.run",
    }
)


class GatewayClient:
    def __init__(self, state, principal, row, guard):
        self.state, self.principal, self.row, self.guard = state, principal, row, guard
        self.socket = None
        self.events = deque(maxlen=128)
        self.scopes = ["operator.read", "operator.write"]

    async def open(self):
        origin = self.state.settings.instance_origin(str(self.row["id"]))
        upstream = self.row["upstream_url"]
        runtime = getattr(self.state, "runtime", None)
        if isinstance(runtime, NemoClawRuntime):
            # Ownership has already been checked by the request guard. A native
            # restart can retire the private tunnel without changing its path.
            try:
                upstream = await self.guard.run(runtime.forward(self.row))
            except RuntimeError as exc:
                raise OSError("Private ingress is temporarily unavailable") from exc
        socket_path = unix_socket(upstream)
        headers = upstream_headers(
            Headers(),
            self.principal,
            origin,
            bool(socket_path),
            self.state.settings.proxy_client_address() if socket_path else None,
        )
        headers.pop("host", None)
        options = dict(
            additional_headers=headers,
            # This adapter serves the independent frontend at the control
            # origin. The tenant Host remains a server-owned routing hint.
            origin=self.state.settings.control_origin,
            open_timeout=5,
            close_timeout=1,
            max_size=2 * 1024 * 1024,
            max_queue=8,
        )
        if socket_path:
            pending = unix_connect(
                socket_path, uri=origin.replace("https:", "ws:") + "/", **options
            )
        else:
            pending = connect(
                str(checked_upstream(upstream).copy_with(scheme="ws")),
                proxy=None,
                **options,
            )
        self.socket = await self.guard.run(pending)
        async with asyncio.timeout(10):
            challenge = await self.receive()
            if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
                raise APIError(
                    502, "GATEWAY_PROTOCOL_ERROR", "The instance protocol is unavailable."
                )
            payload = challenge.get("payload")
            nonce = payload.get("nonce") if isinstance(payload, dict) else None
            if not isinstance(nonce, str) or not 1 <= len(nonce) <= 1024:
                raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid gateway challenge.")
            device = await self.device(nonce)
            # This server is the Control UI adapter. Trusted-proxy authentication
            # derives identity from our private ingress; no browser/device token is used.
            await self.call(
                "connect",
                {
                    "minProtocol": 4,
                    "maxProtocol": 4,
                    "client": {
                        "id": "openclaw-control-ui",
                        "version": "0.1.0",
                        "platform": "server",
                        "mode": "ui",
                        "instanceId": str(uuid4()),
                    },
                    "role": "operator",
                    "scopes": self.scopes,
                    "device": device,
                    "caps": ["session-scoped-events", "tool-events", "agent-kind"],
                },
            )

    async def device(self, nonce):
        root = getattr(self.state, "gateway_device_root", Path.cwd() / ".state/gateway-devices")
        directory = root / str(self.row["id"])
        # Native pairing intentionally rejects silent scope upgrades. Reviews
        # use their own constrained identity instead of expanding the chat key.
        if "operator.questions" in self.scopes:
            directory = directory / (
                "activity" if "operator.approvals" in self.scopes else "activity-no-reviews"
            )
        elif "operator.approvals" in self.scopes:
            directory = directory / "reviewer"
        elif "operator.admin" in self.scopes:
            directory = directory / "automations"
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(Path(__file__).with_name("device.mjs")),
            str(directory),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(5):
                output, _ = await self.guard.run(
                    proc.communicate(
                        json.dumps(
                            {
                                "nonce": nonce,
                                "scopes": self.scopes,
                            }
                        ).encode()
                    )
                )
            if proc.returncode:
                raise APIError(
                    503, "DEVICE_IDENTITY_UNAVAILABLE", "The instance connection is unavailable."
                )
            return json.loads(output)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    async def receive(self):
        try:
            raw = await self.guard.run(self.socket.recv())
            frame = json.loads(raw)
            if not isinstance(frame, dict):
                raise ValueError
            return frame
        except (ValueError, UnicodeError):
            raise APIError(
                502, "GATEWAY_PROTOCOL_ERROR", "The instance protocol is unavailable."
            ) from None

    async def call(self, method, params):
        if method not in METHODS:
            raise APIError(403, "OPERATION_NOT_ALLOWED", "This operation is not exposed.")
        request_id = str(uuid4())
        await self.guard.run(
            self.socket.send(
                json.dumps(
                    {
                        "type": "req",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    }
                )
            )
        )
        async with asyncio.timeout(50 if method == "browser.request" else 15):
            while True:
                frame = await self.receive()
                if frame.get("type") == "res" and frame.get("id") == request_id:
                    if frame.get("ok") is not True:
                        native = frame.get("error")
                        native = native if isinstance(native, dict) else {}
                        details = native.get("details")
                        details = details if isinstance(details, dict) else {}
                        if method == "browser.request" and native.get("code") == "INVALID_REQUEST":
                            raise APIError(
                                422,
                                "BROWSER_REQUEST_REJECTED",
                                "This website or action is blocked by workspace browser policy.",
                            )
                        if method.startswith("cron."):
                            if details.get("code") == "CRON_JOB_NOT_FOUND":
                                raise APIError(404, "AUTOMATION_NOT_FOUND", "Automation not found.")
                            if details.get("code") == "CRON_JOB_CHANGED":
                                raise APIError(409, "AUTOMATION_CHANGED", "Reload this automation.")
                            if native.get("code") == "INVALID_REQUEST":
                                raise APIError(
                                    422, "AUTOMATION_REJECTED", "Check the automation settings."
                                )
                        # Native errors can contain paths, provider details, and credentials.
                        raise APIError(
                            502, "GATEWAY_REJECTED", "The instance rejected this operation."
                        )
                    result = frame.get("payload", {})
                    if not isinstance(result, dict):
                        raise APIError(
                            502, "GATEWAY_PROTOCOL_ERROR", "The instance protocol is unavailable."
                        )
                    return result
                if frame.get("type") == "event" and frame.get("event") in EVENTS:
                    if len(self.events) == self.events.maxlen:
                        raise APIError(
                            502, "EVENT_OVERFLOW", "Reconnect and reload session history."
                        )
                    self.events.append(frame)

    async def next_event(self):
        return self.events.popleft() if self.events else await self.receive()

    async def close(self):
        if self.socket:
            with suppress(OSError, WebSocketException):
                await self.socket.close()


GATEWAY_FAILURES = (OSError, TimeoutError, WebSocketException)

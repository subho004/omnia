import asyncio
from contextlib import suppress

from .auth import Auth, Principal
from .errors import APIError
from .instances import Instances


class Connections:
    def __init__(self):
        self.active: dict[str, set[asyncio.Event]] = {}

    def register(self, sid: str) -> asyncio.Event:
        events = self.active.setdefault(sid, set())
        if len(events) >= 8 or sum(map(len, self.active.values())) >= 64:
            if not events:
                self.active.pop(sid, None)
            raise APIError(429, "CONNECTION_LIMIT", "Too many connections.")
        event = asyncio.Event()
        events.add(event)
        return event

    def remove(self, sid: str, event: asyncio.Event):
        events = self.active.get(sid, set())
        events.discard(event)
        if not events:
            self.active.pop(sid, None)

    def revoke(self, sid: str):
        for event in self.active.get(sid, set()):
            event.set()


class Guard:
    def __init__(
        self,
        registry: Connections,
        auth: Auth,
        instances: Instances,
        principal: Principal,
        host_iid: str,
    ):
        self.registry, self.auth, self.instances = registry, auth, instances
        self.principal, self.host_iid = principal, host_iid
        self.event: asyncio.Event | None = None
        self.watcher: asyncio.Task | None = None
        self.failure: APIError | None = None

    async def valid(self):
        if not await self.auth.is_live(self.principal):
            raise APIError(401, "SESSION_ENDED", "Your session has ended.")
        return await self.instances.authorize_proxy(self.principal, self.host_iid)

    async def open(self):
        self.event = self.registry.register(self.principal.sid)
        try:
            row = await self.valid()
            self.watcher = asyncio.create_task(self.watch(row["upstream_url"]))
            return row
        except BaseException:
            self.registry.remove(self.principal.sid, self.event)
            raise

    async def watch(self, upstream: str):
        try:
            while True:
                await asyncio.sleep(0.5)
                async with asyncio.timeout(0.5):
                    row = await self.valid()
                if row["upstream_url"] != upstream:
                    self.failure = APIError(
                        503, "RECONNECT_REQUIRED", "Reconnect to your workspace."
                    )
                    break
        except APIError as error:
            if error.status_code >= 500:
                self.failure = error
        except Exception:
            self.failure = APIError(503, "INSTANCE_UNAVAILABLE", "Your instance is unavailable.")
        self.event.set()

    async def run(self, awaitable):
        operation = asyncio.ensure_future(awaitable)
        ended = asyncio.create_task(self.event.wait())
        try:
            await asyncio.wait((operation, ended), return_when=asyncio.FIRST_COMPLETED)
            if self.event.is_set():
                if self.failure is not None:
                    # An availability failure must not clear a still-live page.
                    # A concurrent logout/expiry continues to take precedence.
                    try:
                        live = await self.auth.is_live(self.principal)
                    except Exception:
                        raise APIError(
                            503, "INSTANCE_UNAVAILABLE", "Your instance is unavailable."
                        ) from None
                    if live:
                        raise self.failure
                raise APIError(401, "SESSION_ENDED", "Your session has ended.")
            return await operation
        finally:
            for task in (operation, ended):
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task

    async def close(self):
        if self.watcher:
            self.watcher.cancel()
            with suppress(asyncio.CancelledError):
                await self.watcher
        if self.event:
            self.registry.remove(self.principal.sid, self.event)

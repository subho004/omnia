import asyncio
import secrets
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

import asyncpg
import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, ValidationError

from .auth import (
    CONTROL_COOKIE,
    PRELOGIN_COOKIE,
    PROXY_COOKIE,
    USERS,
    Auth,
    check_csrf,
    clear_cookie,
    set_cookie,
    workspace_session,
)
from .boundary import BoundaryMiddleware
from .config import Settings
from .connections import Connections
from .db import Database
from .egress_proxy import PublicEgressProxy
from .errors import APIError
from .frontend_api import install_frontend_api
from .instances import Instances, public_instance
from .provisioning import worker
from .proxy import proxy_http, proxy_ws
from .runtime import NemoClawRuntime, Runtime

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user: Literal["user1", "user2"]
    csrf: str = ""


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    csrf: str = ""


async def payload(request: Request, model):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 8192:
            raise APIError(413, "BODY_TOO_LARGE", "Request body too large.")
    # Starlette can parse the cached small body for both form and JSON clients.
    request._body = bytes(data)
    try:
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            form = await request.form()
            if len(form.multi_items()) != len(form):
                raise ValueError("duplicate fields")
            raw = dict(form)
        elif not data:
            raw = {}
        elif request.headers.get("content-type", "").startswith("application/json"):
            raw = await request.json()
        else:
            raise ValueError("unsupported content type")
        return model.model_validate(raw)
    except (ValidationError, ValueError):
        raise APIError(422, "INVALID_INPUT", "The request contains invalid fields.") from None


def origin_check(request: Request):
    if request.headers.get("origin") != request.app.state.settings.control_origin:
        raise APIError(403, "INVALID_ORIGIN", "This request origin is not allowed.")


def browser_form(request: Request) -> bool:
    return request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded")


class TenantDispatch:
    def __init__(self, app, tenant):
        self.app, self.tenant = app, tenant

    async def __call__(self, scope, receive, send):
        if scope.get("state", {}).get("instance_id"):
            return await self.tenant(scope, receive, send)
        return await self.app(scope, receive, send)


def create_app(
    settings: Settings | None = None, runtime: Runtime | None = None, start_worker: bool = True
) -> FastAPI:
    settings = settings or Settings()
    runtime = runtime or NemoClawRuntime(settings)
    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(application):
        await db.open()
        egress = PublicEgressProxy(
            host=settings.egress_proxy_host,
            port=settings.egress_proxy_port,
        )
        try:
            await egress.start()
            application.state.egress_proxy = egress
        except Exception:
            await db.close()
            raise
        if isinstance(runtime, NemoClawRuntime) and runtime.available:
            async with db.connection() as conn:
                retained = await conn.fetch("SELECT * FROM instances WHERE status='ready'")
            for row in retained:
                if not await runtime.probe(dict(row)):
                    async with db.connection() as conn:
                        await conn.execute(
                            "UPDATE instances SET status='unavailable',updated_at=now() "
                            "WHERE id=$1",
                            row["id"],
                        )
        application.state.http = httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(60, connect=10, pool=5),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )
        application.state.http_uds = {}
        task = asyncio.create_task(worker(db, runtime)) if start_worker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await application.state.http.aclose()
            for client in application.state.http_uds.values():
                await client.aclose()
            if isinstance(runtime, NemoClawRuntime):
                await runtime.close()
            if egress:
                await egress.close()
            await db.close()

    app = FastAPI(
        title="Morrow API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    tenant = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.db, app.state.runtime = settings, db, runtime
    app.state.auth = Auth(settings, db)
    app.state.instances = Instances(settings, db, app.state.auth, runtime)
    app.state.connections = Connections()
    install_frontend_api(app)
    tenant.state = app.state

    async def api_error(request, error: APIError):
        return JSONResponse(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "request_id": secrets.token_hex(8),
                }
            },
            status_code=error.status_code,
            headers={"Cache-Control": "private, no-store"},
        )

    async def dependency_error(request, error):
        return await api_error(
            request,
            APIError(
                503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable. Try again."
            ),
        )

    async def validation_error(request, error):
        return await api_error(request, APIError(422, "INVALID_INPUT", "Invalid request."))

    for application in (app, tenant):
        application.add_exception_handler(APIError, api_error)
        application.add_exception_handler(asyncpg.PostgresError, dependency_error)
        application.add_exception_handler(OSError, dependency_error)
        application.add_exception_handler(TimeoutError, dependency_error)
        application.add_exception_handler(httpx.HTTPError, dependency_error)
        application.add_exception_handler(RequestValidationError, validation_error)

    @app.middleware("http")
    async def response_policy(request, call_next):
        expected_session = request.headers.get("x-workspace-session")
        if expected_session is not None and request.url.path.startswith(("/api/", "/auth/")):
            try:
                principal = await app.state.auth.authenticate(
                    request.cookies.get(CONTROL_COOKIE), "claw-control"
                )
                if len(expected_session) != 64 or not secrets.compare_digest(
                    expected_session.encode(), workspace_session(principal.sid).encode()
                ):
                    raise APIError(409, "SESSION_CHANGED", "This account changed. Sign in again.")
            except APIError as error:
                return await api_error(request, error)
            except (asyncpg.PostgresError, OSError, TimeoutError) as error:
                return await dependency_error(request, error)
        if request.url.path.startswith(("/api/openclaw/", "/api/assistant/")):
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 32768:
                    return await api_error(
                        request, APIError(413, "BODY_TOO_LARGE", "Request body exceeds 32 KiB.")
                    )
            request._body = bytes(data)
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        # no-referrer makes HTML form POSTs send Origin: null in Chromium.
        # strict-origin keeps paths private while preserving exact Origin checks.
        response.headers["Referrer-Policy"] = "strict-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
            "form-action https://*.claw.localhost:8443 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        ).replace(":8443", f":{settings.public_port}")
        return response

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readiness():
        async with db.connection() as conn:
            await conn.fetchval("SELECT 1")
        return {"database": "ready", "runtime": "ready" if runtime.available else "not_configured"}

    @app.get("/api/runtime")
    async def runtime_status(request: Request):
        await app.state.auth.authenticate(request.cookies.get(CONTROL_COOKIE), "claw-control")
        return {"available": runtime.available, "message": runtime.reason}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        principal = None
        try:
            principal = await app.state.auth.authenticate(
                request.cookies.get(CONTROL_COOKIE), "claw-control"
            )
        except APIError:
            pass
        csrf, prelogin = (principal.csrf, None) if principal else app.state.auth.prelogin()
        response = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "principal": principal,
                "csrf": csrf,
                "users": USERS,
                "runtime_available": runtime.available,
                "runtime_message": runtime.reason,
                "auth_marker": workspace_session(principal.sid) if principal else "signed-out",
            },
        )
        if prelogin:
            set_cookie(response, PRELOGIN_COOKIE, prelogin, 600)
            clear_cookie(response, CONTROL_COOKIE)
        return response

    @app.get("/assets/{name}")
    async def assets(
        name: Literal[
            "style.css",
            "app.js",
            "workspace.css",
            "workspace.js",
            "workspace-api.js",
            "workspace-views.js",
            "workspace-automations.js",
            "workspace-activity.js",
            "workspace-text.js",
            "workspace-markdown.js",
        ],
    ):
        media = "text/css" if name.endswith("css") else "text/javascript"
        return Response((Path(__file__).parent / "static" / name).read_text(), media_type=media)

    @app.get("/workspace", response_class=HTMLResponse)
    async def workspace(request: Request):
        try:
            principal = await app.state.auth.authenticate(
                request.cookies.get(CONTROL_COOKIE), "claw-control"
            )
        except APIError:
            return RedirectResponse("/", 303)
        return templates.TemplateResponse(
            request=request,
            name="workspace.html",
            context={
                "user_id": principal.user_id,
                "display_name": USERS[principal.user_id],
                "view_session": workspace_session(principal.sid),
            },
        )

    async def do_login(request: Request, switching: bool):
        if not settings.demo_auth_enabled:
            raise APIError(403, "DEMO_DISABLED", "Demo login is disabled.")
        origin_check(request)
        body = await payload(request, LoginInput)
        previous = None
        if switching or request.cookies.get(CONTROL_COOKIE):
            previous = await app.state.auth.authenticate(
                request.cookies.get(CONTROL_COOKIE), "claw-control"
            )
            check_csrf(previous, request.headers.get("x-csrf-token", body.csrf))
        else:
            app.state.auth.check_prelogin(
                request.cookies.get(PRELOGIN_COOKIE), request.headers.get("x-csrf-token", body.csrf)
            )
        principal = await app.state.auth.create_session(body.user, previous)
        if previous:
            app.state.connections.revoke(previous.sid)
        response = (
            RedirectResponse("/", 303)
            if browser_form(request)
            else JSONResponse({"user": {"id": body.user, "display_name": USERS[body.user]}})
        )
        set_cookie(
            response,
            CONTROL_COOKIE,
            app.state.auth.session_token(principal, "claw-control"),
            settings.session_seconds,
        )
        clear_cookie(response, PRELOGIN_COOKIE)
        return response

    @app.post("/auth/login")
    async def login(request: Request):
        return await do_login(request, False)

    @app.post("/auth/switch")
    async def switch(request: Request):
        return await do_login(request, True)

    @app.post("/auth/logout")
    async def logout(request: Request):
        origin_check(request)
        body = await payload(request, EmptyInput)
        try:
            principal = await app.state.auth.authenticate(
                request.cookies.get(CONTROL_COOKIE), "claw-control"
            )
        except APIError:
            principal = None
        if principal:
            check_csrf(principal, request.headers.get("x-csrf-token", body.csrf))
            await app.state.auth.revoke(principal)
            app.state.connections.revoke(principal.sid)
        response = (
            RedirectResponse("/", 303) if browser_form(request) else Response(status_code=204)
        )
        clear_cookie(response, CONTROL_COOKIE)
        clear_cookie(response, PRELOGIN_COOKIE)
        return response

    @app.get("/auth/me")
    async def me(request: Request):
        principal = await app.state.auth.authenticate(
            request.cookies.get(CONTROL_COOKIE), "claw-control"
        )
        return {"user": {"id": principal.user_id, "display_name": USERS[principal.user_id]}}

    @app.get("/api/instance")
    async def status(request: Request):
        principal = await app.state.auth.authenticate(
            request.cookies.get(CONTROL_COOKIE), "claw-control"
        )
        return public_instance(await app.state.instances.own(principal.user_id))

    @app.post("/api/instance")
    async def create(request: Request):
        origin_check(request)
        principal = await app.state.auth.authenticate(
            request.cookies.get(CONTROL_COOKIE), "claw-control"
        )
        body = await payload(request, EmptyInput)
        check_csrf(principal, request.headers.get("x-csrf-token", body.csrf))
        row = await app.state.instances.create(principal)
        if row["status"] in ("failed", "unavailable"):
            raise APIError(409, "INSTANCE_NOT_READY", "Your instance needs operator attention.")
        code = 200 if row["status"] == "ready" else 202
        return JSONResponse(
            public_instance(row), code, headers={"Location": "/api/instance", "Retry-After": "2"}
        )

    @app.post("/api/instance/launch", response_class=HTMLResponse)
    async def launch(request: Request):
        origin_check(request)
        principal = await app.state.auth.authenticate(
            request.cookies.get(CONTROL_COOKIE), "claw-control"
        )
        body = await payload(request, EmptyInput)
        check_csrf(principal, request.headers.get("x-csrf-token", body.csrf))
        ticket, target = await app.state.instances.ticket(principal)
        return templates.TemplateResponse(
            request=request, name="launch.html", context={"ticket": ticket, "target": target}
        )

    @tenant.post("/__orchestrator/launch")
    async def exchange(request: Request):
        origin_check(request)

        class TicketInput(BaseModel):
            model_config = ConfigDict(extra="forbid", strict=True)
            ticket: str

        body = await payload(request, TicketInput)
        principal = await app.state.instances.consume(body.ticket, request.state.instance_id)
        response = RedirectResponse("/", 303)
        remaining = int(principal.expires_at.timestamp() - time.time())
        set_cookie(
            response,
            PROXY_COOKIE,
            app.state.auth.session_token(principal, "claw-proxy", principal.instance_id),
            max(0, remaining),
        )
        return response

    tenant.add_api_route(
        "/{path:path}",
        proxy_http,
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"],
    )
    tenant.add_api_websocket_route("/{path:path}", proxy_ws)
    app.add_middleware(TenantDispatch, tenant=tenant)
    app.add_middleware(BoundaryMiddleware, settings=settings)
    return app

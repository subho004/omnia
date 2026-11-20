"""Owner-selected browser connection over fixed native browser-control operations."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import Field, field_validator

from .errors import APIError
from .frontend_api import Input, owned_gateway
from .presentation import public_text

PROFILE = "openclaw"


def public_url(value):
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme not in {"http", "https"} or not host or url.username or url.password:
            raise ValueError
        if url.port not in (None, 80, 443):
            raise ValueError
        if (
            host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
            or "." not in host
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise ValueError("Use a public HTTP or HTTPS website without credentials.") from None


class OpenTab(Input):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return public_url(value)


async def check_destination(value):
    host = urlsplit(value).hostname
    try:
        async with asyncio.timeout(5):
            answers = await asyncio.get_running_loop().getaddrinfo(
                host, None, type=socket.SOCK_STREAM
            )
        if not answers or any(
            not ipaddress.ip_address(answer[4][0]).is_global for answer in answers
        ):
            raise ValueError
    except (OSError, ValueError, TimeoutError):
        raise APIError(
            422, "BROWSER_DESTINATION_REJECTED", "Use an available public website."
        ) from None


def tab_view(value):
    if not isinstance(value, dict):
        return None
    target = value.get("targetId")
    if not isinstance(target, str) or not 1 <= len(target) <= 256:
        return None
    url = value.get("url", "")
    # A browser's internal pages and debugging addresses are not customer links.
    try:
        url = public_url(url)
    except ValueError:
        url = ""
    return {"id": target, "title": public_text(value.get("title", ""), limit=300), "url": url}


async def browser_call(gateway, method, path, body=None):
    params = {
        "method": method,
        "path": path,
        "query": {"profile": PROFILE},
        "target": "host",
        "timeoutMs": 45000,
    }
    if body is not None:
        params["body"] = body
    try:
        return await gateway.call("browser.request", params)
    except APIError as error:
        if error.code in {"GATEWAY_REJECTED", "GATEWAY_PROTOCOL_ERROR"}:
            raise APIError(
                503,
                "BROWSER_UNAVAILABLE",
                "The workspace browser is unavailable. Check its runtime setup.",
            ) from None
        raise


async def connection_view(gateway):
    status = await browser_call(gateway, "GET", "/")
    running = status.get("running") is True
    ready = running and status.get("cdpReady") is not False
    tabs = []
    if ready:
        result = await browser_call(gateway, "GET", "/tabs")
        rows = result.get("tabs", [])
        if not isinstance(rows, list):
            raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid browser response.")
        tabs = [view for row in rows[:100] if (view := tab_view(row))]
    return {
        "connected": ready,
        "running": running,
        "state": "connected" if ready else "starting" if running else "disconnected",
        "tabs": tabs,
    }


def install_browser_routes(router):
    @router.get("/browser")
    async def browser_status(request: Request):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            result = await connection_view(gateway)
            await guard.valid()
            return result

    @router.post("/browser/connect")
    async def connect_browser(request: Request, body: Input):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            await browser_call(gateway, "POST", "/start", {})
            result = await connection_view(gateway)
            await guard.valid()
            return result

    @router.post("/browser/disconnect")
    async def disconnect_browser(request: Request, body: Input):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            await browser_call(gateway, "POST", "/stop", {})
            result = await connection_view(gateway)
            await guard.valid()
            return result

    @router.post("/browser/tabs", status_code=201)
    async def open_tab(request: Request, body: OpenTab):
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            await check_destination(body.url)
            result = await browser_call(gateway, "POST", "/tabs/open", {"url": body.url})
            await guard.valid()
            view = tab_view(result)
            if not view:
                raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid browser response.")
            return {"tab": view}

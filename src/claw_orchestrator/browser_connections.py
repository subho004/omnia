"""Persistent browser connection state per instance."""

import ipaddress
import uuid

from fastapi import Request
from pydantic import BaseModel, Field, field_validator

from .browser_api import public_url as validate_public_url
from .browser_api import tab_view
from .errors import APIError
from .frontend_api import Input, owned_gateway


class TabView(BaseModel):
    id: str
    title: str
    url: str
    opened_at: str | None = None
    last_active: str | None = None


class BrowserConnectionView(BaseModel):
    id: str
    instance_id: str
    tab_id: str
    url: str
    title: str
    status: str
    error: str | None = None
    created_at: str
    updated_at: str | None = None
    tabs: list[TabView] = []


class BrowserConnectionCreated(BaseModel):
    connection_id: str
    tab_id: str
    url: str
    title: str
    status: str


class BrowserConnectionDeleted(BaseModel):
    found: bool
    deleted: bool


class OpenTabInput(Input):
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        """Validate URL format."""
        from urllib.parse import urlsplit

        url = urlsplit(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme not in {"http", "https"} or not host or url.username or url.password:
            raise ValueError("URL must be public HTTP/HTTPS without credentials")
        if url.port not in (None, 80, 443):
            raise ValueError("Port must be 80, 443, or None")
        if (
            host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
            or "." not in host
        ):
            raise ValueError("Use a public domain with a registered TLD")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                raise ValueError("Invalid domain format")
        return value


class TabOpened(BaseModel):
    tab_id: str
    url: str
    title: str
    status: str

    _tab_view: object = None


async def public_url(value):
    return validate_public_url(value)


async def connection_view(gateway):
    """Get current browser connection status and tabs."""
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


async def browser_call(gateway, method, path, body=None):
    """Make a browser control API call."""
    params = {
        "method": method,
        "path": path,
        "query": {"profile": "openclaw"},
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


async def create_browser_connection(db, instance_id: str, url: str, session_key: str):
    """Create a persistent browser connection for an instance."""
    if instance_id is None:
        raise APIError(400, "INSTANCE_REQUIRED", "An instance must be created first.")

    async with db.connection() as conn:
        # Check if a connection already exists for this instance and URL
        existing = await conn.fetchrow(
            """
            SELECT id, tab_id, url, status, created_at
            FROM browser_connections
            WHERE instance_id = $1 AND url = $2 AND status != 'deleted'
            ORDER BY created_at DESC
            LIMIT 1
        """,
            instance_id,
            url,
        )

        if existing:
            return {
                "connection_id": existing["id"],
                "tab_id": existing["tab_id"],
                "url": existing["url"],
                "title": existing.get("title", "No title"),
                "status": existing["status"],
            }

        # Generate new connection ID
        connection_id = str(uuid.uuid4())

        # Determine tab_id from connection_id (first 8 chars)
        tab_id = connection_id[:8]

        try:
            # Get session key for authentication
            _ = session_key.split(":")[2] if ":agent:main:" in session_key else session_key

            async with conn.transaction():
                # Create the connection record
                await conn.execute(
                    """
                    INSERT INTO browser_connections
                    (instance_id, tab_id, url, title, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    instance_id,
                    tab_id,
                    url,
                    "disconnected",
                )

                return {
                    "connection_id": connection_id,
                    "tab_id": tab_id,
                    "url": url,
                    "title": "No title",
                    "status": "disconnected",
                }
        except Exception as e:
            raise APIError(500, "DATABASE_ERROR", "Failed to create browser connection.") from e


async def delete_browser_connection(db, connection_id: str):
    """Delete a browser connection."""
    async with db.connection() as conn:
        result = await conn.fetchrow(
            """
            DELETE FROM browser_connections
            WHERE id = $1 AND status != 'deleted'
            RETURNING id
        """,
            connection_id,
        )

        return {
            "found": result is not None,
            "deleted": result is not None,
        }


async def list_browser_connections(db, instance_id: str | None = None, limit: int = 50):
    """List browser connections for an instance or all instances."""
    async with db.connection() as conn:
        if instance_id is None:
            query = """
                SELECT id, instance_id, tab_id, url, title, status, created_at
                FROM browser_connections
                WHERE status != 'deleted'
                ORDER BY instance_id, created_at DESC
            """
        else:
            query = """
                SELECT id, instance_id, tab_id, url, title, status, created_at
                FROM browser_connections
                WHERE instance_id = $1 AND status != 'deleted'
                ORDER BY created_at DESC
            """

        rows = await conn.fetch(query, instance_id)
        return list(rows)[:limit]


async def open_tab(db, gateway, connection_id: str, url: str):
    """Open a new browser tab."""
    # Validate URL
    await public_url(url)

    async with owned_gateway(gateway, automation_write=True) as (gateway2, guard):
        # Actually open the tab in the browser
        await browser_call(gateway, "POST", "/tabs/open", {"url": url})

        # Update the connection record with the new tab
        async with db.connection() as conn:
            # Get existing connection
            conn_data = await conn.fetchrow(
                """
                SELECT id, tab_id, url, title, status
                FROM browser_connections
                WHERE id = $1
            """,
                connection_id,
            )

            if not conn_data:
                raise APIError(404, "CONNECTION_NOT_FOUND", "Browser connection not found.")

            # Get tab info from gateway
            status = await browser_call(gateway, "GET", "/tabs")
            tabs = status.get("tabs", [])
            new_tab = None
            for tab in tabs:
                if tab["url"] == url:
                    new_tab = {
                        "id": tab["id"],
                        "title": tab["title"],
                        "url": tab["url"],
                    }
                    break

            if new_tab:
                await conn.execute(
                    """
                    UPDATE browser_connections
                    SET tab_id = $1, title = $2, status = 'connected', updated_at = NOW()
                    WHERE id = $3
                """,
                    new_tab["id"],
                    new_tab["title"],
                    connection_id,
                )

            return {
                "connection_id": connection_id,
                "tab": new_tab,
            }


def install_browser_connections_routes(tenant_router):
    """Register browser connection routes on the tenant API."""
    from fastapi import Request

    @tenant_router.post("/browser/create", response_model=BrowserConnectionCreated)
    async def create_connection(request: Request, body: OpenTabInput):
        """Create a persistent browser connection."""
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            principal = guard.principal
            params = {
                "url": body.url,
                "instance_id": principal.instance_id,
                "session_key": principal.session_key,
            }
            result = await create_browser_connection(
                tenant_router.app.state.db,
                params["instance_id"],
                params["url"],
                params["session_key"],
            )
            return result

    @tenant_router.delete("/browser/{connection_id}", response_model=BrowserConnectionDeleted)
    async def delete_connection(request: Request, connection_id: str):
        """Delete a browser connection."""
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            result = await delete_browser_connection(
                tenant_router.app.state.db,
                connection_id,
            )
            return result

    @tenant_router.get("/browser/connections", response_class=BrowserConnectionView)
    async def list_connections(request: Request, instance_id: str | None = None):
        """List browser connections."""
        async with owned_gateway(request) as (gateway, guard):
            instance_id = instance_id or guard.principal.instance_id
            connections = await list_browser_connections(
                tenant_router.app.state.db,
                instance_id,
            )
            # Add browser status to each connection
            results = []
            for conn in connections:
                conn_data = await connection_view(gateway)
                results.append(
                    {
                        **conn,
                        "browser": conn_data,
                    }
                )
            return results


# Shared URL validation
async def check_destination(url: str):
    """Validate URL format without creating a connection record."""
    await public_url(url)


def install_browser_routes(router):
    """Register browser control routes on the frontend API."""
    install_browser_connections_routes(router)

    @router.post("/browser/tabs", status_code=201, response_class=TabOpened)
    async def open_tab(request: Request, body: OpenTabInput):
        """Open a new browser tab."""
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            await check_destination(body.url)
            result = await browser_call(gateway, "POST", "/tabs/open", {"url": body.url})
            await guard.valid()
            view = tab_view(result)
            if not view:
                raise APIError(502, "GATEWAY_PROTOCOL_ERROR", "Invalid browser response.")
            return {"tab": view}

    @router.get("/browser")
    async def browser_status(request: Request):
        """Check browser connection status."""
        async with owned_gateway(request) as (gateway, guard):
            result = await connection_view(gateway)
            await guard.valid()
            return result

    @router.post("/browser/disconnect")
    async def disconnect_browser(request: Request, body: Input):
        """Disconnect the browser."""
        async with owned_gateway(request, automation_write=True) as (gateway, guard):
            await browser_call(gateway, "POST", "/stop", {})
            result = await connection_view(gateway)
            await guard.valid()
            return result

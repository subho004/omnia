import asyncio
import os
import secrets
from urllib.parse import quote

import asyncpg
import httpx
import pytest
from dotenv import dotenv_values
from starlette.testclient import TestClient

from claw_orchestrator.app import create_app
from claw_orchestrator.config import Settings
from claw_orchestrator.runtime import RuntimeResult


class TestRuntime:
    __test__ = False
    available = True
    reason = "Test-only upstream; not an OpenClaw or Docker runtime."
    upstream_url = "http://127.0.0.1:19001/"

    async def provision(self, instance):
        return RuntimeResult(
            str(instance["id"]),
            self.upstream_url,
            f"openshell-test--{instance['sandbox_name']}-{instance['id']}",
        )

    async def probe(self, instance):
        return True


@pytest.fixture(scope="session")
def test_settings():
    # Every run has its own disposable database; never truncate the working database.
    env = {**dotenv_values(".env"), **os.environ}
    name = "claw_test_" + secrets.token_hex(8)
    admin = (
        f"postgresql://{quote(env['POSTGRES_USER'], safe='')}:"
        f"{quote(env['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:"
        f"{env.get('POSTGRES_PORT', '5432')}/postgres"
    )
    settings = Settings(postgres_db=name, jwt_secret=secrets.token_urlsafe(48), egress_proxy_port=0)

    async def prepare():
        conn = await asyncpg.connect(admin)
        try:
            await conn.execute(f'CREATE DATABASE "{name}" OWNER claw_api')
        finally:
            await conn.close()
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute("CREATE SCHEMA claw AUTHORIZATION claw_api")
        finally:
            await conn.close()

    asyncio.run(prepare())
    yield settings

    async def cleanup():
        conn = await asyncpg.connect(admin)
        try:
            await conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await conn.close()

    asyncio.run(cleanup())


@pytest.fixture
def client(test_settings):
    app = create_app(test_settings, TestRuntime(), start_worker=False)
    with TestClient(
        app,
        base_url=test_settings.control_origin,
        client=("127.0.0.1", 50000),
        follow_redirects=False,
    ) as client:

        async def clean():
            async with app.state.db.connection() as conn:
                await conn.execute(
                    "DELETE FROM automation_mutations; "
                    "DELETE FROM launch_tickets; DELETE FROM provisioning_jobs; "
                    "DELETE FROM instances; DELETE FROM sessions"
                )

        client.portal.call(clean)
        yield client


@pytest.fixture
def upstream(client):
    seen = []

    class ByteStream(httpx.AsyncByteStream):
        def __init__(self, value):
            self.value = value

        async def __aiter__(self):
            yield self.value

    async def handler(request):
        seen.append(request)
        return httpx.Response(
            200, stream=ByteStream(f"private-marker-for-{request.headers['x-claw-user']}".encode())
        )

    async def replace():
        await client.app.state.http.aclose()
        client.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    client.portal.call(replace)
    return seen

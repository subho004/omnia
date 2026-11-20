from uuid import UUID, uuid4

from test_control import launch, login, post

from claw_orchestrator.provisioning import provision_one


def test_expired_job_is_reconciled_with_same_identity(client):
    token = login(client)
    row = post(client, "/api/instance", token).json()["instance"]
    iid = UUID(row["id"])

    async def interrupt():
        async with client.app.state.db.connection() as conn:
            await conn.execute(
                "UPDATE provisioning_jobs SET status='running',attempts=1,"
                "lease_until=now()-interval '1 second' WHERE instance_id=$1",
                iid,
            )

    client.portal.call(interrupt)
    assert client.portal.call(provision_one, client.app.state.db, client.app.state.runtime)
    updated = client.get("/api/instance").json()["instance"]
    assert updated["id"] == str(iid) and updated["status"] == "ready"

    async def inspect():
        async with client.app.state.db.connection() as conn:
            assert await conn.fetchval("SELECT attempts FROM provisioning_jobs") == 2
            assert (
                await conn.fetchval("SELECT volume_name FROM instances") == f"openclaw-data-{iid}"
            )

    client.portal.call(inspect)


def test_failed_job_retains_identity_and_is_not_recreated(client):
    token = login(client)
    iid = post(client, "/api/instance", token).json()["instance"]["id"]

    async def fail(instance):
        raise RuntimeError("private runtime diagnostic that must not reach users")

    client.app.state.runtime.provision = fail
    client.portal.call(provision_one, client.app.state.db, client.app.state.runtime)
    row = client.get("/api/instance").json()["instance"]
    assert row["id"] == iid and row["status"] == "failed"
    response = post(client, "/api/instance", token)
    assert response.status_code == 409 and "private runtime" not in response.text


def test_wrong_host_does_not_consume_valid_launch_ticket(client):
    import re

    from test_control import ready

    token = login(client)
    iid = ready(client, token)
    response = post(client, "/api/instance/launch", token)
    ticket = re.search(r'name="ticket" value="([^"]+)"', response.text)[1]
    control = str(client.base_url).rstrip("/")
    wrong = client.app.state.settings.instance_origin(str(uuid4()))
    assert (
        client.post(
            wrong + "/__orchestrator/launch", data={"ticket": ticket}, headers={"origin": control}
        ).status_code
        == 401
    )
    correct = client.app.state.settings.instance_origin(iid)
    assert (
        client.post(
            correct + "/__orchestrator/launch", data={"ticket": ticket}, headers={"origin": control}
        ).status_code
        == 303
    )
    # A new ticket still works after a rejected foreign-Origin attempt.
    launch(client, token, iid)


def test_repeated_crash_recovery_is_bounded_and_retains_volume(client):
    token = login(client)
    iid = post(client, "/api/instance", token).json()["instance"]["id"]

    async def exhausted():
        async with client.app.state.db.connection() as conn:
            await conn.execute(
                "UPDATE provisioning_jobs SET status='running',attempts=3,"
                "lease_until=now()-interval '1 second'"
            )

    client.portal.call(exhausted)
    assert client.portal.call(provision_one, client.app.state.db, client.app.state.runtime)
    row = client.get("/api/instance").json()["instance"]
    assert row["id"] == iid and row["status"] == "failed" and row["error_code"] == "RECOVERY_LIMIT"
    assert not client.portal.call(provision_one, client.app.state.db, client.app.state.runtime)


def test_retained_recovery_requires_health_and_preserves_both_owners_resources(client):
    from test_control import ready

    from claw_orchestrator.provisioning import recover_retained

    first = ready(client, login(client, "user1"))
    ready(client, login(client, "user2"))

    async def interrupt():
        async with client.app.state.db.connection() as conn:
            await conn.execute("UPDATE instances SET status='unavailable'")
            return [
                dict(row)
                for row in await conn.fetch("SELECT * FROM instances ORDER BY owner_user_id")
            ]

    before = client.portal.call(interrupt)
    checked = []

    async def probe(row):
        checked.append(str(row["id"]))
        return str(row["id"]) == first

    client.app.state.runtime.probe = probe
    assert client.portal.call(recover_retained, client.app.state.db, client.app.state.runtime) == 1
    assert set(checked) == {str(row["id"]) for row in before}

    async def inspect():
        async with client.app.state.db.connection() as conn:
            after = await conn.fetch("SELECT * FROM instances ORDER BY owner_user_id")
            for old, new in zip(before, after, strict=True):
                for field in (
                    "id",
                    "owner_user_id",
                    "runtime_id",
                    "container_name",
                    "volume_name",
                    "upstream_url",
                ):
                    assert old[field] == new[field]
                assert new["status"] == ("ready" if str(new["id"]) == first else "unavailable")
            assert (
                await conn.fetchval("SELECT count(*) FROM provisioning_jobs WHERE status!='done'")
                == 0
            )

    client.portal.call(inspect)


def test_retained_recovery_rejects_stale_health_and_does_not_retry_failed_provisioning(client):
    from test_control import ready

    from claw_orchestrator.provisioning import recover_retained

    ready(client, login(client))

    async def mark(status):
        async with client.app.state.db.connection() as conn:
            await conn.execute("UPDATE instances SET status=$1", status)

    client.portal.call(mark, "unavailable")
    checked = []

    async def stale_probe(row):
        checked.append(row["id"])
        async with client.app.state.db.connection() as conn:
            await conn.execute(
                "UPDATE instances SET runtime_id='replacement-identity' WHERE id=$1", row["id"]
            )
        return True

    client.app.state.runtime.probe = stale_probe
    assert client.portal.call(recover_retained, client.app.state.db, client.app.state.runtime) == 0
    assert client.get("/api/instance").json()["instance"]["status"] == "unavailable"
    client.portal.call(mark, "failed")
    assert client.portal.call(recover_retained, client.app.state.db, client.app.state.runtime) == 0
    assert len(checked) == 1

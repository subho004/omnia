# Database

PostgreSQL 18 stores control-plane metadata only. Tenant data lives in the instance volumes, not here.

## Compose service

`compose.yaml` defines one service, `db`, on a private `control_plane` bridge network.

- Image `postgres:18`, `PGDATA=/var/lib/postgresql/18/docker`.
- The repo's `./db/` is bind-mounted at `/var/lib/postgresql`, so the cluster lives in `./db/18/docker/`. `./db/` and `.env` are gitignored.
- The host port is published on `127.0.0.1:${POSTGRES_PORT:-5432}` only.
- `infra/postgres/init-app.sql` is mounted read-only into `docker-entrypoint-initdb.d/10-app.sql`.
- `POSTGRES_PASSWORD` and `POSTGRES_APP_PASSWORD` are required. Compose refuses to start if either is empty.
- The health check runs `pg_isready` and logs in as `claw_api`.

Never attach tenant workloads to the database network. A future API container on the same network would use host `db`, port 5432.

## Roles and schema

| Role | Purpose |
| --- | --- |
| `claw_admin` (`POSTGRES_USER`) | Bootstrap administrator. The API never uses it. |
| `claw_api` | `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION`. Owns the `claw` schema. `search_path` is `claw, public`. |

`CREATE` on `public` is revoked from `PUBLIC`. The API connects as `claw_api` with a pool of 1 to 6 connections and a 5 second command timeout.

## Initialization and credentials

Initialization variables apply only to a new cluster. Changing `.env` later does not rotate passwords or rename the database. Make such changes through PostgreSQL. For a cluster created before the app-role initializer existed, run `infra/postgres/init-app.sql` once as the administrator. Never delete `db/` to fix a startup problem.

## Migrations

`Database.open()` runs `src/claw_orchestrator/migrations/*.sql` in filename order. It takes an advisory lock (`pg_advisory_xact_lock(532807120)`), so concurrent starts serialize. Each unapplied file runs in the same transaction as its `schema_migrations` insert. To add one, create the next numbered file and restart the API.

| Migration | Adds |
| --- | --- |
| `001_initial` | `users`, `sessions`, `instances`, `provisioning_jobs`, `launch_tickets` |
| `002_native_container_names` | Renames `container_name` to `sandbox_name`. Adds a unique `container_name` for the native name. |
| `003_approval_reviews` | `approval_reviews` (review tokens with `expires_at`) |
| `004_automation_mutations` | `automation_mutations` (idempotency ledger) |
| `005_global_automations` | `automations` |
| `006_browser_connections` | `browser_connections` |
| `007_automation_members` | `automation_members` |

## Core tables

- **`users`**: fixed rows `user1`/`user2` (`CHECK (id IN ('user1','user2'))`).
- **`sessions`**: `sid`, `user_id`, `csrf_token`, `issued_at`, `expires_at`, `revoked_at`. Unique on `(sid, user_id)`.
- **`instances`**: `id` (UUID), `owner_user_id` (**unique**, one instance per user), `status` (`pending`, `provisioning`, `ready`, `failed`, `unavailable`), `sandbox_name`, `container_name` (unique), `volume_name` (unique), `runtime_id`, `upstream_url`, `error_code`, timestamps. Unique on `(id, owner_user_id)`, which launch tickets reference.
- **`provisioning_jobs`**: one row per instance with `status` (`pending`, `running`, `done`, `failed`), `attempts`, `lease_until`, `error_code`.
- **`launch_tickets`**: SHA-256 `ticket_hash`, session, owner, instance, `target_origin`, `expires_at`, `consumed_at`.
- **`approval_reviews`**: review-token state used by the approvals API.
- **`automation_mutations`**: owner and instance-bound idempotency keys, request hashes and outcomes.

## Tables not used by the current code

The live automation and browser routes talk to the instance's native gateway, not these tables:

- `automations` and `automation_members` (migrations 005 and 007) are only referenced by helper functions in `automations.py` that no route calls.
- `browser_connections` (migration 006) is only referenced by `browser_connections.py`, which no module imports.

They are scaffolding for a future persistence design. Do not rely on them.

## Operations

```sh
# SQL shell
docker compose exec db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
# Stop, keeping data
docker compose down
```

Use database-aware backups (for example `pg_dump`) and a supported upgrade procedure before changing the PostgreSQL major version.

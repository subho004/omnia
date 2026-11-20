CREATE TABLE users (
    id text PRIMARY KEY CHECK (id IN ('user1', 'user2')),
    display_name text NOT NULL
);
INSERT INTO users VALUES ('user1', 'User1'), ('user2', 'User2');

CREATE TABLE sessions (
    sid text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(id),
    csrf_token text NOT NULL,
    issued_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    UNIQUE (sid, user_id)
);
CREATE INDEX sessions_user_idx ON sessions(user_id);

CREATE TABLE instances (
    id uuid PRIMARY KEY,
    owner_user_id text NOT NULL UNIQUE REFERENCES users(id),
    status text NOT NULL CHECK (status IN ('pending','provisioning','ready','failed','unavailable')),
    container_name text NOT NULL UNIQUE,
    volume_name text NOT NULL UNIQUE,
    runtime_id text,
    upstream_url text,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, owner_user_id)
);

CREATE TABLE provisioning_jobs (
    instance_id uuid PRIMARY KEY REFERENCES instances(id),
    status text NOT NULL CHECK (status IN ('pending','running','done','failed')),
    attempts integer NOT NULL DEFAULT 0,
    lease_until timestamptz,
    error_code text
);
CREATE INDEX provisioning_jobs_pending_idx ON provisioning_jobs(status, lease_until);

CREATE TABLE launch_tickets (
    ticket_hash text PRIMARY KEY,
    sid text NOT NULL,
    owner_user_id text NOT NULL,
    instance_id uuid NOT NULL,
    target_origin text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    FOREIGN KEY (sid, owner_user_id) REFERENCES sessions(sid, user_id),
    FOREIGN KEY (instance_id, owner_user_id) REFERENCES instances(id, owner_user_id)
);
CREATE INDEX launch_tickets_session_idx ON launch_tickets(sid, owner_user_id);
CREATE INDEX launch_tickets_instance_idx ON launch_tickets(instance_id, owner_user_id);

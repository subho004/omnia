-- Persist browser connection state across sessions
CREATE TABLE browser_connections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id uuid NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    tab_id text NOT NULL,
    url text NOT NULL,
    title text,
    status text NOT NULL DEFAULT 'disconnected' CHECK (status IN ('disconnected', 'starting', 'connected', 'error')),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE
);
CREATE INDEX browser_connections_instance_idx ON browser_connections(instance_id);
CREATE INDEX browser_connections_status_idx ON browser_connections(status);

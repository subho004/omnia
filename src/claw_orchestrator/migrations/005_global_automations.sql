-- Store automations globally so they can be accessed from any instance
CREATE TABLE automations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    configuration jsonb NOT NULL DEFAULT '{}',
    owner_user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    owner_instance_id uuid REFERENCES instances(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'paused', 'error', 'deleted')),
    error_message text
);
CREATE INDEX automations_owner_idx ON automations(owner_user_id);
CREATE INDEX automations_status_idx ON automations(status);
CREATE INDEX automations_created_idx ON automations(created_at);

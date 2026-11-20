CREATE TABLE automation_mutations (
    instance_id uuid NOT NULL,
    owner_user_id text NOT NULL,
    operation text NOT NULL,
    idempotency_key text NOT NULL,
    payload_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'done', 'uncertain')),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instance_id, operation, idempotency_key),
    FOREIGN KEY (instance_id, owner_user_id) REFERENCES instances(id, owner_user_id)
);

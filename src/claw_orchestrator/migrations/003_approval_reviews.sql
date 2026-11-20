CREATE TABLE approval_reviews (
    ticket_hash text PRIMARY KEY,
    sid text NOT NULL,
    owner_user_id text NOT NULL,
    instance_id uuid NOT NULL,
    approval_id text NOT NULL,
    presentation_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    UNIQUE (sid, instance_id, approval_id),
    FOREIGN KEY (sid, owner_user_id) REFERENCES sessions(sid, user_id) ON DELETE CASCADE,
    FOREIGN KEY (instance_id, owner_user_id) REFERENCES instances(id, owner_user_id) ON DELETE CASCADE
);
CREATE INDEX approval_reviews_instance_idx ON approval_reviews(instance_id, owner_user_id);

-- Support for sharing automations between users/instances
CREATE TABLE automation_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_id uuid NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    member_user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (automation_id) REFERENCES automations(id) ON DELETE CASCADE
);
CREATE INDEX automation_members_automation_idx ON automation_members(automation_id);
CREATE INDEX automation_members_member_idx ON automation_members(member_user_id);
CREATE UNIQUE INDEX automation_members_unique ON automation_members(automation_id, member_user_id);

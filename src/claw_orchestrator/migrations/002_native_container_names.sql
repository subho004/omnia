ALTER TABLE instances RENAME COLUMN container_name TO sandbox_name;
ALTER TABLE instances ADD COLUMN container_name text UNIQUE;

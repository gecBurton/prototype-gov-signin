-- Executed once, on first init of the postgres_data volume (see
-- docker-entrypoint-initdb.d in the official postgres image). Creates a
-- second database, owned by the same "iam" user, for Ory Hydra — kept
-- separate from the "iam" database so Hydra's own migrations never touch
-- this app's tables, while still only requiring one Postgres server to run.
CREATE DATABASE hydra OWNER iam;

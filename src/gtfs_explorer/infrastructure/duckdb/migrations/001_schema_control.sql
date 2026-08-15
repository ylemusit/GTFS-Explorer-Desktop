CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL
);

CREATE TABLE schema_metadata (
    schema_version INTEGER NOT NULL CHECK (schema_version >= 0)
);

INSERT INTO schema_metadata (schema_version) VALUES (0);

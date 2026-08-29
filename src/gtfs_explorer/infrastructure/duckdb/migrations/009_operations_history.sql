CREATE TABLE operations (
    operation_id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL REFERENCES projects(project_id),
    operation_type VARCHAR NOT NULL
        CHECK (operation_type IN ('IMPORT', 'VALIDATION', 'EXPORT')),
    status VARCHAR NOT NULL
        CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    error_code VARCHAR,
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (
        (status = 'RUNNING' AND finished_at IS NULL)
        OR
        (status IN ('COMPLETED', 'FAILED', 'CANCELLED') AND finished_at IS NOT NULL)
    )
);

CREATE TABLE operation_import_details (
    operation_id VARCHAR PRIMARY KEY,
    feed_id VARCHAR NOT NULL REFERENCES feeds(feed_id),
    job_id VARCHAR NOT NULL UNIQUE REFERENCES import_jobs(job_id)
);

CREATE TABLE operation_validation_details (
    operation_id VARCHAR PRIMARY KEY,
    feed_id VARCHAR NOT NULL REFERENCES feeds(feed_id),
    validation_batch_id VARCHAR UNIQUE REFERENCES validation_runs(batch_id)
);

CREATE TABLE operation_export_details (
    operation_id VARCHAR PRIMARY KEY,
    feed_id VARCHAR NOT NULL REFERENCES feeds(feed_id),
    export_format VARCHAR NOT NULL,
    artifact_name VARCHAR,
    artifact_sha256 VARCHAR,
    artifact_size_bytes BIGINT CHECK (artifact_size_bytes IS NULL OR artifact_size_bytes >= 0),
    CHECK (artifact_sha256 IS NULL OR regexp_full_match(artifact_sha256, '^[0-9a-f]{64}$'))
);

CREATE INDEX idx_operation_import_details_feed_id ON operation_import_details(feed_id);
CREATE INDEX idx_operation_validation_details_feed_id ON operation_validation_details(feed_id);
CREATE INDEX idx_operation_export_details_feed_id ON operation_export_details(feed_id);

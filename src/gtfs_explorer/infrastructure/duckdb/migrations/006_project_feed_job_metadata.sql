CREATE TABLE projects (
    project_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    schema_version INTEGER NOT NULL
);

CREATE TABLE feeds (
    feed_id VARCHAR PRIMARY KEY,
    project_id VARCHAR NOT NULL REFERENCES projects(project_id),
    source_name VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    import_mode VARCHAR NOT NULL,
    spec_revision VARCHAR NOT NULL,
    importer_version VARCHAR NOT NULL,
    imported_at TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL
);

CREATE TABLE import_jobs (
    job_id VARCHAR PRIMARY KEY,
    feed_id VARCHAR NOT NULL REFERENCES feeds(feed_id),
    state VARCHAR NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    progress DOUBLE NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    error_code VARCHAR
);

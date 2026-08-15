CREATE TABLE validation_runs (
    batch_id VARCHAR PRIMARY KEY,
    feed_id VARCHAR NOT NULL REFERENCES feeds(feed_id),
    status VARCHAR NOT NULL,
    total_issue_count BIGINT NOT NULL CHECK (total_issue_count >= 0),
    stored_issue_count BIGINT NOT NULL CHECK (stored_issue_count >= 0),
    omitted_issue_count BIGINT NOT NULL CHECK (omitted_issue_count >= 0)
);

CREATE TABLE validation_issues (
    batch_id VARCHAR NOT NULL REFERENCES validation_runs(batch_id),
    position BIGINT NOT NULL CHECK (position > 0),
    fingerprint VARCHAR NOT NULL,
    validator VARCHAR NOT NULL,
    rule_code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    file_name VARCHAR,
    row_number BIGINT,
    field_name VARCHAR,
    entity_type VARCHAR,
    entity_id VARCHAR,
    message_key VARCHAR NOT NULL,
    message_parameters JSON NOT NULL,
    help_id VARCHAR NOT NULL,
    occurrence_count BIGINT NOT NULL CHECK (occurrence_count > 0),
    PRIMARY KEY (batch_id, position),
    UNIQUE (batch_id, fingerprint)
);

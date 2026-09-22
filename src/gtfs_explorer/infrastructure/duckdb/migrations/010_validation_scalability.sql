CREATE TABLE validation_run_metadata (
    batch_id VARCHAR PRIMARY KEY REFERENCES validation_runs(batch_id),
    execution_status VARCHAR NOT NULL,
    validation_outcome VARCHAR,
    detected_issue_count BIGINT NOT NULL CHECK (detected_issue_count >= 0),
    persisted_issue_count BIGINT NOT NULL CHECK (persisted_issue_count >= 0),
    detail_complete BOOLEAN NOT NULL,
    legacy_truncated BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    CHECK (validation_outcome IS NULL OR validation_outcome IN
        ('VALID', 'VALID_WITH_NOTICES', 'VALID_WITH_WARNINGS', 'INVALID')),
    CHECK (execution_status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'))
);

INSERT INTO validation_run_metadata (
    batch_id, execution_status, validation_outcome, detected_issue_count,
    persisted_issue_count, detail_complete, legacy_truncated
)
SELECT
    batch_id,
    CASE status
        WHEN 'RUNNING' THEN 'RUNNING'
        WHEN 'CANCELLED' THEN 'CANCELLED'
        WHEN 'IMPORT_FAILED' THEN 'FAILED'
        ELSE 'COMPLETED'
    END,
    CASE status
        WHEN 'INVALID' THEN 'INVALID'
        WHEN 'IMPORT_FAILED' THEN NULL
        WHEN 'VALID_WITH_WARNINGS' THEN 'VALID_WITH_WARNINGS'
        WHEN 'VALID' THEN CASE WHEN total_issue_count > 0 THEN 'VALID_WITH_NOTICES' ELSE 'VALID' END
        ELSE NULL
    END,
    total_issue_count,
    COALESCE((SELECT sum(i.occurrence_count) FROM validation_issues i
              WHERE i.batch_id = validation_runs.batch_id), 0),
    total_issue_count <= COALESCE((SELECT sum(i.occurrence_count) FROM validation_issues i
                                   WHERE i.batch_id = validation_runs.batch_id), 0),
    total_issue_count > COALESCE((SELECT sum(i.occurrence_count) FROM validation_issues i
                                  WHERE i.batch_id = validation_runs.batch_id), 0)
FROM validation_runs;

CREATE TABLE validation_severity_aggregates (
    batch_id VARCHAR NOT NULL REFERENCES validation_runs(batch_id),
    severity VARCHAR NOT NULL,
    occurrence_count BIGINT NOT NULL CHECK (occurrence_count >= 0),
    PRIMARY KEY (batch_id, severity)
);

CREATE TABLE validation_rule_aggregates (
    batch_id VARCHAR NOT NULL REFERENCES validation_runs(batch_id),
    validator VARCHAR NOT NULL,
    rule_code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    occurrence_count BIGINT NOT NULL CHECK (occurrence_count >= 0),
    affected_entity_count BIGINT,
    PRIMARY KEY (batch_id, validator, rule_code, severity, category)
);

INSERT INTO validation_severity_aggregates (batch_id, severity, occurrence_count)
SELECT batch_id, severity, sum(occurrence_count)
FROM validation_issues
GROUP BY batch_id, severity;

INSERT INTO validation_rule_aggregates (
    batch_id, validator, rule_code, severity, category, occurrence_count, affected_entity_count
)
SELECT batch_id, validator, rule_code, severity, category, sum(occurrence_count),
       count(DISTINCT CASE WHEN entity_type IS NULL OR entity_id IS NULL THEN NULL
                           ELSE entity_type || chr(31) || entity_id END)
FROM validation_issues
GROUP BY batch_id, validator, rule_code, severity, category;

CREATE INDEX idx_validation_issues_batch_severity_position
    ON validation_issues(batch_id, severity, position);
CREATE INDEX idx_validation_issues_batch_category_position
    ON validation_issues(batch_id, category, position);
CREATE INDEX idx_validation_issues_batch_rule_position
    ON validation_issues(batch_id, rule_code, position);
CREATE INDEX idx_validation_issues_batch_file_position
    ON validation_issues(batch_id, file_name, position);

UPDATE projects SET schema_version = 10;

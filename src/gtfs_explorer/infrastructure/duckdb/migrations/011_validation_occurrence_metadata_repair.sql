-- Repara bases locales que ya aplicaron la 010 con el contador de filas.
UPDATE validation_run_metadata AS metadata
SET
    persisted_issue_count = COALESCE((
        SELECT sum(issue.occurrence_count)
        FROM validation_issues AS issue
        WHERE issue.batch_id = metadata.batch_id
    ), 0),
    detail_complete = detected_issue_count <= COALESCE((
        SELECT sum(issue.occurrence_count)
        FROM validation_issues AS issue
        WHERE issue.batch_id = metadata.batch_id
    ), 0),
    legacy_truncated = detected_issue_count > COALESCE((
        SELECT sum(issue.occurrence_count)
        FROM validation_issues AS issue
        WHERE issue.batch_id = metadata.batch_id
    ), 0);

UPDATE projects SET schema_version = 11;

CREATE TABLE stg_source_inventory (
    original_name VARCHAR PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    content_sha256 VARCHAR NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    known_to_schedule_spec BOOLEAN NOT NULL,
    loaded_row_count BIGINT,
    staging_table_name VARCHAR
);

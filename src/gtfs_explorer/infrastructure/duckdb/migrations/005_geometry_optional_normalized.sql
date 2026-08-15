CREATE TABLE gtfs_shapes (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    shape_id VARCHAR, shape_pt_lat DOUBLE, shape_pt_lon DOUBLE, shape_pt_sequence BIGINT,
    shape_dist_traveled DOUBLE
);

CREATE TABLE gtfs_frequencies (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    trip_id VARCHAR, start_time_lexeme VARCHAR, start_time_service_seconds INTEGER,
    end_time_lexeme VARCHAR, end_time_service_seconds INTEGER, headway_secs BIGINT,
    exact_times SMALLINT
);

CREATE TABLE gtfs_transfers (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    from_stop_id VARCHAR, to_stop_id VARCHAR, from_route_id VARCHAR, to_route_id VARCHAR,
    from_trip_id VARCHAR, to_trip_id VARCHAR, transfer_type SMALLINT, min_transfer_time BIGINT
);

CREATE TABLE gtfs_feed_info (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    feed_publisher_name VARCHAR, feed_publisher_url VARCHAR, feed_lang VARCHAR, default_lang VARCHAR,
    feed_start_date_lexeme VARCHAR, feed_start_date DATE, feed_end_date_lexeme VARCHAR,
    feed_end_date DATE, feed_version VARCHAR, feed_contact_email VARCHAR, feed_contact_url VARCHAR
);

CREATE TABLE gtfs_attributions (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    attribution_id VARCHAR, agency_id VARCHAR, route_id VARCHAR, trip_id VARCHAR,
    organization_name VARCHAR, is_producer SMALLINT, is_operator SMALLINT, is_authority SMALLINT,
    attribution_url VARCHAR, attribution_email VARCHAR, attribution_phone VARCHAR
);

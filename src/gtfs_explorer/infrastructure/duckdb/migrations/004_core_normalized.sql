CREATE TABLE normalization_issues (
    issue_code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    file_name VARCHAR NOT NULL,
    row_number BIGINT,
    field_name VARCHAR,
    raw_value VARCHAR,
    message VARCHAR NOT NULL
);

CREATE TABLE gtfs_agency (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    agency_id VARCHAR, agency_name VARCHAR, agency_url VARCHAR, agency_timezone VARCHAR,
    agency_lang VARCHAR, agency_phone VARCHAR, agency_fare_url VARCHAR, agency_email VARCHAR,
    cemv_support SMALLINT
);

CREATE TABLE gtfs_stops (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    stop_id VARCHAR, stop_code VARCHAR, stop_name VARCHAR, tts_stop_name VARCHAR, stop_desc VARCHAR,
    stop_lat DOUBLE, stop_lon DOUBLE, zone_id VARCHAR, stop_url VARCHAR, location_type SMALLINT,
    parent_station VARCHAR, stop_timezone VARCHAR, wheelchair_boarding SMALLINT, level_id VARCHAR,
    platform_code VARCHAR, stop_access SMALLINT
);

CREATE TABLE gtfs_routes (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    route_id VARCHAR, agency_id VARCHAR, route_short_name VARCHAR, route_long_name VARCHAR,
    route_desc VARCHAR, route_type SMALLINT, route_url VARCHAR, route_color VARCHAR,
    route_text_color VARCHAR, route_sort_order BIGINT, continuous_pickup SMALLINT,
    continuous_drop_off SMALLINT, network_id VARCHAR, cemv_support SMALLINT
);

CREATE TABLE gtfs_trips (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    route_id VARCHAR, service_id VARCHAR, trip_id VARCHAR, trip_headsign VARCHAR, trip_short_name VARCHAR,
    direction_id SMALLINT, block_id VARCHAR, shape_id VARCHAR, wheelchair_accessible SMALLINT,
    bikes_allowed SMALLINT, cars_allowed SMALLINT, safe_duration_factor DOUBLE,
    safe_duration_offset DOUBLE
);

CREATE TABLE gtfs_stop_times (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    trip_id VARCHAR, arrival_time_lexeme VARCHAR, arrival_service_seconds INTEGER,
    departure_time_lexeme VARCHAR, departure_service_seconds INTEGER, stop_id VARCHAR,
    location_group_id VARCHAR, location_id VARCHAR, stop_sequence BIGINT, stop_headsign VARCHAR,
    start_pickup_drop_off_window_lexeme VARCHAR, start_pickup_drop_off_window_service_seconds INTEGER,
    end_pickup_drop_off_window_lexeme VARCHAR, end_pickup_drop_off_window_service_seconds INTEGER,
    pickup_type SMALLINT, drop_off_type SMALLINT, continuous_pickup SMALLINT,
    continuous_drop_off SMALLINT, shape_dist_traveled DOUBLE, timepoint SMALLINT,
    pickup_booking_rule_id VARCHAR, drop_off_booking_rule_id VARCHAR
);

CREATE TABLE gtfs_calendar (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    service_id VARCHAR, monday SMALLINT, tuesday SMALLINT, wednesday SMALLINT, thursday SMALLINT,
    friday SMALLINT, saturday SMALLINT, sunday SMALLINT, start_date_lexeme VARCHAR,
    start_date DATE, end_date_lexeme VARCHAR, end_date DATE
);

CREATE TABLE gtfs_calendar_dates (
    source_filename VARCHAR NOT NULL, source_row BIGINT NOT NULL, raw_values JSON NOT NULL,
    service_id VARCHAR, date_lexeme VARCHAR, date DATE, exception_type SMALLINT
);

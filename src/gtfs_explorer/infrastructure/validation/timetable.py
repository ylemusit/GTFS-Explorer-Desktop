"""Reglas GTFS Schedule para horarios de servicio y frecuencias."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeGuard

from gtfs_explorer.domain.validation import (
    LocalizedMessage,
    ValidationCategory,
    ValidationContext,
    ValidationEntity,
    ValidationIssue,
    ValidationSeverity,
)
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection


@dataclass(frozen=True)
class TimetableValidationRule:
    """Valida tiempos de servicio sin convertirlos a fechas u horas civiles."""

    connection: DatabaseConnection
    code: str = "GTFS_TIMETABLE_2026_04_27"
    severity: ValidationSeverity = ValidationSeverity.ERROR
    category: ValidationCategory = ValidationCategory.TIMETABLE

    def evaluate(self, _context: ValidationContext) -> Iterable[ValidationIssue]:
        rows = tuple(self._stop_time_rows())
        yield from _stop_time_conditions(rows)
        yield from _sequence_and_time_issues(rows)
        yield from self._frequency_issues()

    def _stop_time_rows(self) -> Iterable["_StopTime"]:
        for row in self.connection.execute(
            "SELECT source_row, trip_id, arrival_service_seconds, departure_service_seconds, "
            "stop_id, location_group_id, location_id, stop_sequence, "
            "start_pickup_drop_off_window_service_seconds, "
            "end_pickup_drop_off_window_service_seconds, pickup_type, drop_off_type, "
            "continuous_pickup, continuous_drop_off, timepoint "
            "FROM gtfs_stop_times ORDER BY trip_id, stop_sequence, source_row"
        ).fetchall():
            yield _StopTime(*row)

    def _frequency_issues(self) -> Iterable[ValidationIssue]:
        for source_row, trip_id, start, end in self.connection.execute(
            "SELECT source_row, trip_id, start_time_service_seconds, end_time_service_seconds "
            "FROM gtfs_frequencies ORDER BY trip_id, source_row"
        ).fetchall():
            if start is not None and end is not None and start >= end:
                yield _issue(
                    "GTFS_FREQUENCY_TIME_RANGE_INVALID",
                    "validation.frequency_time_range_invalid",
                    "frequencies.txt",
                    int(source_row),
                    "end_time",
                    str(trip_id),
                )


@dataclass(frozen=True)
class _StopTime:
    source_row: int
    trip_id: str | None
    arrival: int | None
    departure: int | None
    stop_id: str | None
    location_group_id: str | None
    location_id: str | None
    sequence: int | None
    window_start: int | str | None
    window_end: int | str | None
    pickup_type: int | None
    drop_off_type: int | None
    continuous_pickup: int | None
    continuous_drop_off: int | None
    timepoint: int | None

    @property
    def has_window(self) -> bool:
        return _is_informed(self.window_start) or _is_informed(self.window_end)

    @property
    def entity_id(self) -> str:
        return self.trip_id or ""


def _stop_time_conditions(rows: tuple[_StopTime, ...]) -> Iterable[ValidationIssue]:
    by_trip: dict[str, list[_StopTime]] = defaultdict(list)
    for row in rows:
        by_trip[row.entity_id].append(row)
        locations = sum(
            value is not None for value in (row.stop_id, row.location_group_id, row.location_id)
        )
        if locations != 1:
            yield _issue(
                "GTFS_STOP_TIME_LOCATION_EXCLUSIVE",
                "validation.stop_time_location_exclusive",
                "stop_times.txt",
                row.source_row,
                "stop_id",
                row.entity_id,
            )
        start_informed = _is_informed(row.window_start)
        end_informed = _is_informed(row.window_end)
        if start_informed != end_informed:
            yield _issue(
                "GTFS_STOP_TIME_WINDOW_PAIR_REQUIRED",
                "validation.stop_time_window_pair_required",
                "stop_times.txt",
                row.source_row,
                "start_pickup_drop_off_window",
                row.entity_id,
            )
        if _window_order_invalid(row.window_start, row.window_end):
            yield _issue(
                "GTFS_STOP_TIME_WINDOW_ORDER_INVALID",
                "validation.stop_time_window_order_invalid",
                "stop_times.txt",
                row.source_row,
                "end_pickup_drop_off_window",
                row.entity_id,
            )
        if row.has_window:
            if row.arrival is not None or row.departure is not None:
                yield _issue(
                    "GTFS_STOP_TIME_WINDOW_WITH_SCHEDULED_TIME",
                    "validation.stop_time_window_with_scheduled_time",
                    "stop_times.txt",
                    row.source_row,
                    "arrival_time",
                    row.entity_id,
                )
            if row.pickup_type in (0, 3):
                yield _issue(
                    "GTFS_STOP_TIME_WINDOW_PICKUP_FORBIDDEN",
                    "validation.stop_time_window_pickup_forbidden",
                    "stop_times.txt",
                    row.source_row,
                    "pickup_type",
                    row.entity_id,
                )
            if row.drop_off_type == 0:
                yield _issue(
                    "GTFS_STOP_TIME_WINDOW_DROP_OFF_FORBIDDEN",
                    "validation.stop_time_window_drop_off_forbidden",
                    "stop_times.txt",
                    row.source_row,
                    "drop_off_type",
                    row.entity_id,
                )
            if row.continuous_pickup not in (None, 1):
                yield _issue(
                    "GTFS_STOP_TIME_WINDOW_CONTINUOUS_PICKUP_FORBIDDEN",
                    "validation.stop_time_window_continuous_pickup_forbidden",
                    "stop_times.txt",
                    row.source_row,
                    "continuous_pickup",
                    row.entity_id,
                )
            if row.continuous_drop_off not in (None, 1):
                yield _issue(
                    "GTFS_STOP_TIME_WINDOW_CONTINUOUS_DROP_OFF_FORBIDDEN",
                    "validation.stop_time_window_continuous_drop_off_forbidden",
                    "stop_times.txt",
                    row.source_row,
                    "continuous_drop_off",
                    row.entity_id,
                )
        if row.timepoint == 1 and (row.arrival is None or row.departure is None):
            yield _issue(
                "GTFS_STOP_TIME_TIMEPOINT_SCHEDULE_REQUIRED",
                "validation.stop_time_timepoint_schedule_required",
                "stop_times.txt",
                row.source_row,
                "arrival_time" if row.arrival is None else "departure_time",
                row.entity_id,
            )
    for trip_rows in by_trip.values():
        for row in (trip_rows[0], trip_rows[-1]):
            if not row.has_window and row.arrival is None:
                yield _issue(
                    "GTFS_STOP_TIME_TERMINAL_ARRIVAL_REQUIRED",
                    "validation.stop_time_terminal_arrival_required",
                    "stop_times.txt",
                    row.source_row,
                    "arrival_time",
                    row.entity_id,
                )


def _is_informed(value: int | str | None) -> TypeGuard[int | str]:
    """Trata lexemas vacíos como ausencia, incluso antes de tipar el campo."""
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _window_order_invalid(start: int | str | None, end: int | str | None) -> bool:
    if not (_is_informed(start) and _is_informed(end)):
        return False
    if isinstance(start, int) and isinstance(end, int):
        return start > end
    if isinstance(start, str) and isinstance(end, str):
        return start > end
    return False


def _sequence_and_time_issues(rows: tuple[_StopTime, ...]) -> Iterable[ValidationIssue]:
    by_trip: dict[str, list[_StopTime]] = defaultdict(list)
    for row in rows:
        by_trip[row.entity_id].append(row)
    for trip_id, trip_rows in by_trip.items():
        seen_sequences: set[int] = set()
        previous_departure: int | None = None
        for row in trip_rows:
            if row.sequence is not None:
                if row.sequence in seen_sequences:
                    yield _issue(
                        "GTFS_STOP_SEQUENCE_DUPLICATED",
                        "validation.stop_sequence_duplicated",
                        "stop_times.txt",
                        row.source_row,
                        "stop_sequence",
                        trip_id,
                    )
                seen_sequences.add(row.sequence)
            if (
                row.arrival is not None
                and row.departure is not None
                and row.departure < row.arrival
            ):
                yield _issue(
                    "GTFS_STOP_TIME_DEPARTURE_BEFORE_ARRIVAL",
                    "validation.stop_time_departure_before_arrival",
                    "stop_times.txt",
                    row.source_row,
                    "departure_time",
                    trip_id,
                )
            if (
                previous_departure is not None
                and row.arrival is not None
                and row.arrival < previous_departure
            ):
                yield _issue(
                    "GTFS_STOP_TIME_SEQUENCE_REGRESSION",
                    "validation.stop_time_sequence_regression",
                    "stop_times.txt",
                    row.source_row,
                    "arrival_time",
                    trip_id,
                )
            if row.departure is not None:
                previous_departure = row.departure


def _issue(
    code: str,
    message_key: str,
    file_name: str,
    row_number: int,
    field_name: str,
    entity_id: str,
) -> ValidationIssue:
    return ValidationIssue(
        rule_code=code,
        severity=ValidationSeverity.ERROR,
        category=ValidationCategory.TIMETABLE,
        message=LocalizedMessage(message_key),
        file_name=file_name,
        row_number=row_number,
        field_name=field_name,
        entity=ValidationEntity("trip", entity_id),
    )

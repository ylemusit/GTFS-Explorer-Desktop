"""Pruebas de la matriz de horarios acotada por patrón GTFS."""

from __future__ import annotations

from gtfs_explorer.application.queries.timetable import TimetableQueries
from gtfs_explorer.domain.ports import PagedResult, PageRequest
from gtfs_explorer.domain.routes import TimelineStop, TripSummary


class _Repository:
    def __init__(
        self,
        trips: tuple[TripSummary, ...],
        timelines: dict[str, tuple[TimelineStop, ...]],
    ) -> None:
        self.trips = trips
        self.timelines = timelines
        self.trip_requests: list[PageRequest] = []
        self.timeline_requests: list[str] = []

    def trips_for_route_service_direction(
        self, route_id: str, service_id: str, direction_id: int | None, page: PageRequest
    ) -> PagedResult[TripSummary]:
        self.trip_requests.append(page)
        matching = tuple(
            trip
            for trip in self.trips
            if (trip.route_id, trip.service_id, trip.direction_id)
            == (route_id, service_id, direction_id)
        )
        return PagedResult(matching[page.offset : page.offset + page.limit], len(matching), page)

    def trip_timeline(self, trip_id: str, page: PageRequest) -> PagedResult[TimelineStop]:
        self.timeline_requests.append(trip_id)
        items = self.timelines[trip_id]
        return PagedResult(items[page.offset : page.offset + page.limit], len(items), page)


def _trip(trip_id: str) -> TripSummary:
    return TripSummary(trip_id, "R", "weekday", 0, None, None, None)


def _stop(sequence: int, stop_id: str, arrival: str | None, departure: str | None) -> TimelineStop:
    return TimelineStop(sequence, stop_id, stop_id, arrival, None, departure, None)


def test_matrix_groups_patterns_and_preserves_loops_missing_times_and_over_24h() -> None:
    trips = (_trip("A"), _trip("B"), _trip("C"))
    repository = _Repository(
        trips,
        {
            "A": (_stop(1, "S1", "24:05:00", "24:06:00"), _stop(2, "S2", None, "24:10:00")),
            "B": (_stop(1, "S1", "25:05:00", "25:06:00"), _stop(2, "S2", "25:10:00", None)),
            "C": (_stop(1, "S1", "26:05:00", "26:06:00"), _stop(2, "S1", "26:10:00", "26:11:00")),
        },
    )

    matrix = TimetableQueries(repository).matrix("R", "weekday", 0)

    assert matrix.total_trips == 3
    assert not matrix.truncated
    assert [len(pattern.columns) for pattern in matrix.patterns] == [2, 1]
    comparable = matrix.patterns[0]
    assert [column.trip_id for column in comparable.columns] == ["A", "B"]
    assert comparable.columns[0].cells[0].arrival_time == "24:05:00"
    assert comparable.columns[0].cells[1].arrival_time is None
    assert comparable.columns[1].cells[1].departure_time is None
    loop = matrix.patterns[1]
    assert [(row.stop_id, row.occurrence) for row in loop.rows] == [("S1", 1), ("S1", 1)]


def test_matrix_limits_preview_without_loading_thousands_and_exposes_full_export_scope() -> None:
    trips = tuple(_trip(f"T-{number:04d}") for number in range(1_000))
    repository = _Repository(
        trips,
        {trip.trip_id: (_stop(1, "S", "06:00:00", "06:00:00"),) for trip in trips},
    )

    matrix = TimetableQueries(repository).matrix("R", "weekday", 0, column_limit=3)

    assert repository.trip_requests == [PageRequest(limit=3)]
    assert repository.timeline_requests == ["T-0000", "T-0001", "T-0002"]
    assert matrix.total_trips == 1_000
    assert matrix.truncated
    assert matrix.export_scope.route_id == "R"
    assert matrix.export_scope.service_id == "weekday"
    assert matrix.export_scope.direction_id == 0
    assert [column.trip_id for column in matrix.patterns[0].columns] == [
        "T-0000",
        "T-0001",
        "T-0002",
    ]

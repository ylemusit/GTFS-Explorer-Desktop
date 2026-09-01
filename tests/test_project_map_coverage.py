from __future__ import annotations

import pytest

from gtfs_explorer.application.queries.project_map_coverage import (
    project_map_coverage,
    route_map_coverage,
)


class _Connection:
    def __init__(self, batches: list[list[tuple[object, object]]]) -> None:
        self._batches = iter(batches)
        self.queries: list[tuple[str, list[object]]] = []

    def execute(self, query: str, parameters: list[object] | None = None) -> "_Result":
        self.queries.append((query, parameters or []))
        return _Result(next(self._batches))


class _Result:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, object]]:
        return self._rows


def test_feed_bounds_ignore_invalid_coordinates_and_expand_one_point() -> None:
    connection = _Connection([[(float("nan"), -3.0), (181.0, 43.0), (-5.5, 43.5), (None, None)]])

    coverage = project_map_coverage(connection)

    assert coverage.source == "shapes"
    assert coverage.bounds == (-5.52, 43.48, -5.48, 43.52)


def test_route_bounds_use_the_joint_shape_extent() -> None:
    connection = _Connection([[(1.0, 40.0), (2.0, 41.0), (10.0, 50.0)]])

    coverage = route_map_coverage(connection, "R1")

    assert coverage.source == "route_shapes"
    assert coverage.bounds == (0.98, 39.98, 10.02, 50.02)
    assert connection.queries[0][1] == ["R1"]


def test_route_bounds_fallback_to_stops_when_shapes_are_empty() -> None:
    connection = _Connection([[], [(-5.0, 43.0), (-4.9, 43.1)]])

    coverage = route_map_coverage(connection, "R2")

    assert coverage.source == "route_stops"
    assert coverage.bounds == pytest.approx((-5.02, 42.98, -4.88, 43.12))

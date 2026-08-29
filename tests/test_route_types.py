from __future__ import annotations

from gtfs_explorer.domain.route_types import (
    CORE_ROUTE_TYPES,
    EXTENDED_ROUTE_TYPES,
    RouteTypeKind,
    classify_route_type,
    format_route_type,
)


def test_catalog_covers_core_and_documented_extended_route_types() -> None:
    assert set(CORE_ROUTE_TYPES) == {0, 1, 2, 3, 4, 5, 6, 7, 11, 12}
    assert len(EXTENDED_ROUTE_TYPES) == 81

    demand_response = classify_route_type(715)
    assert demand_response is not None
    assert demand_response.kind is RouteTypeKind.EXTENDED
    assert demand_response.name == "Demand and Response Bus Service"
    assert "715" in format_route_type(715)
    assert "extended" in format_route_type(715)

    other_extended = classify_route_type(1301)
    assert other_extended is not None
    assert other_extended.kind is RouteTypeKind.EXTENDED
    assert other_extended.name == "Telecabin Service"


def test_unknown_route_type_is_not_silently_mapped_to_a_core_type() -> None:
    unknown = classify_route_type(999)

    assert unknown is not None
    assert unknown.kind is RouteTypeKind.UNKNOWN
    assert "999" in format_route_type(999)
    assert "unknown" in format_route_type(999).casefold()

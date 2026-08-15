from __future__ import annotations

from pathlib import Path

import pytest

from gtfs_explorer.application.queries.subset import MiniGtfsSubsetQueries
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.domain.subset import (
    CoreStop,
    CoreSubsetSource,
    CoreTrip,
    SubsetIntegrityError,
    SubsetSelection,
    SubsetSelectionError,
    close_core_subset,
)
from gtfs_explorer.domain.subset_rules import (
    OptionalFilePolicy,
    OptionalReference,
    OptionalSubsetError,
    OptionalSubsetSource,
    close_optional_subset,
    optional_file_coverage,
)


def _source() -> CoreSubsetSource:
    return CoreSubsetSource(
        route_agencies=(("R1", "A1"), ("R2", "A2")),
        trips=(
            CoreTrip("T1", "R1", "S_WEEKDAY"),
            CoreTrip("T2", "R1", "S_SPECIAL"),
            CoreTrip("T3", "R2", "S_WEEKDAY"),
        ),
        stop_times=(("T1", "P1"), ("T1", "S_SHARED"), ("T2", "S2"), ("T3", "S_SHARED")),
        stops=(
            CoreStop("P1", None),
            CoreStop("S_SHARED", "P1"),
            CoreStop("S2", None),
        ),
        calendar_service_ids=frozenset({"S_WEEKDAY"}),
        calendar_date_service_ids=frozenset({"S_SPECIAL"}),
        agency_ids=frozenset({"A1", "A2"}),
    )


def test_closes_multiple_routes_agencies_shared_stops_and_station_ancestors() -> None:
    subset = close_core_subset(_source(), SubsetSelection(frozenset({"R1", "R2"})))

    assert subset.route_ids == frozenset({"R1", "R2"})
    assert subset.trip_ids == frozenset({"T1", "T2", "T3"})
    assert subset.stop_ids == frozenset({"P1", "S_SHARED", "S2"})
    assert subset.service_ids == frozenset({"S_WEEKDAY", "S_SPECIAL"})
    assert subset.calendar_service_ids == frozenset({"S_WEEKDAY"})
    assert subset.calendar_date_service_ids == frozenset({"S_SPECIAL"})
    assert subset.agency_ids == frozenset({"A1", "A2"})
    assert subset.report.count("stop") == 3


def test_calendar_dates_only_service_is_a_valid_core_closure() -> None:
    subset = close_core_subset(
        _source(), SubsetSelection(frozenset({"R1"}), trip_ids=frozenset({"T2"}))
    )

    assert subset.trip_ids == frozenset({"T2"})
    assert subset.calendar_service_ids == frozenset()
    assert subset.calendar_date_service_ids == frozenset({"S_SPECIAL"})


def test_rejects_empty_and_ambiguous_selections_with_a_reason() -> None:
    with pytest.raises(SubsetSelectionError, match="al menos una ruta"):
        SubsetSelection(frozenset())
    with pytest.raises(SubsetSelectionError, match="no deja ningún viaje"):
        close_core_subset(_source(), SubsetSelection(frozenset({"R2"}), trip_ids=frozenset({"T1"})))


def test_rejects_dangling_core_references_before_a_zip_can_be_written() -> None:
    source = _source()
    invalid = CoreSubsetSource(
        source.route_agencies,
        source.trips,
        (("T1", "MISSING_STOP"),),
        source.stops,
        source.calendar_service_ids,
        source.calendar_date_service_ids,
        source.agency_ids,
    )

    with pytest.raises(SubsetIntegrityError, match="paradas ausentes"):
        close_core_subset(invalid, SubsetSelection(frozenset({"R1"}), trip_ids=frozenset({"T1"})))


def test_application_query_uses_the_repository_without_leaking_storage_details() -> None:
    class Repository:
        def core_subset_source(self) -> CoreSubsetSource:
            return _source()

    subset = MiniGtfsSubsetQueries(Repository()).close(SubsetSelection(frozenset({"R2"})))
    assert subset.trip_ids == frozenset({"T3"})


def test_optional_coverage_is_explicit_for_every_registered_file() -> None:
    known = frozenset(load_schedule_spec(Path("schemas/gtfs_schedule/2026-04-27/spec.json")).files)

    coverage = optional_file_coverage(known)

    assert {entry.file_name for entry in coverage} == known
    policies = {entry.file_name: entry.policy for entry in coverage}
    assert len(policies) == 32
    assert {
        name: policies[name]
        for name in {
            "agency.txt",
            "stops.txt",
            "routes.txt",
            "trips.txt",
            "stop_times.txt",
            "calendar.txt",
            "calendar_dates.txt",
            "shapes.txt",
            "transfers.txt",
            "translations.txt",
            "feed_info.txt",
            "fare_products.txt",
        }
    } == {
        "agency.txt": OptionalFilePolicy.ERROR,
        "stops.txt": OptionalFilePolicy.ERROR,
        "routes.txt": OptionalFilePolicy.ERROR,
        "trips.txt": OptionalFilePolicy.ERROR,
        "stop_times.txt": OptionalFilePolicy.ERROR,
        "calendar.txt": OptionalFilePolicy.ERROR,
        "calendar_dates.txt": OptionalFilePolicy.ERROR,
        "shapes.txt": OptionalFilePolicy.FILTER,
        "transfers.txt": OptionalFilePolicy.FILTER,
        "translations.txt": OptionalFilePolicy.FILTER,
        "feed_info.txt": OptionalFilePolicy.INCLUDE,
        "fare_products.txt": OptionalFilePolicy.EXCLUDE,
    }


def test_optional_closure_filters_shared_relations_and_preserves_metadata() -> None:
    core = close_core_subset(_source(), SubsetSelection(frozenset({"R1"})))
    optional = close_optional_subset(
        core,
        OptionalSubsetSource(
            shape_ids_by_trip=(("T1", "SH1"), ("T3", "SH2")),
            references_by_file=(
                (
                    "transfers.txt",
                    (
                        OptionalReference("keep", stop_ids=frozenset({"S_SHARED", "S2"})),
                        OptionalReference("drop-route", route_ids=frozenset({"R2"})),
                    ),
                ),
                (
                    "attributions.txt",
                    (
                        OptionalReference("global"),
                        OptionalReference("drop-trip", trip_ids=frozenset({"T3"})),
                    ),
                ),
                (
                    "translations.txt",
                    (OptionalReference("keep-translation", stop_ids=frozenset({"S_SHARED"})),),
                ),
                ("feed_info.txt", (OptionalReference("feed"),)),
            ),
            present_files=frozenset(
                {
                    "shapes.txt",
                    "transfers.txt",
                    "attributions.txt",
                    "translations.txt",
                    "feed_info.txt",
                }
            ),
        ),
        frozenset(
            {"shapes.txt", "transfers.txt", "attributions.txt", "translations.txt", "feed_info.txt"}
        ),
    )

    assert optional.shape_ids == frozenset({"SH1"})
    assert optional.rows_for("transfers.txt") == frozenset({"keep"})
    assert optional.rows_for("attributions.txt") == frozenset({"global"})
    assert optional.rows_for("translations.txt") == frozenset({"keep-translation"})
    assert optional.rows_for("feed_info.txt") == frozenset({"feed"})


def test_optional_closure_rejects_unknown_files_instead_of_copying_them() -> None:
    core = close_core_subset(_source(), SubsetSelection(frozenset({"R1"})))

    with pytest.raises(OptionalSubsetError, match="desconocidos"):
        close_optional_subset(
            core,
            OptionalSubsetSource(present_files=frozenset({"publisher_extension.txt"})),
            frozenset({"feed_info.txt"}),
        )

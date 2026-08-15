"""Políticas explícitas para el cierre de opcionales de Mini-GTFS."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gtfs_explorer.domain.subset import CoreSubset


class OptionalFilePolicy(StrEnum):
    """Acción que el exportador deberá aplicar a un archivo conocido."""

    INCLUDE = "include"
    FILTER = "filter"
    EXCLUDE = "exclude"
    ERROR = "error"


@dataclass(frozen=True)
class OptionalFileCoverage:
    file_name: str
    policy: OptionalFilePolicy
    reason: str


@dataclass(frozen=True)
class OptionalReference:
    """Fila opcional identificable y las entidades core que referencia."""

    row_id: str
    stop_ids: frozenset[str] = frozenset()
    route_ids: frozenset[str] = frozenset()
    trip_ids: frozenset[str] = frozenset()
    service_ids: frozenset[str] = frozenset()
    agency_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class OptionalSubsetSource:
    """Relaciones opcionales ya normalizadas, sin detalles de almacenamiento."""

    shape_ids_by_trip: tuple[tuple[str, str], ...] = ()
    references_by_file: tuple[tuple[str, tuple[OptionalReference, ...]], ...] = ()
    present_files: frozenset[str] = frozenset()


@dataclass(frozen=True)
class OptionalSubset:
    """Cobertura y filas opcionales permitidas para el cierre core recibido."""

    coverage: tuple[OptionalFileCoverage, ...]
    shape_ids: frozenset[str]
    included_rows: tuple[tuple[str, frozenset[str]], ...]

    def rows_for(self, file_name: str) -> frozenset[str]:
        return dict(self.included_rows).get(file_name, frozenset())


class OptionalSubsetError(ValueError):
    """Un archivo o relación opcional no puede formar parte del subconjunto."""


_CORE_FILES = frozenset(
    {
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "calendar_dates.txt",
    }
)
_FILTERED_FILES = frozenset(
    {
        "shapes.txt",
        "frequencies.txt",
        "transfers.txt",
        "pathways.txt",
        "levels.txt",
        "location_groups.txt",
        "location_group_stops.txt",
        "booking_rules.txt",
        "translations.txt",
        "attributions.txt",
    }
)
_INCLUDED_FILES = frozenset({"feed_info.txt"})
_EXCLUDED_FILES = frozenset(
    {
        "fare_attributes.txt",
        "fare_rules.txt",
        "timeframes.txt",
        "rider_categories.txt",
        "fare_media.txt",
        "fare_products.txt",
        "fare_leg_rules.txt",
        "fare_leg_join_rules.txt",
        "fare_transfer_rules.txt",
        "areas.txt",
        "stop_areas.txt",
        "networks.txt",
        "route_networks.txt",
        "locations.geojson",
    }
)


def optional_file_coverage(known_files: frozenset[str]) -> tuple[OptionalFileCoverage, ...]:
    """Publica una política para cada archivo del registro versionado."""
    unclassified = known_files - _CORE_FILES - _FILTERED_FILES - _INCLUDED_FILES - _EXCLUDED_FILES
    if unclassified:
        raise OptionalSubsetError(_files_message("sin política", unclassified))
    return tuple(
        OptionalFileCoverage(name, _policy_for(name), _reason_for(name))
        for name in sorted(known_files)
    )


def close_optional_subset(
    core: CoreSubset, source: OptionalSubsetSource, known_files: frozenset[str]
) -> OptionalSubset:
    """Cierra opcionales soportados sin copiar desconocidos ni crear salida."""
    coverage = optional_file_coverage(known_files)
    unknown_present = source.present_files - known_files
    if unknown_present:
        raise OptionalSubsetError(_files_message("desconocidos", unknown_present))
    references = dict(source.references_by_file)
    unknown_references = references.keys() - known_files
    if unknown_references:
        raise OptionalSubsetError(
            _files_message("con referencias desconocidas", unknown_references)
        )
    shape_ids = frozenset(
        shape_id for trip_id, shape_id in source.shape_ids_by_trip if trip_id in core.trip_ids
    )
    included_rows: list[tuple[str, frozenset[str]]] = []
    for file_name, rows in sorted(references.items()):
        policy = _policy_for(file_name)
        if policy is OptionalFilePolicy.FILTER:
            included_rows.append(
                (
                    file_name,
                    frozenset(row.row_id for row in rows if _references_are_closed(row, core)),
                )
            )
        elif policy is OptionalFilePolicy.INCLUDE:
            included_rows.append((file_name, frozenset(row.row_id for row in rows)))
    return OptionalSubset(coverage, shape_ids, tuple(included_rows))


def _policy_for(file_name: str) -> OptionalFilePolicy:
    if file_name in _CORE_FILES:
        return OptionalFilePolicy.ERROR
    if file_name in _FILTERED_FILES:
        return OptionalFilePolicy.FILTER
    if file_name in _INCLUDED_FILES:
        return OptionalFilePolicy.INCLUDE
    if file_name in _EXCLUDED_FILES:
        return OptionalFilePolicy.EXCLUDE
    raise OptionalSubsetError(_files_message("sin política", {file_name}))


def _reason_for(file_name: str) -> str:
    policy = _policy_for(file_name)
    if policy is OptionalFilePolicy.ERROR:
        return "Lo gestiona el cierre core."
    if policy is OptionalFilePolicy.FILTER:
        return "Se conserva solo si sus referencias permanecen en el cierre."
    if policy is OptionalFilePolicy.INCLUDE:
        return "Es metadata global del feed."
    return "Requiere un cierre específico no soportado en esta versión."


def _references_are_closed(reference: OptionalReference, core: CoreSubset) -> bool:
    return (
        reference.stop_ids <= core.stop_ids
        and reference.route_ids <= core.route_ids
        and reference.trip_ids <= core.trip_ids
        and reference.service_ids <= core.service_ids
        and reference.agency_ids <= core.agency_ids
    )


def _files_message(subject: str, files: set[str] | frozenset[str]) -> str:
    return f"Archivos {subject}: {', '.join(sorted(files))}."

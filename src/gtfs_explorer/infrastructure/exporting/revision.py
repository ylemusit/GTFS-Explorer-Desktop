"""Cierre y materialización de exportaciones GTFS desde una revisión de trabajo."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from gtfs_explorer.domain.changesets import EntityKey, WorkingCopy
from gtfs_explorer.domain.exporting import ExportError, ExportManifest
from gtfs_explorer.domain.spec import ScheduleSpec
from gtfs_explorer.domain.subset import (
    CoreStop,
    CoreSubset,
    CoreSubsetSource,
    CoreTrip,
    SubsetSelection,
    close_core_subset,
)
from gtfs_explorer.infrastructure.exporting.atomic_output import CancellationCheck
from gtfs_explorer.infrastructure.exporting.gtfs_subset import (
    FormalValidator,
    MiniGtfsSubsetExporter,
    MiniGtfsTable,
)

_TABLE_TO_FILENAME = {
    "gtfs_agency": "agency.txt",
    "gtfs_stops": "stops.txt",
    "gtfs_routes": "routes.txt",
    "gtfs_trips": "trips.txt",
    "gtfs_stop_times": "stop_times.txt",
    "gtfs_calendar": "calendar.txt",
    "gtfs_calendar_dates": "calendar_dates.txt",
    "gtfs_shapes": "shapes.txt",
    "gtfs_frequencies": "frequencies.txt",
    "gtfs_transfers": "transfers.txt",
    "gtfs_feed_info": "feed_info.txt",
    "gtfs_attributions": "attributions.txt",
}

_FILENAME_TO_TABLE = {value: key for key, value in _TABLE_TO_FILENAME.items()}
_TIME_FIELDS = {
    "arrival_time": "arrival_time_lexeme",
    "departure_time": "departure_time_lexeme",
    "start_pickup_drop_off_window": "start_pickup_drop_off_window_lexeme",
    "end_pickup_drop_off_window": "end_pickup_drop_off_window_lexeme",
    "start_time": "start_time_lexeme",
    "end_time": "end_time_lexeme",
}
_DATE_FIELDS = {
    "start_date": "start_date_lexeme",
    "end_date": "end_date_lexeme",
    "date": "date_lexeme",
    "feed_start_date": "feed_start_date_lexeme",
    "feed_end_date": "feed_end_date_lexeme",
}
_TYPED_FIELDS = {
    "arrival_time": "arrival_service_seconds",
    "departure_time": "departure_service_seconds",
    "start_pickup_drop_off_window": "start_pickup_drop_off_window_service_seconds",
    "end_pickup_drop_off_window": "end_pickup_drop_off_window_service_seconds",
    "start_time": "start_time_service_seconds",
    "end_time": "end_time_service_seconds",
    "start_date": "start_date",
    "end_date": "end_date",
    "date": "date",
    "feed_start_date": "feed_start_date",
    "feed_end_date": "feed_end_date",
}


@dataclass(frozen=True)
class RevisionExportPreview:
    """Resultado de cierre antes de que un escritor publique un archivo."""

    revision_id: str
    selection: SubsetSelection
    subset: CoreSubset
    tables: tuple[MiniGtfsTable, ...]
    included_entities: tuple[EntityKey, ...]
    omitted_entities: tuple[EntityKey, ...]


class WorkingCopyGtfsBuilder:
    """Convierte una ``WorkingCopy`` en tablas GTFS cerradas y deterministas."""

    def __init__(self, working_copy: WorkingCopy, specification: ScheduleSpec) -> None:
        self._working_copy = working_copy
        self._specification = specification

    def preview(
        self,
        *,
        revision_id: str,
        selection: SubsetSelection | None = None,
        version_id: str | None = None,
    ) -> RevisionExportPreview:
        # Una nueva versión puede sustituir feed_version en la salida, pero
        # nunca debe mutar la WorkingCopy ni su estado persistente.
        entities = {
            key: copy.deepcopy(payload) for key, payload in self._working_copy.entities.items()
        }
        if version_id is not None:
            _validate_version_id(version_id)
            for key, payload in tuple(entities.items()):
                if key[0] == "gtfs_feed_info":
                    updated = dict(payload)
                    updated["feed_version"] = version_id
                    updated["feed_version_lexeme"] = version_id
                    entities[key] = updated
        source = _core_source(entities)
        selected = selection or SubsetSelection(
            frozenset(route_id for route_id, _ in source.route_agencies)
        )
        subset = close_core_subset(source, selected)
        included = _included_entities(entities, subset)
        tables = tuple(
            self._table_for(filename, entities, included)
            for filename in self._files_to_export(included)
        )
        included_set = set(included)
        omitted = tuple(sorted(key for key in entities if key not in included_set))
        return RevisionExportPreview(
            revision_id,
            selected,
            subset,
            tables,
            tuple(sorted(included)),
            omitted,
        )

    def _files_to_export(self, included: tuple[EntityKey, ...]) -> tuple[str, ...]:
        selected_files = {
            _TABLE_TO_FILENAME[key[0]] for key in included if key[0] in _TABLE_TO_FILENAME
        }
        return tuple(sorted(selected_files))

    def _table_for(
        self,
        filename: str,
        entities: dict[EntityKey, dict[str, Any]],
        included: tuple[EntityKey, ...],
    ) -> MiniGtfsTable:
        table_name = _FILENAME_TO_TABLE[filename]
        fields = tuple(self._specification.files[filename].fields)
        included_set = set(included)
        rows = tuple(
            _row_for_payload(payload, fields)
            for key, payload in sorted(entities.items())
            if key[0] == table_name and key in included_set
        )
        return MiniGtfsTable(filename, fields, rows)


class RevisionGtfsExporter:
    """Publica una revisión confirmada después de mostrar su cierre."""

    def __init__(
        self,
        specification: ScheduleSpec,
        *,
        formal_validator: FormalValidator | None = None,
    ) -> None:
        self._specification = specification
        self._formal_validator = formal_validator

    def write(
        self,
        destination: Path,
        working_copy: WorkingCopy,
        *,
        revision_id: str,
        confirmed: bool,
        selection: SubsetSelection | None = None,
        version_id: str | None = None,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        """Escribe un ZIP solo cuando el llamador identifica una revisión confirmada."""
        if not confirmed or not revision_id or revision_id == "draft":
            raise ExportError(
                "No se puede exportar un borrador: confirme primero una revisión de trabajo."
            )
        if working_copy.dirty:
            raise ExportError(
                "No se puede exportar una working copy DIRTY; confirme primero la revisión."
            )
        if revision_id != working_copy.base_revision_id:
            raise ExportError("La exportación debe apuntar a la revisión activa.")
        preview = WorkingCopyGtfsBuilder(working_copy, self._specification).preview(
            revision_id=revision_id,
            selection=selection,
            version_id=version_id,
        )
        return MiniGtfsSubsetExporter(
            self._specification,
            formal_validator=self._formal_validator,
        ).write(
            destination,
            preview.tables,
            expected=preview.subset,
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={
                "revision_id": revision_id,
                "export_scope": "selected_routes" if selection is not None else "complete_modified",
                "version_id": version_id or revision_id,
            },
        )


def _core_source(entities: dict[EntityKey, dict[str, Any]]) -> CoreSubsetSource:
    routes = tuple(
        (str(payload["route_id"]), _optional_text(payload.get("agency_id")))
        for key, payload in sorted(entities.items())
        if key[0] == "gtfs_routes" and payload.get("route_id") is not None
    )
    trips = tuple(
        (
            str(payload["trip_id"]),
            str(payload["route_id"]),
            str(payload["service_id"]),
        )
        for key, payload in sorted(entities.items())
        if key[0] == "gtfs_trips"
        and payload.get("trip_id") is not None
        and payload.get("route_id") is not None
        and payload.get("service_id") is not None
    )
    stop_times = tuple(
        (str(payload["trip_id"]), str(payload["stop_id"]))
        for key, payload in sorted(entities.items())
        if key[0] == "gtfs_stop_times"
        and payload.get("trip_id") is not None
        and payload.get("stop_id") is not None
    )
    stops = tuple(
        (
            str(payload["stop_id"]),
            _optional_text(payload.get("parent_station")),
        )
        for key, payload in sorted(entities.items())
        if key[0] == "gtfs_stops" and payload.get("stop_id") is not None
    )
    return CoreSubsetSource(
        routes,
        tuple(CoreTrip(*value) for value in trips),
        stop_times,
        tuple(CoreStop(*value) for value in stops),
        frozenset(
            str(payload["service_id"])
            for key, payload in entities.items()
            if key[0] == "gtfs_calendar" and payload.get("service_id") is not None
        ),
        frozenset(
            str(payload["service_id"])
            for key, payload in entities.items()
            if key[0] == "gtfs_calendar_dates" and payload.get("service_id") is not None
        ),
        frozenset(
            str(payload["agency_id"])
            for key, payload in entities.items()
            if key[0] == "gtfs_agency" and payload.get("agency_id") is not None
        ),
    )


def _included_entities(
    entities: dict[EntityKey, dict[str, Any]], subset: CoreSubset
) -> tuple[EntityKey, ...]:
    included: list[EntityKey] = []
    shape_ids = {
        payload.get("shape_id")
        for key, payload in entities.items()
        if key[0] == "gtfs_trips" and payload.get("trip_id") in subset.trip_ids
    }
    for key, payload in entities.items():
        table = key[0]
        if table == "gtfs_agency":
            keep = payload.get("agency_id") in subset.agency_ids
        elif table == "gtfs_routes":
            keep = payload.get("route_id") in subset.route_ids
        elif table == "gtfs_trips":
            keep = payload.get("trip_id") in subset.trip_ids
        elif table == "gtfs_stop_times":
            keep = payload.get("trip_id") in subset.trip_ids
        elif table == "gtfs_stops":
            keep = payload.get("stop_id") in subset.stop_ids
        elif table == "gtfs_calendar":
            keep = payload.get("service_id") in subset.calendar_service_ids
        elif table == "gtfs_calendar_dates":
            keep = payload.get("service_id") in subset.calendar_date_service_ids
        elif table == "gtfs_shapes":
            keep = payload.get("shape_id") in shape_ids
        elif table == "gtfs_frequencies":
            keep = payload.get("trip_id") in subset.trip_ids
        elif table == "gtfs_transfers":
            keep = _optional_references_within(
                payload,
                (
                    ("from_stop_id", subset.stop_ids),
                    ("to_stop_id", subset.stop_ids),
                    ("from_route_id", subset.route_ids),
                    ("to_route_id", subset.route_ids),
                    ("from_trip_id", subset.trip_ids),
                    ("to_trip_id", subset.trip_ids),
                ),
            )
        elif table == "gtfs_attributions":
            keep = _optional_references_within(
                payload,
                (
                    ("agency_id", subset.agency_ids),
                    ("route_id", subset.route_ids),
                    ("trip_id", subset.trip_ids),
                ),
            )
        elif table == "gtfs_feed_info":
            keep = True
        else:
            keep = False
        if keep:
            included.append(key)
    return tuple(included)


def _optional_references_within(
    payload: dict[str, Any], references: tuple[tuple[str, frozenset[str]], ...]
) -> bool:
    present = [payload.get(field) for field, _ in references if payload.get(field) is not None]
    return bool(present) and all(
        payload.get(field) is None or payload.get(field) in values for field, values in references
    )


def _row_for_payload(payload: dict[str, Any], fields: tuple[str, ...]) -> tuple[str | None, ...]:
    raw = _raw_values(payload.get("raw_values"))
    result: list[str | None] = []
    for field in fields:
        lexeme_field = _TIME_FIELDS.get(field) or _DATE_FIELDS.get(field)
        if lexeme_field is not None and payload.get(lexeme_field) not in {None, ""}:
            value = payload[lexeme_field]
        elif field in _TYPED_FIELDS and payload.get(_TYPED_FIELDS[field]) is not None:
            value = _format_typed(field, payload[_TYPED_FIELDS[field]])
        elif field in payload:
            value = payload[field]
        else:
            value = raw.get(field)
        result.append(None if value is None else str(value))
    return tuple(result)


def _raw_values(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _format_typed(field: str, value: object) -> str:
    if field in _DATE_FIELDS:
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return value.strftime("%Y%m%d")
    if field in _TIME_FIELDS and isinstance(value, int):
        hours, remainder = divmod(value, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return str(value)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _validate_version_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ExportError("La nueva versión GTFS necesita un identificador corto no vacío.")
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ExportError("El identificador de versión GTFS contiene caracteres no permitidos.")

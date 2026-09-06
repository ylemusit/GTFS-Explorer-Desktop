"""Validación local e impactada del estado efectivo del borrador."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from gtfs_explorer.domain.changesets import EntityKey, ImpactAnalysis, WorkingCopy
from gtfs_explorer.domain.validation import (
    LocalizedMessage,
    ValidationCategory,
    ValidationEntity,
    ValidationIssue,
    ValidationSeverity,
)


@dataclass(frozen=True)
class ValidationImpact:
    """Identidad del lote de validación acotado a un impacto de comando."""

    command_id: str | None
    entity_keys: tuple[EntityKey, ...]

    @classmethod
    def from_analysis(
        cls, analysis: ImpactAnalysis, command_id: str | None = None
    ) -> "ValidationImpact":
        return cls(command_id, analysis.affected_entities)


class WorkingCopyValidator:
    """Comprueba reglas inmediatas sin modificar ni persistir la working copy."""

    def validate(
        self,
        working_copy: WorkingCopy,
        *,
        impact: ValidationImpact | None = None,
    ) -> tuple[ValidationIssue, ...]:
        entities = working_copy.entities
        scope = set(impact.entity_keys) if impact is not None else set(entities)
        issues = list(self._required_identifiers(entities, scope))
        issues.extend(self._references(entities, scope))
        issues.extend(self._geometry(entities, scope))
        issues.extend(self._times_and_sequences(entities, scope))
        issues.extend(self._calendar(entities, scope))
        return tuple(issues)

    def _required_identifiers(
        self, entities: dict[EntityKey, dict[str, object]], scope: set[EntityKey]
    ) -> Iterable[ValidationIssue]:
        fields = {
            "gtfs_agency": "agency_id",
            "gtfs_stops": "stop_id",
            "gtfs_routes": "route_id",
            "gtfs_trips": "trip_id",
            "gtfs_stop_times": "trip_id",
            "gtfs_calendar": "service_id",
            "gtfs_calendar_dates": "service_id",
            "gtfs_shapes": "shape_id",
        }
        for key in sorted(scope):
            field = fields.get(key[0])
            if field is not None and not entities.get(key, {}).get(field):
                yield _issue(
                    "GTFS_EDITOR_REQUIRED_ID",
                    ValidationCategory.FIELD,
                    key,
                    f"Falta el identificador obligatorio {field}.",
                    field_name=field,
                )

    def _references(
        self, entities: dict[EntityKey, dict[str, object]], scope: set[EntityKey]
    ) -> Iterable[ValidationIssue]:
        reference_fields = {
            "gtfs_routes": {"agency_id": ("gtfs_agency", "agency_id")},
            "gtfs_trips": {
                "route_id": ("gtfs_routes", "route_id"),
                "service_id": ("gtfs_calendar", "service_id"),
                "shape_id": ("gtfs_shapes", "shape_id"),
            },
            "gtfs_stop_times": {
                "trip_id": ("gtfs_trips", "trip_id"),
                "stop_id": ("gtfs_stops", "stop_id"),
            },
            "gtfs_frequencies": {"trip_id": ("gtfs_trips", "trip_id")},
            "gtfs_attributions": {
                "agency_id": ("gtfs_agency", "agency_id"),
                "route_id": ("gtfs_routes", "route_id"),
                "trip_id": ("gtfs_trips", "trip_id"),
            },
            "gtfs_transfers": {
                "from_stop_id": ("gtfs_stops", "stop_id"),
                "to_stop_id": ("gtfs_stops", "stop_id"),
                "from_route_id": ("gtfs_routes", "route_id"),
                "to_route_id": ("gtfs_routes", "route_id"),
                "from_trip_id": ("gtfs_trips", "trip_id"),
                "to_trip_id": ("gtfs_trips", "trip_id"),
            },
        }
        for key in sorted(scope):
            payload = entities.get(key)
            if payload is None:
                continue
            for field, (table, target_field) in reference_fields.get(key[0], {}).items():
                value = payload.get(field)
                if value is None:
                    continue
                target_tables = {table}
                if table == "gtfs_calendar":
                    target_tables.add("gtfs_calendar_dates")
                exists = any(
                    row_key[0] in target_tables and row.get(target_field) == value
                    for row_key, row in entities.items()
                )
                if not exists:
                    yield _issue(
                        "GTFS_EDITOR_ORPHAN_REFERENCE",
                        ValidationCategory.REFERENCE,
                        key,
                        f"La referencia {field}={value!r} no existe.",
                        field_name=field,
                    )

    def _geometry(
        self, entities: dict[EntityKey, dict[str, object]], scope: set[EntityKey]
    ) -> Iterable[ValidationIssue]:
        coordinate_fields = {
            "gtfs_stops": ("stop_lat", "stop_lon", -90.0, 90.0, -180.0, 180.0),
            "gtfs_shapes": ("shape_pt_lat", "shape_pt_lon", -90.0, 90.0, -180.0, 180.0),
        }
        for key in sorted(scope):
            payload = entities.get(key)
            fields = coordinate_fields.get(key[0])
            if payload is None or fields is None:
                continue
            latitude_field, longitude_field, min_lat, max_lat, min_lon, max_lon = fields
            latitude, longitude = payload.get(latitude_field), payload.get(longitude_field)
            if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
                yield _issue(
                    "GTFS_EDITOR_COORDINATE_MISSING",
                    ValidationCategory.GEOMETRY,
                    key,
                    "La entidad necesita latitud y longitud numéricas.",
                )
                continue
            if not (
                math.isfinite(float(latitude))
                and math.isfinite(float(longitude))
                and min_lat <= float(latitude) <= max_lat
                and min_lon <= float(longitude) <= max_lon
            ):
                yield _issue(
                    "GTFS_EDITOR_COORDINATE_RANGE",
                    ValidationCategory.GEOMETRY,
                    key,
                    "La coordenada queda fuera de WGS84.",
                )

    def _times_and_sequences(
        self, entities: dict[EntityKey, dict[str, object]], scope: set[EntityKey]
    ) -> Iterable[ValidationIssue]:
        sequences: dict[tuple[object, object], list[EntityKey]] = defaultdict(list)
        for key, payload in entities.items():
            if key[0] != "gtfs_stop_times":
                continue
            trip_id, sequence = payload.get("trip_id"), payload.get("stop_sequence")
            if trip_id is not None and sequence is not None:
                sequences[(trip_id, sequence)].append(key)
            for field in (
                "arrival_time_lexeme",
                "departure_time_lexeme",
                "start_pickup_drop_off_window_lexeme",
                "end_pickup_drop_off_window_lexeme",
            ):
                value = payload.get(field)
                if value is not None and not _valid_time(value):
                    if key in scope:
                        yield _issue(
                            "GTFS_EDITOR_INVALID_TIME",
                            ValidationCategory.TIMETABLE,
                            key,
                            f"El lexema horario {field} no es válido.",
                            field_name=field,
                        )
        for keys in sequences.values():
            if len(keys) > 1:
                for key in keys:
                    if key in scope:
                        yield _issue(
                            "GTFS_EDITOR_DUPLICATE_SEQUENCE",
                            ValidationCategory.TIMETABLE,
                            key,
                            "Hay dos paradas con la misma secuencia en un viaje.",
                            field_name="stop_sequence",
                        )

    def _calendar(
        self, entities: dict[EntityKey, dict[str, object]], scope: set[EntityKey]
    ) -> Iterable[ValidationIssue]:
        for key in sorted(scope):
            payload = entities.get(key)
            if payload is None:
                continue
            if key[0] == "gtfs_calendar":
                start, end = payload.get("start_date"), payload.get("end_date")
                if isinstance(start, date) and isinstance(end, date) and start > end:
                    yield _issue(
                        "GTFS_EDITOR_CALENDAR_RANGE",
                        ValidationCategory.CALENDAR,
                        key,
                        "El inicio del servicio es posterior al final.",
                    )
            if key[0] == "gtfs_calendar_dates" and payload.get("exception_type") not in {1, 2}:
                yield _issue(
                    "GTFS_EDITOR_EXCEPTION_TYPE",
                    ValidationCategory.CALENDAR,
                    key,
                    "exception_type debe ser 1 o 2.",
                    field_name="exception_type",
                )


def _valid_time(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(":")
    if len(parts) != 3 or any(not part.isdecimal() for part in parts):
        return False
    return int(parts[1]) < 60 and int(parts[2]) < 60


def _issue(
    code: str,
    category: ValidationCategory,
    key: EntityKey,
    message: str,
    *,
    field_name: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code,
        ValidationSeverity.ERROR,
        category,
        LocalizedMessage("validation.editor_issue", {"message": message}),
        file_name=None,
        row_number=None,
        field_name=field_name,
        entity=ValidationEntity(key[0], key[1]),
        validator="gtfs-explorer-editor",
    )

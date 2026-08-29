"""Bundle JSON GTFS determinista y publicado de forma atómica."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.infrastructure.duckdb.database import DatabaseConnection
from gtfs_explorer.infrastructure.exporting.atomic_output import (
    AtomicOutputWriter,
    CancellationCheck,
)
from gtfs_explorer.product import IDENTITY

# Compatibilidad para consumidores que ya importaban esta variable del módulo.
__version__ = IDENTITY.version

_BATCH_SIZE = 1_000
_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class JsonExportSelection:
    """Selección explícita soportada por el contrato público 1.0.0."""

    route_ids: frozenset[str]
    trip_ids: frozenset[str] = frozenset()
    service_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.route_ids:
            raise ValueError("La exportación JSON requiere al menos una ruta seleccionada.")
        if any(not value for value in (*self.route_ids, *self.trip_ids, *self.service_ids)):
            raise ValueError("Los identificadores de selección no pueden estar vacíos.")


class JsonBundleExporter:
    """Emite el contrato ``gtfs-explorer.bundle`` sin materializar el feed completo."""

    def __init__(
        self,
        writer: AtomicOutputWriter | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._writer = writer or AtomicOutputWriter()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def write(
        self,
        connection: DatabaseConnection,
        destination: Path,
        *,
        feed_id: str,
        selection: JsonExportSelection,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        """Serializa en lotes y publica el bundle junto con su manifiesto lateral."""
        source = self._source(connection, feed_id)
        timestamp = self._timestamp()
        return self._writer.write(
            destination,
            self._chunks(connection, source, selection, timestamp, is_cancelled),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
        )

    def _source(self, connection: DatabaseConnection, feed_id: str) -> dict[str, str]:
        row = connection.execute(
            "SELECT source_sha256, spec_revision FROM feeds WHERE feed_id = ?", [feed_id]
        ).fetchone()
        if row is None:
            raise ValueError("No existe el feed solicitado para la exportación JSON.")
        return {"sha256": str(row[0]), "spec_revision": str(row[1])}

    def _chunks(
        self,
        connection: DatabaseConnection,
        source: dict[str, str],
        selection: JsonExportSelection,
        timestamp: str,
        is_cancelled: CancellationCheck,
    ) -> Iterator[bytes]:
        warnings: list[dict[str, object]] = []
        trip_where, parameters = _trip_predicate(selection)
        scalar_fields: tuple[tuple[str, object], ...] = (
            ("schema_version", _SCHEMA_VERSION),
            ("generator", {"name": IDENTITY.name, "version": IDENTITY.version}),
            ("source", source),
            ("selection", _selection_payload(selection)),
        )
        arrays: tuple[tuple[str, Iterable[dict[str, object]]], ...] = (
            ("agencies", self._agencies(connection, trip_where, parameters, warnings)),
            ("routes", self._routes(connection, trip_where, parameters, warnings)),
            ("services", self._services(connection, trip_where, parameters, warnings)),
            ("stops", self._stops(connection, trip_where, parameters, warnings)),
            ("shapes", self._shapes(connection, trip_where, parameters, warnings)),
            ("trips", self._trips(connection, trip_where, parameters, warnings)),
            ("transfers", self._transfers(connection, trip_where, parameters, warnings)),
        )
        yield b"{"
        first = True
        for name, value in scalar_fields:
            yield from _field(name, value, first)
            first = False
        for name, records in arrays:
            yield from _array_field(name, records, is_cancelled, first)
            first = False
        metadata = self._metadata(connection, trip_where, parameters, timestamp)
        yield from _field("metadata", metadata, first)
        yield from _array_field("warnings", warnings, is_cancelled, False)
        yield b"}\n"

    @staticmethod
    def _agencies(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "SELECT DISTINCT a.agency_id, a.agency_name, a.agency_timezone, a.agency_url, "
            "a.agency_lang, a.agency_phone, a.agency_email, a.agency_fare_url "
            "FROM gtfs_agency a JOIN gtfs_routes r ON r.agency_id = a.agency_id "
            "JOIN gtfs_trips t ON t.route_id = r.route_id "
            f"WHERE {trip_where} ORDER BY a.agency_id, a.source_row"
        )
        for row in _rows(connection, query, parameters):
            if row["agency_name"] is None or row["agency_timezone"] is None:
                _omitted(warnings, "agency", row["agency_id"])
                continue
            yield {
                "agency_id": row["agency_id"],
                "name": row["agency_name"],
                "timezone": row["agency_timezone"],
                "url": row["agency_url"],
                "lang": row["agency_lang"],
                "phone": row["agency_phone"],
                "email": row["agency_email"],
                "fare_url": row["agency_fare_url"],
            }

    @staticmethod
    def _routes(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "SELECT DISTINCT r.route_id, r.agency_id, r.route_short_name, r.route_long_name, "
            "r.route_type, r.route_desc, r.route_url, r.route_color, r.route_text_color "
            "FROM gtfs_routes r JOIN gtfs_trips t ON t.route_id = r.route_id "
            f"WHERE {trip_where} ORDER BY r.route_id, r.source_row"
        )
        for row in _rows(connection, query, parameters):
            if row["route_id"] is None or row["route_type"] is None:
                _omitted(warnings, "route", row["route_id"])
                continue
            yield {
                "route_id": row["route_id"],
                "agency_id": row["agency_id"],
                "short_name": row["route_short_name"],
                "long_name": row["route_long_name"],
                "route_type": row["route_type"],
                "description": row["route_desc"],
                "url": row["route_url"],
                "color": row["route_color"],
                "text_color": row["route_text_color"],
            }

    @staticmethod
    def _services(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "SELECT DISTINCT t.service_id FROM gtfs_trips t WHERE "
            + trip_where
            + " ORDER BY t.service_id"
        )
        for service in _rows(connection, query, parameters):
            service_id = service["service_id"]
            if service_id is None:
                _omitted(warnings, "service", None)
                continue
            calendar = connection.execute(
                "SELECT monday, tuesday, wednesday, thursday, friday, saturday, sunday, "
                "start_date, end_date FROM gtfs_calendar WHERE service_id = ? "
                "ORDER BY source_row LIMIT 1",
                [service_id],
            ).fetchone()
            dates = list(
                _rows(
                    connection,
                    "SELECT date, exception_type FROM gtfs_calendar_dates "
                    "WHERE service_id = ? ORDER BY date, exception_type, source_row",
                    [str(service_id)],
                )
            )
            calendar_payload: dict[str, object] | None = None
            if calendar is not None:
                if calendar[7] is None or calendar[8] is None:
                    _omitted(warnings, "calendar", str(service_id))
                else:
                    calendar_payload = {
                        day: bool(calendar[index])
                        for index, day in enumerate(
                            (
                                "monday",
                                "tuesday",
                                "wednesday",
                                "thursday",
                                "friday",
                                "saturday",
                                "sunday",
                            )
                        )
                    }
                    calendar_payload.update(
                        {"start_date": calendar[7].isoformat(), "end_date": calendar[8].isoformat()}
                    )
            yield {
                "service_id": service_id,
                "calendar": calendar_payload,
                "calendar_dates": [
                    {"date": row["date"].isoformat(), "exception_type": row["exception_type"]}
                    for row in dates
                    if row["date"] is not None and row["exception_type"] is not None
                ],
            }

    @staticmethod
    def _stops(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "SELECT DISTINCT s.stop_id, s.stop_name, s.stop_lat, s.stop_lon, s.location_type, "
            "s.parent_station, s.stop_code, s.stop_desc, s.stop_timezone, s.wheelchair_boarding "
            "FROM gtfs_stops s JOIN gtfs_stop_times st ON st.stop_id = s.stop_id "
            "JOIN gtfs_trips t ON t.trip_id = st.trip_id "
            f"WHERE {trip_where} ORDER BY s.stop_id, s.source_row"
        )
        for row in _rows(connection, query, parameters):
            if row["stop_id"] is None:
                _omitted(warnings, "stop", None)
                continue
            yield {
                "stop_id": row["stop_id"],
                "name": row["stop_name"],
                "latitude": row["stop_lat"],
                "longitude": row["stop_lon"],
                "location_type": row["location_type"],
                "parent_station": row["parent_station"],
                "code": row["stop_code"],
                "description": row["stop_desc"],
                "timezone": row["stop_timezone"],
                "wheelchair_boarding": row["wheelchair_boarding"],
            }

    @staticmethod
    def _shapes(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "SELECT sh.shape_id, sh.shape_pt_sequence, sh.shape_pt_lat, sh.shape_pt_lon, "
            "sh.shape_dist_traveled "
            "FROM gtfs_shapes sh JOIN (SELECT DISTINCT t.shape_id FROM gtfs_trips t WHERE "
            + trip_where
            + ") selected "
            "ON selected.shape_id = sh.shape_id WHERE sh.shape_id IS NOT NULL "
            "ORDER BY sh.shape_id, sh.shape_pt_sequence, sh.source_row"
        )
        current_id: str | None = None
        points: list[dict[str, object]] = []
        for row in _rows(connection, query, parameters):
            shape_id = str(row["shape_id"])
            if current_id is not None and shape_id != current_id:
                yield {"shape_id": current_id, "points": points}
                points = []
            current_id = shape_id
            if any(
                row[name] is None for name in ("shape_pt_sequence", "shape_pt_lat", "shape_pt_lon")
            ):
                _omitted(warnings, "shape_point", shape_id)
                continue
            points.append(
                {
                    "sequence": row["shape_pt_sequence"],
                    "latitude": row["shape_pt_lat"],
                    "longitude": row["shape_pt_lon"],
                    "distance_traveled": row["shape_dist_traveled"],
                }
            )
        if current_id is not None:
            yield {"shape_id": current_id, "points": points}

    @staticmethod
    def _trips(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "SELECT trip_id, route_id, service_id, direction_id, shape_id, trip_headsign, "
            "trip_short_name, "
            "wheelchair_accessible, bikes_allowed FROM gtfs_trips t WHERE "
            + trip_where
            + " ORDER BY t.trip_id, t.source_row"
        )
        for row in _rows(connection, query, parameters):
            if any(row[name] is None for name in ("trip_id", "route_id", "service_id")):
                _omitted(warnings, "trip", row["trip_id"])
                continue
            times = []
            for time in _rows(
                connection,
                "SELECT stop_id, stop_sequence, arrival_time_lexeme, "
                "arrival_service_seconds, departure_time_lexeme, departure_service_seconds, "
                "stop_headsign, "
                "pickup_type, drop_off_type, timepoint FROM gtfs_stop_times WHERE trip_id = ? "
                "ORDER BY stop_sequence, source_row",
                [str(row["trip_id"])],
            ):
                if time["stop_id"] is None or time["stop_sequence"] is None:
                    _omitted(warnings, "stop_time", str(row["trip_id"]))
                    continue
                times.append(
                    {
                        "stop_id": time["stop_id"],
                        "stop_sequence": time["stop_sequence"],
                        "arrival": time["arrival_time_lexeme"],
                        "arrival_service_seconds": time["arrival_service_seconds"],
                        "departure": time["departure_time_lexeme"],
                        "departure_service_seconds": time["departure_service_seconds"],
                        "headsign": time["stop_headsign"],
                        "pickup_type": time["pickup_type"],
                        "drop_off_type": time["drop_off_type"],
                        "timepoint": time["timepoint"],
                    }
                )
            yield {
                "trip_id": row["trip_id"],
                "route_id": row["route_id"],
                "service_id": row["service_id"],
                "direction_id": row["direction_id"],
                "shape_id": row["shape_id"],
                "headsign": row["trip_headsign"],
                "short_name": row["trip_short_name"],
                "wheelchair_accessible": row["wheelchair_accessible"],
                "bikes_allowed": row["bikes_allowed"],
                "stop_times": times,
            }

    @staticmethod
    def _transfers(
        connection: DatabaseConnection,
        trip_where: str,
        parameters: list[str],
        warnings: list[dict[str, object]],
    ) -> Iterator[dict[str, object]]:
        query = (
            "WITH selected_stops AS (SELECT DISTINCT st.stop_id FROM gtfs_stop_times st "
            "JOIN gtfs_trips t "
            "ON t.trip_id = st.trip_id WHERE " + trip_where + ") "
            "SELECT from_stop_id, to_stop_id, transfer_type, min_transfer_time FROM gtfs_transfers "
            "WHERE from_stop_id IN (SELECT stop_id FROM selected_stops) "
            "AND to_stop_id IN (SELECT stop_id FROM selected_stops) "
            "ORDER BY from_stop_id, to_stop_id, transfer_type, min_transfer_time, source_row"
        )
        for row in _rows(connection, query, parameters):
            if row["from_stop_id"] is None or row["to_stop_id"] is None:
                _omitted(warnings, "transfer", None)
                continue
            yield {
                "from_stop_id": row["from_stop_id"],
                "to_stop_id": row["to_stop_id"],
                "transfer_type": row["transfer_type"],
                "min_transfer_time": row["min_transfer_time"],
            }

    @staticmethod
    def _metadata(
        connection: DatabaseConnection, trip_where: str, parameters: list[str], timestamp: str
    ) -> dict[str, object]:
        frequencies = list(
            _rows(
                connection,
                "SELECT trip_id, start_time_lexeme, start_time_service_seconds, "
                "end_time_lexeme, end_time_service_seconds, headway_secs, exact_times "
                "FROM gtfs_frequencies "
                "WHERE trip_id IN (SELECT t.trip_id FROM gtfs_trips t WHERE " + trip_where + ") "
                "ORDER BY trip_id, start_time_service_seconds, source_row",
                parameters,
            )
        )
        feed_info = list(
            _rows(
                connection,
                "SELECT feed_publisher_name, feed_publisher_url, feed_lang, default_lang, "
                "feed_start_date_lexeme, feed_end_date_lexeme, feed_version, "
                "feed_contact_email, feed_contact_url "
                "FROM gtfs_feed_info ORDER BY source_row",
                [],
            )
        )
        attributions = list(
            _rows(
                connection,
                "WITH selected_trips AS (SELECT t.trip_id, t.route_id FROM gtfs_trips t WHERE "
                + trip_where
                + "), selected_agencies AS (SELECT DISTINCT r.agency_id FROM gtfs_routes r "
                "JOIN selected_trips t ON t.route_id = r.route_id) "
                "SELECT attribution_id, agency_id, route_id, trip_id, organization_name, "
                "is_producer, is_operator, is_authority, attribution_url, attribution_email, "
                "attribution_phone "
                "FROM gtfs_attributions WHERE "
                "(agency_id IS NULL AND route_id IS NULL AND trip_id IS NULL) "
                "OR agency_id IN (SELECT agency_id FROM selected_agencies) "
                "OR route_id IN (SELECT route_id FROM selected_trips) "
                "OR trip_id IN (SELECT trip_id FROM selected_trips) "
                "ORDER BY attribution_id, source_row",
                parameters,
            )
        )
        return {
            "exported_at": timestamp,
            "frequencies": [_plain(row) for row in frequencies],
            "feed_info": [_plain(row) for row in feed_info],
            "attributions": [_plain(row) for row in attributions],
        }

    def _timestamp(self) -> str:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("El reloj de exportación debe devolver una fecha con zona horaria.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _trip_predicate(selection: JsonExportSelection) -> tuple[str, list[str]]:
    conditions = [_in("t.route_id", selection.route_ids)]
    parameters = sorted(selection.route_ids)
    if selection.trip_ids:
        conditions.append(_in("t.trip_id", selection.trip_ids))
        parameters.extend(sorted(selection.trip_ids))
    if selection.service_ids:
        conditions.append(_in("t.service_id", selection.service_ids))
        parameters.extend(sorted(selection.service_ids))
    return " AND ".join(conditions), parameters


def _in(column: str, values: frozenset[str]) -> str:
    return f"{column} IN ({', '.join('?' for _ in values)})"


def _selection_payload(selection: JsonExportSelection) -> dict[str, list[str]]:
    return {
        "route_ids": sorted(selection.route_ids),
        "trip_ids": sorted(selection.trip_ids),
        "service_ids": sorted(selection.service_ids),
    }


def _rows(
    connection: DatabaseConnection, query: str, parameters: list[str]
) -> Iterator[dict[str, Any]]:
    cursor = connection.execute(query, parameters)
    if cursor.description is None:
        raise ValueError("La consulta de exportación no devolvió columnas.")
    columns = [str(item[0]) for item in cursor.description]
    while batch := cursor.fetchmany(_BATCH_SIZE):
        yield from (dict(zip(columns, row, strict=True)) for row in batch)


def _omitted(warnings: list[dict[str, object]], entity_type: str, entity_id: object) -> None:
    warning: dict[str, object] = {
        "code": "OMITTED_INVALID_RECORD",
        "message": "Se omitió un registro inválido del bundle.",
        "entity_type": entity_type,
        "entity_id": None if entity_id is None else str(entity_id),
    }
    if warning not in warnings:
        warnings.append(warning)


def _plain(value: object) -> object:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _field(name: str, value: object, first: bool) -> Iterator[bytes]:
    prefix = "" if first else ","
    yield (prefix + json.dumps(name) + ":" + _dump(value)).encode("utf-8")


def _array_field(
    name: str, records: Iterable[dict[str, object]], is_cancelled: CancellationCheck, first: bool
) -> Iterator[bytes]:
    yield (("" if first else ",") + json.dumps(name) + ":[").encode("utf-8")
    item_first = True
    for record in records:
        if is_cancelled():
            from gtfs_explorer.domain.exporting import ExportCancelled

            raise ExportCancelled("La exportación se ha cancelado.")
        yield (("" if item_first else ",") + _dump(record)).encode("utf-8")
        item_first = False
    yield b"]"


def _dump(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_plain
    )

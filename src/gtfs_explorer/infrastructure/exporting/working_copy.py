"""Exportadores de las salidas no-GTFS sobre una WorkingRevision confirmada."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from gtfs_explorer.domain.changesets import WorkingCopy
from gtfs_explorer.domain.exporting import ExportManifest
from gtfs_explorer.domain.spec import ScheduleSpec
from gtfs_explorer.domain.subset import SubsetSelection
from gtfs_explorer.infrastructure.exporting.atomic_output import (
    AtomicOutputWriter,
    CancellationCheck,
)
from gtfs_explorer.infrastructure.exporting.revision import WorkingCopyGtfsBuilder


class WorkingCopyExporters:
    """Publica JSON, CSV y GeoJSON desde la revisión, nunca desde el original."""

    def __init__(
        self,
        specification: ScheduleSpec,
        *,
        writer: AtomicOutputWriter | None = None,
    ) -> None:
        self._specification = specification
        self._writer = writer or AtomicOutputWriter()

    def write_json(
        self,
        destination: Path,
        working_copy: WorkingCopy,
        *,
        revision_id: str,
        selection: SubsetSelection | None = None,
        source: dict[str, str] | None = None,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        preview = WorkingCopyGtfsBuilder(working_copy, self._specification).preview(
            revision_id=revision_id, selection=selection
        )
        entities = working_copy.entities
        included = set(preview.included_entities)
        tables: dict[str, list[dict[str, object]]] = defaultdict(list)
        for key in sorted(included):
            table = key[0]
            filename = _table_filename(table)
            if filename is None:
                continue
            payload = _json_safe(entities[key])
            payload["entity_id"] = key[1]
            tables[filename].append(payload)
        payload = {
            "schema_version": "1.0.0",
            "generator": {"name": "GTFS Explorer Desktop", "version": "0.2.0"},
            "source": source or {},
            "revision": {
                "revision_id": revision_id,
                "scope": "selected_routes" if selection is not None else "complete_modified",
            },
            "selection": {
                "route_ids": sorted(selection.route_ids) if selection is not None else None,
                "trip_ids": sorted(selection.trip_ids or ()) if selection is not None else None,
                "service_ids": sorted(selection.service_ids or ())
                if selection is not None
                else None,
            },
            "tables": dict(sorted(tables.items())),
            "dependencies": {
                "included_entities": [list(key) for key in preview.included_entities],
                "omitted_entities": [list(key) for key in preview.omitted_entities],
            },
        }
        content = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        return self._writer.write(
            destination,
            (content,),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={
                "format": "json_bundle",
                "revision_id": revision_id,
                "export_scope": "selected_routes" if selection is not None else "complete_modified",
            },
        )

    def write_csv(
        self,
        destination: Path,
        working_copy: WorkingCopy,
        *,
        revision_id: str,
        selection: SubsetSelection | None = None,
        spreadsheet_safe: bool = False,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        preview = WorkingCopyGtfsBuilder(working_copy, self._specification).preview(
            revision_id=revision_id, selection=selection
        )
        entities = working_copy.entities
        routes = [
            payload
            for key, payload in sorted(entities.items())
            if key in set(preview.included_entities) and key[0] == "gtfs_routes"
        ]
        headers = ("route_id", "route_short_name", "route_long_name", "route_type")
        lines = [",".join(headers) + "\r\n"]
        for route in routes:
            if is_cancelled():
                from gtfs_explorer.domain.exporting import ExportCancelled

                raise ExportCancelled("La exportación CSV se ha cancelado.")
            values = ["" if route.get(field) is None else str(route[field]) for field in headers]
            if spreadsheet_safe:
                values = [
                    "'" + value if value[:1] in {"=", "+", "-", "@"} else value for value in values
                ]
            lines.append(_csv_line(values))
        return self._writer.write(
            destination,
            ("".join(lines).encode("utf-8"),),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={
                "format": "csv_route_view",
                "revision_id": revision_id,
                "mode": "spreadsheet-safe" if spreadsheet_safe else "faithful",
            },
        )

    def write_geojson(
        self,
        destination: Path,
        working_copy: WorkingCopy,
        *,
        revision_id: str,
        selection: SubsetSelection | None = None,
        include_bbox: bool = False,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        preview = WorkingCopyGtfsBuilder(working_copy, self._specification).preview(
            revision_id=revision_id, selection=selection
        )
        entities = working_copy.entities
        included = set(preview.included_entities)
        features: list[dict[str, object]] = []
        stop_ids = {
            str(entities[key].get("stop_id"))
            for key in included
            if key[0] == "gtfs_stop_times" and entities[key].get("stop_id") is not None
        }
        for key in sorted(included):
            if key[0] != "gtfs_stops" or str(entities[key].get("stop_id")) not in stop_ids:
                continue
            payload = entities[key]
            coordinate = _coordinate(payload.get("stop_lon"), payload.get("stop_lat"))
            if coordinate is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_kind": "stop",
                        "stop_id": payload.get("stop_id"),
                        "stop_name": payload.get("stop_name"),
                        "geometry_source": "working_revision",
                        "revision_id": revision_id,
                    },
                    "geometry": {"type": "Point", "coordinates": coordinate},
                }
            )
        shape_ids = {
            entities[key].get("shape_id")
            for key in included
            if key[0] == "gtfs_trips" and entities[key].get("shape_id") is not None
        }
        points: dict[object, list[dict[str, object]]] = defaultdict(list)
        for key in included:
            if key[0] == "gtfs_shapes" and entities[key].get("shape_id") in shape_ids:
                points[entities[key].get("shape_id")].append(entities[key])
        for shape_id in sorted(shape_ids, key=str):
            coordinates = []
            for point in sorted(
                points[shape_id], key=lambda item: _number(item.get("shape_pt_sequence"))
            ):
                coordinate = _coordinate(point.get("shape_pt_lon"), point.get("shape_pt_lat"))
                if coordinate is not None:
                    coordinates.append(coordinate)
            if len(coordinates) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_kind": "shape",
                        "shape_id": shape_id,
                        "geometry_source": "working_revision",
                        "revision_id": revision_id,
                    },
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                }
            )
        geojson_payload: dict[str, object] = {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "revision_id": revision_id,
                "scope": "selected_routes" if selection is not None else "complete_modified",
            },
        }
        if include_bbox and features:
            coordinates = [
                coordinate for feature in features for coordinate in _feature_points(feature)
            ]
            if coordinates:
                geojson_payload["bbox"] = [
                    min(point[0] for point in coordinates),
                    min(point[1] for point in coordinates),
                    max(point[0] for point in coordinates),
                    max(point[1] for point in coordinates),
                ]
        content = (json.dumps(geojson_payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        return self._writer.write(
            destination,
            (content,),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={
                "format": "geojson_feature_collection",
                "revision_id": revision_id,
                "export_scope": "selected_routes" if selection is not None else "complete_modified",
            },
        )


def _table_filename(table: str) -> str | None:
    return {
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
    }.get(table)


def _json_safe(value: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, (date, datetime)):
            result[key] = item.isoformat()
        else:
            result[key] = item
    return result


def _coordinate(longitude: object, latitude: object) -> list[float] | None:
    if not isinstance(longitude, (int, float)) or isinstance(longitude, bool):
        return None
    if not isinstance(latitude, (int, float)) or isinstance(latitude, bool):
        return None
    if not math.isfinite(float(longitude)) or not math.isfinite(float(latitude)):
        return None
    if not -180 <= float(longitude) <= 180 or not -90 <= float(latitude) <= 90:
        return None
    return [float(longitude), float(latitude)]


def _feature_points(feature: dict[str, object]) -> list[list[float]]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point" and isinstance(coordinates, list):
        return [coordinates]
    if isinstance(coordinates, list):
        return [point for point in coordinates if isinstance(point, list) and len(point) >= 2]
    return []


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else float("inf")


def _csv_line(values: list[str]) -> str:
    import csv
    import io

    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow(values)
    return output.getvalue()

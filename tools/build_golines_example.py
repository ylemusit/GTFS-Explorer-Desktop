"""Genera un kit local GTFS + PMTiles a partir de los activos de GoLines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "examples" / "golines-asturias" / "style.json"
DEFAULT_OUTPUT = ROOT / "examples" / "golines-asturias" / "generated"
DEFAULT_ROUTES = (
    "centrobus-og1",
    "centrobus-go1",
    "centrobus-oa1",
    "centrobus-ao1",
    "centrobus-ga1",
    "centrobus-ag1",
)
ROUTE_COLORS = ("2563EB", "DC2626", "16A34A", "9333EA", "EA580C", "0891B2")
FIXED_ZIP_TIME = (2026, 8, 15, 0, 0, 0)


class ExampleBuildError(RuntimeError):
    """El catálogo no permite construir un ejemplo coherente."""


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _csv_bytes(headers: tuple[str, ...], rows: Iterable[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _selected_trips(trips: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    usable = sorted(
        (trip for trip in trips if len(trip.get("stops", [])) >= 2),
        key=lambda trip: str(trip["stops"][0].get("departure", "")),
    )
    if len(usable) <= limit:
        return usable
    if limit == 1:
        return [usable[0]]
    indexes = [round(index * (len(usable) - 1) / (limit - 1)) for index in range(limit)]
    return [usable[index] for index in dict.fromkeys(indexes)]


def _distance_meters(first: list[float], second: list[float]) -> float:
    latitude_1, longitude_1 = (math.radians(float(value)) for value in first)
    latitude_2, longitude_2 = (math.radians(float(value)) for value in second)
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = longitude_2 - longitude_1
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(longitude_delta / 2) ** 2
    )
    return 6_371_008.8 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def build_gtfs(
    catalog_path: Path,
    destination: Path,
    *,
    route_ids: tuple[str, ...] = DEFAULT_ROUTES,
    trips_per_route: int = 2,
) -> dict[str, object]:
    """Convierte una selección del catálogo GoLines en un GTFS de evaluación."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("schemaVersion") != 1:
        raise ExampleBuildError("El catálogo GoLines no usa el esquema 1 esperado.")
    routes_by_id = {route["id"]: route for route in catalog.get("routes", [])}
    missing_routes = [route_id for route_id in route_ids if route_id not in routes_by_id]
    if missing_routes:
        raise ExampleBuildError("Faltan rutas en GoLines: " + ", ".join(missing_routes))
    shapes = catalog.get("shapes")
    if not isinstance(shapes, dict):
        raise ExampleBuildError("El catálogo GoLines no contiene shapes.")
    source_trips = catalog.get("trips")
    if not isinstance(source_trips, list):
        raise ExampleBuildError("El catálogo GoLines no contiene viajes.")

    selected: list[dict[str, Any]] = []
    for route_id in route_ids:
        candidates = [trip for trip in source_trips if trip.get("routeId") == route_id]
        route_trips = _selected_trips(candidates, trips_per_route)
        if not route_trips:
            raise ExampleBuildError(f"La ruta {route_id} no contiene viajes utilizables.")
        selected.extend(route_trips)

    stops: dict[str, dict[str, Any]] = {}
    for trip in selected:
        for stop in trip["stops"]:
            stop_id = str(stop["stopId"])
            previous = stops.setdefault(stop_id, stop)
            if (
                abs(float(previous["latitude"]) - float(stop["latitude"])) > 1e-7
                or abs(float(previous["longitude"]) - float(stop["longitude"])) > 1e-7
            ):
                raise ExampleBuildError(f"La parada {stop_id} tiene coordenadas inconsistentes.")

    agency_rows = [
        {
            "agency_id": "GOLINES_DEMO",
            "agency_name": "GoLines Asturias — demostración no oficial",
            "agency_url": "https://github.com/ylemusit/GoLines",
            "agency_timezone": "Europe/Madrid",
            "agency_lang": "es",
        }
    ]
    route_rows = []
    for index, route_id in enumerate(route_ids):
        route = routes_by_id[route_id]
        route_rows.append(
            {
                "route_id": route_id,
                "agency_id": "GOLINES_DEMO",
                "route_short_name": route["shortName"],
                "route_long_name": route["longName"],
                "route_desc": (
                    "Reconstrucción técnica local para evaluación; no es servicio oficial."
                ),
                "route_type": 3,
                "route_url": route.get("officialPage", ""),
                "route_color": ROUTE_COLORS[index % len(ROUTE_COLORS)],
                "route_text_color": "FFFFFF",
                "route_sort_order": index + 1,
            }
        )
    stop_rows = [
        {
            "stop_id": stop_id,
            "stop_code": stop_id.removeprefix("centrobus-stop-"),
            "stop_name": stop["name"],
            "stop_desc": "Parada de demostración procedente del catálogo local GoLines.",
            "stop_lat": stop["latitude"],
            "stop_lon": stop["longitude"],
            "location_type": 0,
        }
        for stop_id, stop in sorted(stops.items())
    ]
    trip_rows = [
        {
            "route_id": trip["routeId"],
            "service_id": "DEMO_DAILY_2026",
            "trip_id": trip["id"],
            "trip_headsign": trip.get("headsign", ""),
            "trip_short_name": trip.get("serviceId", "Horario fuente"),
            "direction_id": trip.get("directionId", "0"),
            "block_id": f"DEMO-{trip['routeId']}",
            "shape_id": trip["shapeId"],
        }
        for trip in selected
    ]
    stop_time_rows = []
    for trip in selected:
        for stop in trip["stops"]:
            stop_time_rows.append(
                {
                    "trip_id": trip["id"],
                    "arrival_time": stop.get("arrival", ""),
                    "departure_time": stop.get("departure", ""),
                    "stop_id": stop["stopId"],
                    "stop_sequence": stop["sequence"],
                    "timepoint": 1,
                }
            )
    shape_rows = []
    for shape_id in dict.fromkeys(str(trip["shapeId"]) for trip in selected):
        raw_points = shapes.get(shape_id)
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            raise ExampleBuildError(f"Falta una geometría utilizable para {shape_id}.")
        points: list[list[float]] = []
        for point in raw_points:
            normalized = [float(point[0]), float(point[1])]
            if not points or normalized != points[-1]:
                points.append(normalized)
        distance = 0.0
        for sequence, point in enumerate(points, start=1):
            if sequence > 1:
                distance += _distance_meters(points[sequence - 2], point)
            shape_rows.append(
                {
                    "shape_id": shape_id,
                    "shape_pt_lat": point[0],
                    "shape_pt_lon": point[1],
                    "shape_pt_sequence": sequence,
                    "shape_dist_traveled": f"{distance:.3f}",
                }
            )

    tables = {
        "agency.txt": _csv_bytes(
            ("agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"),
            agency_rows,
        ),
        "attributions.txt": _csv_bytes(
            (
                "attribution_id",
                "organization_name",
                "is_producer",
                "is_operator",
                "is_authority",
                "attribution_url",
            ),
            [
                {
                    "attribution_id": "CENTROBUS_SOURCE",
                    "organization_name": "CENTROBUS",
                    "is_producer": 1,
                    "is_operator": 0,
                    "is_authority": 0,
                    "attribution_url": catalog.get("sourceUrl", ""),
                },
                {
                    "attribution_id": "OSM_GEOMETRY",
                    "organization_name": "OpenStreetMap contributors",
                    "is_producer": 1,
                    "is_operator": 0,
                    "is_authority": 0,
                    "attribution_url": "https://www.openstreetmap.org/copyright",
                },
            ],
        ),
        "calendar.txt": _csv_bytes(
            (
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ),
            [
                {
                    "service_id": "DEMO_DAILY_2026",
                    "monday": 1,
                    "tuesday": 1,
                    "wednesday": 1,
                    "thursday": 1,
                    "friday": 1,
                    "saturday": 1,
                    "sunday": 1,
                    "start_date": "20260101",
                    "end_date": "20261231",
                }
            ],
        ),
        "calendar_dates.txt": _csv_bytes(
            ("service_id", "date", "exception_type"),
            [
                {
                    "service_id": "DEMO_DAILY_2026",
                    "date": "20261225",
                    "exception_type": 2,
                }
            ],
        ),
        "feed_info.txt": _csv_bytes(
            (
                "feed_publisher_name",
                "feed_publisher_url",
                "feed_lang",
                "default_lang",
                "feed_start_date",
                "feed_end_date",
                "feed_version",
                "feed_contact_url",
            ),
            [
                {
                    "feed_publisher_name": "GTFS Explorer Desktop / GoLines",
                    "feed_publisher_url": "https://github.com/ylemusit/GoLines",
                    "feed_lang": "es",
                    "default_lang": "es",
                    "feed_start_date": "20260101",
                    "feed_end_date": "20261231",
                    "feed_version": "demo-local-2026-08-15",
                    "feed_contact_url": "https://github.com/ylemusit/GoLines",
                }
            ],
        ),
        "routes.txt": _csv_bytes(
            (
                "route_id",
                "agency_id",
                "route_short_name",
                "route_long_name",
                "route_desc",
                "route_type",
                "route_url",
                "route_color",
                "route_text_color",
                "route_sort_order",
            ),
            route_rows,
        ),
        "shapes.txt": _csv_bytes(
            (
                "shape_id",
                "shape_pt_lat",
                "shape_pt_lon",
                "shape_pt_sequence",
                "shape_dist_traveled",
            ),
            shape_rows,
        ),
        "stop_times.txt": _csv_bytes(
            (
                "trip_id",
                "arrival_time",
                "departure_time",
                "stop_id",
                "stop_sequence",
                "timepoint",
            ),
            stop_time_rows,
        ),
        "stops.txt": _csv_bytes(
            (
                "stop_id",
                "stop_code",
                "stop_name",
                "stop_desc",
                "stop_lat",
                "stop_lon",
                "location_type",
            ),
            stop_rows,
        ),
        "trips.txt": _csv_bytes(
            (
                "route_id",
                "service_id",
                "trip_id",
                "trip_headsign",
                "trip_short_name",
                "direction_id",
                "block_id",
                "shape_id",
            ),
            trip_rows,
        ),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for filename, contents in sorted(tables.items()):
            info = zipfile.ZipInfo(filename, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, contents)
    return {
        "routes": len(route_rows),
        "trips": len(trip_rows),
        "stops": len(stop_rows),
        "stop_times": len(stop_time_rows),
        "shape_points": len(shape_rows),
        "route_ids": list(route_ids),
    }


def _build_map_package(source: Path, destination: Path, *, pmtiles_binary: Path) -> None:
    command = [
        sys.executable,
        str(ROOT / "tools" / "build_map_package.py"),
        "--source",
        str(source),
        "--source-reference",
        "Protomaps Basemap 2026-08-06; OpenStreetMap y Natural Earth; copia local GoLines",
        "--output",
        str(destination),
        "--bbox=-7.25,42.82,-4.45,43.78",
        "--min-zoom",
        "0",
        "--max-zoom",
        "15",
        "--style",
        str(STYLE),
        "--license",
        "ODbL-1.0",
        "--license-url",
        "https://opendatacommons.org/licenses/odbl/1-0/",
        "--attribution",
        "© OpenStreetMap contributors · Protomaps Basemap",
        "--pmtiles-bin",
        str(pmtiles_binary),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode:
        raise ExampleBuildError((result.stderr or result.stdout).strip())


def build_example(
    golines_root: Path,
    output: Path,
    *,
    pmtiles_binary: Path,
    route_ids: tuple[str, ...],
    trips_per_route: int,
) -> Path:
    golines_root = golines_root.resolve()
    catalog = golines_root / "app" / "src" / "main" / "assets" / "centrobus_repository.json"
    basemap = golines_root / "app" / "src" / "main" / "assets" / "asturias-offline.pmtiles"
    if not catalog.is_file() or not basemap.is_file() or not pmtiles_binary.is_file():
        raise ExampleBuildError("GoLines no contiene catálogo, PMTiles o CLI requeridos.")
    output = output.resolve()
    if output.exists():
        raise ExampleBuildError(f"El destino ya existe: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="golines-example-", dir=output.parent) as temporary:
        root = Path(temporary) / "example"
        root.mkdir()
        gtfs = root / "golines-asturias-demo.gtfs.zip"
        counts = build_gtfs(
            catalog,
            gtfs,
            route_ids=route_ids,
            trips_per_route=trips_per_route,
        )
        _build_map_package(basemap, root / "map-package", pmtiles_binary=pmtiles_binary)
        files = [path for path in sorted(root.rglob("*")) if path.is_file()]
        checksums = {path.relative_to(root).as_posix(): _sha256(path) for path in files}
        manifest = {
            "version": 1,
            "name": "GoLines Asturias — ejemplo local no oficial",
            "generated_at": "2026-08-15",
            "purpose": "local_evaluation_only",
            "redistribution": "permission_required_for_centrobus_derived_schedule",
            "source_catalog": {
                "schema_version": 1,
                "generated_at": json.loads(catalog.read_text(encoding="utf-8")).get("generatedAt"),
                "sha256": _sha256(catalog),
            },
            "gtfs": counts,
            "map": {
                "bbox": [-7.25, 42.82, -4.45, 43.78],
                "license": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors · Protomaps Basemap",
            },
            "sha256": checksums,
        }
        (root / "example-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        checksums["example-manifest.json"] = _sha256(root / "example-manifest.json")
        (root / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
            encoding="ascii",
        )
        os.replace(root, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golines-root", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pmtiles-bin", required=True, type=Path)
    parser.add_argument("--routes", default=",".join(DEFAULT_ROUTES))
    parser.add_argument("--trips-per-route", type=int, default=2)
    arguments = parser.parse_args()
    if not 1 <= arguments.trips_per_route <= 10:
        parser.error("--trips-per-route debe estar entre 1 y 10.")
    route_ids = tuple(item.strip() for item in arguments.routes.split(",") if item.strip())
    if not route_ids:
        parser.error("--routes debe contener al menos una ruta.")
    try:
        output = build_example(
            arguments.golines_root,
            arguments.output,
            pmtiles_binary=arguments.pmtiles_bin,
            route_ids=route_ids,
            trips_per_route=arguments.trips_per_route,
        )
    except ExampleBuildError as error:
        raise SystemExit(f"Error: {error}") from error
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

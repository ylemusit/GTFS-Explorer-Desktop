"""Benchmark reproducible de T095 para un feed GTFS sintético y ficticio.

No sustituye una prueba con un feed real autorizado.  Genera siempre los mismos
CSV, mide el flujo de importación completo (incluida la validación), una consulta
paginada, una exportación JSON y la preparación de capas del mapa.  El resultado
JSON se puede guardar junto a una release para comparar regresiones locales.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import platform
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.application.jobs.import_job import CancelToken, ImportPhase
from gtfs_explorer.application.queries.map_layers import (
    MapLayerPayload,
    MapViewport,
    simplify_for_viewport,
)
from gtfs_explorer.domain.project import ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.infrastructure.exporting.json_exporter import (
    JsonBundleExporter,
    JsonExportSelection,
)
from gtfs_explorer.product import IDENTITY, runtime_build_id

_SPEC_PATH = Path(f"schemas/gtfs_schedule/{IDENTITY.gtfs_spec_revision}/spec.json")


@dataclass(frozen=True)
class Profile:
    name: str
    trips: int
    stops: int
    stops_per_trip: int

    @property
    def stop_times(self) -> int:
        return self.trips * self.stops_per_trip


_PROFILES = {
    "small": Profile("small", 200, 500, 20),
    "medium": Profile("medium", 10_000, 10_000, 50),
    "rnf-006": Profile("rnf-006", 100_000, 50_000, 50),
}


def _rss_bytes() -> int:
    """Obtiene el conjunto residente del proceso sin dependencia adicional."""
    if sys.platform != "win32":
        return 0

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    function = ctypes.windll.psapi.GetProcessMemoryInfo
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    function.restype = wintypes.BOOL
    ok = function(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return int(counters.PeakWorkingSetSize) if ok else 0


def _write_csv(path: Path, headers: list[str], rows: object) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)  # type: ignore[arg-type]


def build_fixture(destination: Path, profile: Profile) -> None:
    """Escribe un GTFS formal mínimo; no se materializan sus filas en memoria."""
    destination.mkdir(parents=True, exist_ok=True)
    _write_csv(
        destination / "agency.txt",
        ["agency_id", "agency_name", "agency_url", "agency_timezone"],
        [("A1", "Benchmark Transit", "https://example.invalid", "Europe/Madrid")],
    )
    _write_csv(
        destination / "routes.txt",
        ["route_id", "agency_id", "route_short_name", "route_type"],
        [("R1", "A1", "B", "3")],
    )
    _write_csv(
        destination / "calendar.txt",
        [
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
        ],
        [("S1", "1", "1", "1", "1", "1", "1", "1", "20260101", "20261231")],
    )
    _write_csv(
        destination / "stops.txt",
        ["stop_id", "stop_name", "stop_lat", "stop_lon"],
        (
            (f"S{index}", f"Stop {index}", f"43.{index % 10000:04d}", f"-5.{index % 10000:04d}")
            for index in range(profile.stops)
        ),
    )
    _write_csv(
        destination / "trips.txt",
        ["route_id", "service_id", "trip_id"],
        (("R1", "S1", f"T{index}") for index in range(profile.trips)),
    )
    _write_csv(
        destination / "stop_times.txt",
        ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
        (
            (
                f"T{trip}",
                f"{sequence // 60:02d}:{sequence % 60:02d}:00",
                f"{sequence // 60:02d}:{sequence % 60:02d}:30",
                f"S{(trip * profile.stops_per_trip + sequence) % profile.stops}",
                str(sequence + 1),
            )
            for trip in range(profile.trips)
            for sequence in range(profile.stops_per_trip)
        ),
    )


def _map_measurement(profile: Profile) -> dict[str, object]:
    payload = MapLayerPayload(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-5.9 + index / 500_000, 43.0]
                            for index in range(min(profile.stop_times, 100_000))
                        ],
                    },
                }
            ],
        },
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"id": f"S{index}"},
                    "geometry": {"type": "Point", "coordinates": [-5.9 + index / 500_000, 43.0]},
                }
                for index in range(min(profile.stops, 50_000))
            ],
        },
    )
    started = time.perf_counter()
    result = simplify_for_viewport(payload, MapViewport(-5.91, 42.99, -5.70, 43.02, 12))
    elapsed = time.perf_counter() - started
    return {
        "seconds": round(elapsed, 3),
        "output_stops": len(result.stops["features"]),
        "output_shape_points": len(result.shapes["features"][0]["geometry"]["coordinates"]),
    }


def run(profile: Profile, output: Path | None) -> dict[str, object]:
    with TemporaryDirectory(prefix="gtfs-t095-") as temporary:
        root = Path(temporary)
        source, workspace = root / "feed", root / "workspace"
        started = time.perf_counter()
        build_fixture(source, profile)
        fixture_seconds = time.perf_counter() - started
        # DuckDB 1.1.3 acepta una cantidad explícita, no porcentajes, en el
        # parámetro Python usado por este proyecto.
        database = ProjectDatabase(
            workspace / "project.duckdb",
            workspace / "temporary",
            settings=DatabaseSettings(memory_limit="1GB", max_temp_directory_size="1GB", threads=1),
        )
        phases: dict[str, float] = {}
        import_started = time.perf_counter()

        def progress(value: object) -> None:
            phase = getattr(value, "phase")
            phases[str(phase)] = time.perf_counter() - import_started

        command = ImportFeed(
            database,
            ProjectMetadata("benchmark", "Benchmark", ProjectStatus.READY),
            InputSource(source, InputSourceKind.DIRECTORY),
            load_schedule_spec(_SPEC_PATH),
            job_id="benchmark-job",
            feed_id="benchmark-feed",
            on_progress=progress,
        )
        import_result = command.execute()
        import_seconds = time.perf_counter() - import_started
        with database.connection() as connection:
            query_started = time.perf_counter()
            page_rows = connection.execute(
                "SELECT trip_id, stop_sequence FROM gtfs_stop_times "
                "ORDER BY trip_id, stop_sequence LIMIT 500"
            ).fetchall()
            query_seconds = time.perf_counter() - query_started
        export_started = time.perf_counter()
        with database.connection() as connection:
            manifest = JsonBundleExporter().write(
                connection,
                workspace / "export.json",
                feed_id="benchmark-feed",
                selection=JsonExportSelection(frozenset({"R1"})),
            )
        export_seconds = time.perf_counter() - export_started
        token = CancelToken()
        cancel_started = time.perf_counter()
        cancelled = ImportFeed(
            database,
            ProjectMetadata("cancel", "Cancel", ProjectStatus.READY),
            InputSource(source, InputSourceKind.DIRECTORY),
            load_schedule_spec(_SPEC_PATH),
            job_id="cancel-job",
            feed_id="cancel-feed",
            on_progress=lambda value: token.cancel()
            if getattr(value, "phase") is ImportPhase.STAGING
            else None,
        ).execute(token)
        cancel_seconds = time.perf_counter() - cancel_started
        disk_bytes = sum(item.stat().st_size for item in workspace.rglob("*") if item.is_file())
        report = {
            "product": IDENTITY.name,
            "app_version": IDENTITY.version,
            "build_id": runtime_build_id(),
            "gtfs_spec_revision": IDENTITY.gtfs_spec_revision,
            "profile": profile.name,
            "dataset": {
                "trips": profile.trips,
                "stops": profile.stops,
                "stop_times": profile.stop_times,
                "fictitious": True,
            },
            "environment": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "duckdb": __import__("duckdb").__version__,
            },
            "seconds": {
                "fixture": round(fixture_seconds, 3),
                "import_and_validation": round(import_seconds, 3),
                "query_page_500": round(query_seconds, 3),
                "export_json": round(export_seconds, 3),
                "cancellation": round(cancel_seconds, 3),
            },
            "import": {
                "state": str(import_result.state),
                "phase_offsets_seconds": {name: round(value, 3) for name, value in phases.items()},
            },
            "query_rows": len(page_rows),
            "export_bytes": manifest.size_bytes,
            "map": _map_measurement(profile),
            "peak_rss_bytes": _rss_bytes(),
            "workspace_bytes": disk_bytes,
            "cancellation_state": str(cancelled.state),
        }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(_PROFILES), default="small")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    print(
        json.dumps(
            run(_PROFILES[arguments.profile], arguments.output), ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

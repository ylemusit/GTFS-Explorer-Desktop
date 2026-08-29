"""Generación determinista de datasets GTFS para mediciones locales.

Este módulo no contiene umbrales de tiempo: su función es producir el mismo
feed para que el harness pueda comparar observaciones entre máquinas.

Autor: Yeison Arbey Carrillo Lemus.
Todos los derechos reservados.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    agencies: int
    routes: int
    stops: int
    trips_per_route: int
    stop_times_per_trip: int
    shapes: int
    services: int

    @property
    def trips(self) -> int:
        return self.routes * self.trips_per_route

    @property
    def stop_times(self) -> int:
        return self.trips * self.stop_times_per_trip

    @property
    def shape_points(self) -> int:
        """Puntos físicos que genera el fixture por cada shape declarado."""
        return self.shapes * 2

    def counts(self) -> dict[str, int]:
        return {
            "agencies": self.agencies,
            "routes": self.routes,
            "stops": self.stops,
            "trips": self.trips,
            "stop_times": self.stop_times,
            "shapes": self.shapes,
            "shape_points": self.shape_points,
            "services": self.services,
        }


PROFILES: dict[str, BenchmarkProfile] = {
    "small": BenchmarkProfile("small", 1, 10, 500, 25, 20, 10, 2),
    "medium": BenchmarkProfile("medium", 2, 50, 5_000, 20, 50, 50, 4),
    "large": BenchmarkProfile("large", 4, 150, 15_000, 20, 75, 150, 8),
    "xl": BenchmarkProfile("xl", 4, 300, 30_000, 25, 80, 300, 12),
}


def generate_feed(
    destination: Path, profile: BenchmarkProfile, *, seed: int = 21
) -> dict[str, int]:
    """Genera un feed válido y determinista sin materializar filas gigantes."""
    if seed < 0:
        raise ValueError("La semilla debe ser no negativa.")
    destination.mkdir(parents=True, exist_ok=True)
    _write(
        destination / "agency.txt",
        ("agency_id", "agency_name", "agency_url", "agency_timezone"),
        (
            (f"A{index}", f"Benchmark Agency {index}", "https://example.invalid", "Europe/Madrid")
            for index in range(profile.agencies)
        ),
    )
    _write(
        destination / "routes.txt",
        ("route_id", "agency_id", "route_short_name", "route_type"),
        (
            (f"R{index}", f"A{index % profile.agencies}", f"R{index}", "3")
            for index in range(profile.routes)
        ),
    )
    _write(
        destination / "calendar.txt",
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
        (
            (f"S{index}", "1", "1", "1", "1", "1", "1", "1", "20260101", "20261231")
            for index in range(profile.services)
        ),
    )
    _write(
        destination / "stops.txt",
        ("stop_id", "stop_name", "stop_lat", "stop_lon"),
        (
            (
                f"STOP{index}",
                f"Stop {index}",
                f"40.{(index + seed) % 1000:04d}",
                f"-3.{index % 1000:04d}",
            )
            for index in range(profile.stops)
        ),
    )
    _write(
        destination / "shapes.txt",
        ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
        (
            (shape_id, lat, lon, sequence)
            for index in range(profile.shapes)
            for shape_id, lat, lon, sequence in (
                (f"SH{index}", f"40.{(index + seed) % 1000:04d}", f"-3.{index % 1000:04d}", "1"),
                (
                    f"SH{index}",
                    f"40.{(index + seed + 1) % 1000:04d}",
                    f"-3.{(index % 1000) + 1:04d}",
                    "2",
                ),
            )
        ),
    )
    _write(
        destination / "trips.txt",
        ("route_id", "service_id", "trip_id", "direction_id", "shape_id"),
        (
            (
                f"R{route}",
                f"S{trip % profile.services}",
                f"T{route}_{trip}",
                str(trip % 2),
                f"SH{route % profile.shapes}",
            )
            for route in range(profile.routes)
            for trip in range(profile.trips_per_route)
        ),
    )
    _write(
        destination / "stop_times.txt",
        ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
        (
            (
                f"T{route}_{trip}",
                f"{sequence // 60:02d}:{sequence % 60:02d}:00",
                f"{sequence // 60:02d}:{sequence % 60:02d}:30",
                _stop_id(route, trip, sequence, profile),
                str(sequence + 1),
            )
            for route in range(profile.routes)
            for trip in range(profile.trips_per_route)
            for sequence in range(profile.stop_times_per_trip)
        ),
    )
    return profile.counts()


def _write(path: Path, headers: tuple[str, ...], rows: object) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)  # type: ignore[arg-type]


def _stop_id(route: int, trip: int, sequence: int, profile: BenchmarkProfile) -> str:
    index = (route * profile.trips_per_route + trip) * profile.stop_times_per_trip + sequence
    return f"STOP{index % profile.stops}"

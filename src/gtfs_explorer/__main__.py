"""Entrypoint de línea de comandos de GTFS Explorer Desktop."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .infrastructure.filesystem.paths import application_resource_path, resolve_application_paths
from .infrastructure.logging import configure_logging, install_exception_handler
from .product import IDENTITY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gtfs-explorer")
    parser.add_argument("--version", action="version", version=IDENTITY.version)
    parser.add_argument("--runtime-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--map-runtime-smoke", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--map-runtime-smoke-report", type=Path, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--map-runtime-smoke-package", type=Path, default=None, help=argparse.SUPPRESS
    )
    return parser


def _runtime_smoke() -> int:
    import duckdb

    from .domain.spec import load_schedule_spec
    from .infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
    from .presentation.desktop.main_window import MainWindow
    from .presentation.desktop.map.widget import _map_assets_directory

    connection = duckdb.connect(":memory:")
    try:
        if connection.execute("SELECT 42").fetchone() != (42,):
            raise RuntimeError("DuckDB no devolvió el resultado esperado.")
    finally:
        connection.close()
    if MainWindow.__name__ != "MainWindow":
        raise RuntimeError("No se pudo importar la ventana principal.")
    map_assets = _map_assets_directory()
    required_map_assets = ("map_bundle.js", "map_bridge.js", "map_layers.js", "map_worker.mjs")
    missing_map_assets = [name for name in required_map_assets if not (map_assets / name).is_file()]
    if missing_map_assets:
        raise RuntimeError(
            "Faltan recursos locales del mapa: " + ", ".join(sorted(missing_map_assets))
        )
    with tempfile.TemporaryDirectory(prefix="gtfs-explorer-runtime-smoke-") as temporary:
        root = Path(temporary)
        database = ProjectDatabase(
            root / "data.duckdb",
            root / "temp",
            settings=DatabaseSettings(memory_limit="64MB", max_temp_directory_size="64MB"),
        )
        if database.initialize() < 1:
            raise RuntimeError("No se pudieron aplicar las migraciones DuckDB.")
    load_schedule_spec(
        application_resource_path(f"schemas/gtfs_schedule/{IDENTITY.gtfs_spec_revision}/spec.json")
    )
    return 0


def _map_runtime_smoke(report_path: Path | None, map_package: Path | None = None) -> int:
    """Acredita que el WebEngine compilado dibuja una ruta, no solo que importa."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .application.queries.map_layers import MapLayerPayload
    from .presentation.desktop.map.widget import MapWidget

    shapes: dict[str, object] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"trip_id": "T1", "shape_id": "SH1", "color": "#2563eb"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-5.95, 43.30], [-5.85, 43.36], [-5.70, 43.42]],
                },
            }
        ],
    }
    stops: dict[str, object] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"id": "S1", "name": "Norte"},
                "geometry": {"type": "Point", "coordinates": [-5.85, 43.36]},
            }
        ],
    }
    evidence: dict[str, Any] = {
        "bridge_ready": False,
        "package_loaded": map_package is None,
        "route_blue_pixels": 0,
        "basemap_pixels": 0,
        "width": 0,
        "height": 0,
        "errors": [],
    }
    application = QApplication.instance() or QApplication(sys.argv)
    # El smoke gráfico debe ser reproducible y no puede convertir una prueba
    # local del overlay en una petición real al proveedor online.
    widget = MapWidget(
        lambda _trip_id: MapLayerPayload(shapes, stops),
        lambda _stop_id: None,
        provider=None,
    )
    errors: list[str] = []
    widget._bridge.protocol_error.connect(errors.append)  # noqa: SLF001 - smoke del binario

    def event_received(event: object) -> None:
        event_name = getattr(event, "event", "")
        if event_name == "mapError":
            errors.append(str(getattr(event, "payload", {})))
        if event_name == "mapReady" and map_package is not None:
            try:
                widget.set_map_package(map_package)
                evidence["package_loaded"] = True
            except Exception as error:  # pragma: no cover - solo diagnóstico compilado
                errors.append(str(error))

    widget._bridge.event_received.connect(event_received)  # noqa: SLF001 - smoke del binario
    widget.resize(900, 500)
    widget.show()
    widget.show_trip("T1")
    finished = False

    def finish(*, inspect: bool) -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        if inspect:
            image = widget._view.grab().toImage()  # noqa: SLF001 - smoke del binario
            evidence["width"] = image.width()
            evidence["height"] = image.height()
            evidence["bridge_ready"] = widget._bridge.ready  # noqa: SLF001
            blue_pixels = 0
            basemap_pixels = 0
            basemap_colors = (
                (238, 241, 231),
                (220, 232, 212),
                (227, 234, 220),
                (169, 216, 232),
                (215, 204, 190),
            )
            for y in range(image.height()):
                for x in range(image.width()):
                    color = image.pixelColor(x, y)
                    if (
                        color.blue() >= 150
                        and color.red() <= 110
                        and 55 <= color.green() <= 180
                        and color.blue() >= color.green() + 35
                    ):
                        blue_pixels += 1
                    if any(
                        abs(color.red() - red) <= 5
                        and abs(color.green() - green) <= 5
                        and abs(color.blue() - blue) <= 5
                        for red, green, blue in basemap_colors
                    ):
                        basemap_pixels += 1
            evidence["route_blue_pixels"] = blue_pixels
            evidence["basemap_pixels"] = basemap_pixels
        evidence["errors"] = errors
        widget.close()
        application.quit()

    inspection_delay = 15_000 if map_package is not None else 8_000
    timeout = 25_000 if map_package is not None else 15_000
    QTimer.singleShot(inspection_delay, lambda: finish(inspect=True))
    QTimer.singleShot(timeout, lambda: finish(inspect=False))
    application.exec()
    success = (
        bool(evidence["bridge_ready"])
        and bool(evidence["package_loaded"])
        and int(evidence["route_blue_pixels"]) >= 20
        and (map_package is None or int(evidence["basemap_pixels"]) >= 1_000)
        and not errors
    )
    evidence["success"] = success
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if success else 1


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.runtime_smoke:
        return _runtime_smoke()
    if arguments.map_runtime_smoke:
        return _map_runtime_smoke(
            arguments.map_runtime_smoke_report, arguments.map_runtime_smoke_package
        )
    paths = resolve_application_paths(Path(sys.argv[0]))
    debug = os.environ.get("GTFS_EXPLORER_DEBUG") == "1"
    logger = configure_logging(paths.logs_directory, debug=debug)
    install_exception_handler(logger, debug=debug)

    from .presentation.desktop.main_window import run_window

    return run_window(
        application_paths=paths,
        logger=logger,
        logs_directory=paths.logs_directory,
        debug=debug,
    )


if __name__ == "__main__":
    raise SystemExit(main())

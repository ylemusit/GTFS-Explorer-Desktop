"""Renderiza el GTFS GoLines sobre su PMTiles y guarda evidencia gráfica."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gtfs_explorer.application.queries.map_layers import MapLayerPayload
from gtfs_explorer.presentation.desktop.map.widget import MapWidget


def _rows(archive: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    with archive.open(filename) as source:
        text = io.TextIOWrapper(source, encoding="utf-8", newline="")
        return list(csv.DictReader(text))


def _payload(archive_path: Path, route_id: str) -> tuple[str, MapLayerPayload]:
    with zipfile.ZipFile(archive_path) as archive:
        routes = {row["route_id"]: row for row in _rows(archive, "routes.txt")}
        trips = [row for row in _rows(archive, "trips.txt") if row["route_id"] == route_id]
        if route_id not in routes or not trips:
            raise ValueError(f"El GTFS no contiene la ruta {route_id}.")
        trip = sorted(trips, key=lambda row: row["trip_id"])[0]
        shape_rows = sorted(
            (row for row in _rows(archive, "shapes.txt") if row["shape_id"] == trip["shape_id"]),
            key=lambda row: int(row["shape_pt_sequence"]),
        )
        stops = {row["stop_id"]: row for row in _rows(archive, "stops.txt")}
        stop_times = sorted(
            (row for row in _rows(archive, "stop_times.txt") if row["trip_id"] == trip["trip_id"]),
            key=lambda row: int(row["stop_sequence"]),
        )
    shape_feature = {
        "type": "Feature",
        "properties": {
            "trip_id": trip["trip_id"],
            "shape_id": trip["shape_id"],
            "color": f"#{routes[route_id]['route_color']}",
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])] for row in shape_rows
            ],
        },
    }
    stop_features = [
        {
            "type": "Feature",
            "properties": {"id": row["stop_id"], "name": stops[row["stop_id"]]["stop_name"]},
            "geometry": {
                "type": "Point",
                "coordinates": [
                    float(stops[row["stop_id"]]["stop_lon"]),
                    float(stops[row["stop_id"]]["stop_lat"]),
                ],
            },
        }
        for row in stop_times
    ]

    def collection(features: list[dict[str, object]]) -> dict[str, object]:
        return {"type": "FeatureCollection", "features": features}

    return trip["trip_id"], MapLayerPayload(collection([shape_feature]), collection(stop_features))


def verify(
    gtfs: Path,
    map_package: Path,
    screenshot: Path,
    report: Path,
    *,
    route_id: str,
) -> int:
    trip_id, payload = _payload(gtfs, route_id)
    application = QApplication.instance() or QApplication(sys.argv)
    widget = MapWidget(lambda _trip_id: payload, lambda _stop_id: None)
    errors: list[str] = []
    state = {"finished": False, "package_loaded": False}
    evidence: dict[str, object] = {
        "route_id": route_id,
        "trip_id": trip_id,
        "bridge_ready": False,
        "package_loaded": False,
        "route_blue_pixels": 0,
        "basemap_pixels": 0,
        "errors": errors,
    }

    def event_received(event: object) -> None:
        event_name = getattr(event, "event", "")
        if event_name == "mapError":
            errors.append(str(getattr(event, "payload", {})))
        if event_name == "mapReady" and not state["package_loaded"]:
            widget.set_map_package(map_package)
            state["package_loaded"] = True
            evidence["package_loaded"] = True
            widget.show_trip(trip_id)

    widget._bridge.protocol_error.connect(errors.append)  # noqa: SLF001 - verificador gráfico
    widget._bridge.event_received.connect(event_received)  # noqa: SLF001 - verificador gráfico
    widget.resize(1000, 650)
    widget.show()

    def finish(*, inspect: bool) -> None:
        if state["finished"]:
            return
        state["finished"] = True
        if inspect:
            pixmap = widget._view.grab()  # noqa: SLF001 - verificador gráfico
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(screenshot), "PNG")
            image = pixmap.toImage()
            route_pixels = 0
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
                        route_pixels += 1
                    if any(
                        abs(color.red() - red) <= 5
                        and abs(color.green() - green) <= 5
                        and abs(color.blue() - blue) <= 5
                        for red, green, blue in basemap_colors
                    ):
                        basemap_pixels += 1
            evidence.update(
                {
                    "bridge_ready": widget._bridge.ready,  # noqa: SLF001
                    "route_blue_pixels": route_pixels,
                    "basemap_pixels": basemap_pixels,
                    "width": image.width(),
                    "height": image.height(),
                }
            )
        widget.close()
        application.quit()

    QTimer.singleShot(15_000, lambda: finish(inspect=True))
    QTimer.singleShot(25_000, lambda: finish(inspect=False))
    application.exec()
    success = (
        evidence["bridge_ready"] is True
        and evidence["package_loaded"] is True
        and int(evidence["route_blue_pixels"]) >= 20
        and int(evidence["basemap_pixels"]) >= 1_000
        and not errors
    )
    evidence["success"] = success
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs", required=True, type=Path)
    parser.add_argument("--map-package", required=True, type=Path)
    parser.add_argument("--screenshot", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--route-id", default="centrobus-og1")
    arguments = parser.parse_args()
    return verify(
        arguments.gtfs,
        arguments.map_package,
        arguments.screenshot,
        arguments.report,
        route_id=arguments.route_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())

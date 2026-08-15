"""Mide localmente el presupuesto visual de T075, sin abrir Qt/WebEngine."""

from __future__ import annotations

import json
import platform
import time
from typing import cast

from gtfs_explorer.application.queries.map_layers import (
    MapLayerPayload,
    MapViewport,
    simplify_for_viewport,
)


def main() -> None:
    stop_count, point_count = 50_000, 100_000
    payload = MapLayerPayload(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"color": "#2563EB"},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [-5.9 + index / 500_000, 43.0 + (index % 97) / 100_000]
                            for index in range(point_count)
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
                for index in range(stop_count)
            ],
        },
    )
    started = time.perf_counter()
    result = simplify_for_viewport(payload, MapViewport(-5.85, 42.99, -5.75, 43.02, 12))
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 2)
    output_stops = cast(list[object], result.stops["features"])
    output_shapes = cast(list[dict[str, object]], result.shapes["features"])
    output_geometry = cast(dict[str, object], output_shapes[0]["geometry"])
    output_points = cast(list[object], output_geometry["coordinates"])
    print(
        json.dumps(
            {
                "platform": platform.platform(),
                "input_stops": stop_count,
                "input_shape_points": point_count,
                "output_stops": len(output_stops),
                "output_shape_points": len(output_points),
                "elapsed_ms": elapsed_ms,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

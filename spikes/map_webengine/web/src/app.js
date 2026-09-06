import * as maplibregl from "maplibre-gl";
import {PMTiles, Protocol} from "pmtiles";

new QWebChannel(qt.webChannelTransport, async function (channel) {
  const bridge = channel.objects.spikeBridge;
  try {
    const roundtrip = new Promise(function (resolve) {
      bridge.echo("js-ping", resolve);
    });
    const archiveUrl = new URL("sample.pmtiles", window.location.href).href;
    maplibregl.setWorkerUrl(new URL("map_worker.mjs", window.location.href).href);
    const archive = new PMTiles(archiveUrl);
    const header = await archive.getHeader();
    const protocol = new Protocol();
    protocol.add(archive);
    maplibregl.addProtocol("pmtiles", protocol.tile);

    bridge.report(JSON.stringify({kind: "feature-clicked", feature: "stop:fixture"}));
    const map = new maplibregl.Map({
    container: "map",
    center: [0, 0],
    zoom: 0,
    attributionControl: false,
    style: {
      version: 8,
      sources: {
        localPmtiles: {
          type: "raster",
          url: `pmtiles://${archiveUrl}`,
          tileSize: 256,
          attribution: "Fixture sintético local"
        },
        gtfs: {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                properties: {kind: "route"},
                geometry: {type: "LineString", coordinates: [[-20, -10], [0, 15], [20, -5]]}
              },
              {
                type: "Feature",
                properties: {kind: "stop"},
                geometry: {type: "Point", coordinates: [0, 15]}
              }
            ]
          }
        }
      },
      layers: [
        {id: "base", type: "raster", source: "localPmtiles"},
        {id: "route", type: "line", source: "gtfs", filter: ["==", "kind", "route"], paint: {"line-color": "#155eef", "line-width": 5}},
        {id: "stop", type: "circle", source: "gtfs", filter: ["==", "kind", "stop"], paint: {"circle-color": "#d92d20", "circle-radius": 8}}
      ]
    }
    });

    map.on("error", function (event) {
      bridge.report(JSON.stringify({
        kind: "map-error",
        message: event.error ? event.error.message : "Error de mapa sin detalle"
      }));
    });

    map.once("idle", async function () {
      const renderedKinds = Array.from(new Set(
        map.queryRenderedFeatures(undefined, {layers: ["route", "stop"]})
          .map(function (feature) { return feature.properties.kind; })
      )).sort();
      bridge.report(JSON.stringify({
        kind: "map-result",
        // Las capas GTFS renderizadas son la evidencia útil del mapa para este
        // spike; la tesela raster opcional puede mantener el estilo pendiente.
        loaded: map.isStyleLoaded() ||
          (renderedKinds.includes("route") && renderedKinds.includes("stop")),
        specVersion: header.specVersion,
        roundtrip: await roundtrip,
        renderedKinds: renderedKinds
      }));
    });
  } catch (error) {
    bridge.report(JSON.stringify({
      kind: "map-failure",
      message: error instanceof Error ? error.message : String(error)
    }));
  }
});

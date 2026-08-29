/* Capas locales MapLibre. Los textos del feed nunca se insertan como HTML. */
(function () {
  "use strict";

  const EMPTY = {type: "FeatureCollection", features: []};
  let map = null;
  let selectedStopId = null;
  let viewportRequest = 0;
  let mapLoaded = false;
  let mapReadyReported = false;
  let pendingReplacement = null;
  let latestReplacement = null;
  let pendingCamera = null;
  let activeBasemapSource = "unavailable";
  let activeBasemapRequest = 0;
  let reportedErrorRequest = null;
  let styleTransitionPending = false;

  function reportMapReadyWhenBridgeIsAvailable() {
    const bridge = window.GTFSExplorerMapBridge;
    if (!mapLoaded || mapReadyReported || !bridge || !layersAreReady()) return;
    mapReadyReported = bridge.mapReady() === true;
  }

  function layersAreReady() {
    return !!map && map.isStyleLoaded() && !!map.getSource("gtfs-shapes") && !!map.getSource("gtfs-stops");
  }

  function installTransitLayers() {
    if (!map) return;
    if (!map.getSource("gtfs-shapes")) map.addSource("gtfs-shapes", {type: "geojson", data: EMPTY});
    if (!map.getSource("gtfs-stops")) map.addSource("gtfs-stops", {type: "geojson", data: EMPTY, cluster: true, clusterRadius: 48, clusterMaxZoom: 14});
    if (!map.getLayer("gtfs-shapes-line")) map.addLayer({id: "gtfs-shapes-line", type: "line", source: "gtfs-shapes", paint: {"line-color": ["get", "color"], "line-width": 4}});
    if (!map.getLayer("gtfs-stops-cluster")) map.addLayer({id: "gtfs-stops-cluster", type: "circle", source: "gtfs-stops", filter: ["has", "point_count"], paint: {"circle-radius": ["step", ["get", "point_count"], 13, 50, 18, 250, 24], "circle-color": "#2563eb"}});
    if (!map.getLayer("gtfs-stops-cluster-label")) map.addLayer({id: "gtfs-stops-cluster-label", type: "symbol", source: "gtfs-stops", filter: ["has", "point_count"], layout: {"text-field": ["get", "point_count_abbreviated"], "text-size": 11}, paint: {"text-color": "#ffffff"}});
    if (!map.getLayer("gtfs-stops-circle")) map.addLayer({id: "gtfs-stops-circle", type: "circle", source: "gtfs-stops", filter: ["!", ["has", "point_count"]], paint: {"circle-radius": ["case", ["get", "selected"], 8, 5], "circle-color": "#ffffff", "circle-stroke-color": "#0f172a", "circle-stroke-width": 2}});
  }

  function popupText(feature) {
    const properties = feature.properties || {};
    const content = document.createElement("div");
    content.textContent = `${properties.name || "Sin nombre"} (${properties.id || "Sin ID"})`;
    return content;
  }

  function updateSelection() {
    if (!map) return;
    const source = map.getSource("gtfs-stops");
    if (!source) return;
    const data = source.serialize().data;
    source.setData({
      ...data,
      features: data.features.map((feature) => ({
        ...feature,
        properties: {...feature.properties, selected: feature.properties.id === selectedStopId},
      })),
    });
  }

  function captureCamera() {
    if (!map || typeof map.getCenter !== "function") return null;
    const center = map.getCenter();
    const values = [center && center.lng, center && center.lat, map.getZoom(), map.getBearing(), map.getPitch()];
    if (!values.every((value) => Number.isFinite(value))) return null;
    return {center: [values[0], values[1]], zoom: values[2], bearing: values[3], pitch: values[4]};
  }

  function restoreCamera() {
    if (!map || !pendingCamera || typeof map.jumpTo !== "function") return;
    const camera = pendingCamera;
    pendingCamera = null;
    try { map.jumpTo(camera); } catch (_) { pendingCamera = null; }
  }

  function overlayForStyle() {
    if (!latestReplacement) return null;
    return {payload: latestReplacement.payload, fit: false, resetSelection: false};
  }

  function reportMapError(kind) {
    if (reportedErrorRequest === activeBasemapRequest) return;
    reportedErrorRequest = activeBasemapRequest;
    const bridge = window.GTFSExplorerMapBridge;
    if (bridge) bridge.mapError({source: activeBasemapSource, kind, request: activeBasemapRequest});
  }

  function fitData(shapes, stops) {
    const coordinates = [...shapes.features, ...stops.features].flatMap((feature) =>
      feature.geometry.type === "LineString" ? feature.geometry.coordinates : [feature.geometry.coordinates]
    );
    if (!coordinates.length) return;
    const bounds = coordinates.reduce(
      (result, coordinate) => result.extend(coordinate),
      new window.GTFSExplorerMap.maplibregl.LngLatBounds(coordinates[0], coordinates[0])
    );
    map.fitBounds(bounds, {padding: 36, maxZoom: 16, duration: 0});
  }

  function applyReplacement(payload, fit, resetSelection) {
    if (!layersAreReady()) return false;
    map.resize();
    const shapes = payload.shapes || EMPTY;
    const stops = payload.stops || EMPTY;
    if (resetSelection) selectedStopId = null;
    map.getSource("gtfs-shapes").setData(shapes);
    const selectedStops = Array.isArray(stops.features) ? {
      ...stops,
      features: stops.features.map((feature) => ({
        ...feature,
        properties: {...feature.properties, selected: feature.properties && feature.properties.id === selectedStopId},
      })),
    } : stops;
    map.getSource("gtfs-stops").setData(selectedStops);
    if (fit) fitData(shapes, stops);
    return true;
  }

  function flushPendingReplacement() {
    if (!pendingReplacement) return;
    const {payload, fit, resetSelection} = pendingReplacement;
    if (applyReplacement(payload, fit, resetSelection)) pendingReplacement = null;
  }

  function neutralStyle() {
    return {
      version: 8,
      sources: {},
      layers: [{id: "empty-background", type: "background", paint: {"background-color": "#f8fafc"}}],
    };
  }

  function initialize() {
    const {maplibregl} = window.GTFSExplorerMap;
    maplibregl.setWorkerUrl("map_worker.mjs");
    map = new maplibregl.Map({
      container: "map",
      center: [0, 0], zoom: 1,
      style: neutralStyle(),
    });
    map.on("error", () => reportMapError("map"));
    map.on("load", () => {
      mapLoaded = true;
      installTransitLayers();
      map.on("click", "gtfs-stops-circle", (event) => {
        const feature = event.features[0];
        const id = feature.properties && feature.properties.id;
        if (typeof id !== "string") return;
        selectedStopId = id;
        updateSelection();
        new maplibregl.Popup().setLngLat(event.lngLat).setDOMContent(popupText(feature)).addTo(map);
        const bridge = window.GTFSExplorerMapBridge;
        if (bridge) bridge.featureClicked({kind: "stop", id});
      });
      map.on("mouseenter", "gtfs-stops-circle", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "gtfs-stops-circle", () => { map.getCanvas().style.cursor = ""; });
      map.on("moveend", () => {
        const bounds = map.getBounds();
        viewportRequest += 1;
        // El contador permite a Qt desechar cualquier respuesta anterior al último pan/zoom.
        const bridge = window.GTFSExplorerMapBridge;
        if (bridge) bridge.viewportChanged({request: viewportRequest, west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth(), zoom: map.getZoom()});
      });
      map.on("idle", () => {
        reportMapReadyWhenBridgeIsAvailable();
        flushPendingReplacement();
      });
      reportMapReadyWhenBridgeIsAvailable();
    });
    map.on("style.load", () => {
      if (!mapLoaded) return;
      styleTransitionPending = false;
      installTransitLayers();
      restoreCamera();
      if (!pendingReplacement) pendingReplacement = overlayForStyle();
      flushPendingReplacement();
    });
  }

  window.GTFSExplorerLayers = {
    replace: function (payload, fit = true, resetSelection = true) {
      latestReplacement = {payload, fit, resetSelection};
      if (!styleTransitionPending && applyReplacement(payload, fit, resetSelection)) {
        pendingReplacement = null;
        return true;
      }
      // Conserva únicamente el estado visual más reciente. El evento idle lo
      // aplicará cuando MapLibre termine de publicar el estilo y sus fuentes.
      pendingReplacement = {payload, fit, resetSelection};
      return false;
    },
    selectStop: function (stopId) { selectedStopId = stopId; updateSelection(); },
    clearBasemap: function (request = 0) {
      if (!map) return false;
      activeBasemapSource = "unavailable";
      activeBasemapRequest = request;
      reportedErrorRequest = null;
      pendingCamera = captureCamera();
      pendingReplacement = overlayForStyle();
      styleTransitionPending = true;
      try {
        map.setStyle(neutralStyle());
        return true;
      } catch (_) {
        reportMapError("style");
        return false;
      }
    },
    setBasemap: async function (styleUrl, pmtilesUrl, request = 0) {
      if (!map) return false;
      activeBasemapSource = "local";
      activeBasemapRequest = request;
      reportedErrorRequest = null;
      pendingCamera = captureCamera();
      styleTransitionPending = true;
      const {maplibregl, PMTiles, Protocol} = window.GTFSExplorerMap;
      const protocol = new Protocol();
      protocol.add(new PMTiles(pmtilesUrl));
      maplibregl.addProtocol("pmtiles", protocol.tile);
      const style = await fetch(styleUrl, {cache: "no-store"}).then((response) => {
        if (!response.ok) throw new Error("No se pudo cargar el estilo offline.");
        return response.json();
      });
      if (request !== activeBasemapRequest || activeBasemapSource !== "local") return false;
      const replace = (value) => typeof value === "string"
        ? value.replaceAll("pmtiles://basemap.pmtiles", `pmtiles://${pmtilesUrl}`)
        : Array.isArray(value) ? value.map(replace)
          : value && typeof value === "object"
            ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, replace(item)]))
            : value;
      pendingReplacement = overlayForStyle();
      map.setStyle(replace(style));
      return true;
    },
    setOnlineBasemap: async function (tileUrl, tileSize = 256, minZoom = 0, maxZoom = 19, request = 0) {
      if (!map) return false;
      if (typeof tileUrl !== "string" || !tileUrl.includes("{z}") || !tileUrl.includes("{x}") || !tileUrl.includes("{y}")) {
        throw new Error("La plantilla de teselas online no es válida.");
      }
      if (tileUrl.includes("?") || tileUrl.includes("#")) {
        throw new Error("La plantilla de teselas online no admite query ni fragmentos.");
      }
      activeBasemapSource = "online";
      activeBasemapRequest = request;
      reportedErrorRequest = null;
      pendingCamera = captureCamera();
      pendingReplacement = overlayForStyle();
      styleTransitionPending = true;
      map.setStyle({
        version: 8,
        sources: {"online-basemap": {type: "raster", tiles: [tileUrl], tileSize, minzoom: minZoom, maxzoom: maxZoom}},
        layers: [{id: "online-basemap-layer", type: "raster", source: "online-basemap"}],
      });
      return true;
    },
  };
  window.addEventListener("gtfs-explorer-map-command", (event) => {
    if (!map) return;
    const {longitude, latitude, zoom} = event.detail.payload;
    map.jumpTo({center: [longitude, latitude], zoom});
  });
  window.addEventListener("gtfs-explorer-map-bridge-ready", reportMapReadyWhenBridgeIsAvailable);
  initialize();
}());

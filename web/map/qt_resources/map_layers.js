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
    if (!map.getSource("gtfs-stops")) map.addSource("gtfs-stops", {type: "geojson", data: EMPTY});
    if (!map.getLayer("gtfs-route-context")) map.addLayer({id: "gtfs-route-context", type: "line", source: "gtfs-shapes", paint: {"line-color": "#0f172a", "line-width": 9, "line-opacity": 0.82}});
    if (!map.getLayer("gtfs-shapes-line")) map.addLayer({id: "gtfs-shapes-line", type: "line", source: "gtfs-shapes", paint: {"line-color": ["get", "color"], "line-width": 5, "line-opacity": 1}});
    if (!map.getLayer("gtfs-stops-circle")) map.addLayer({id: "gtfs-stops-circle", type: "circle", source: "gtfs-stops", paint: {"circle-radius": ["case", ["get", "selected"], 8, 5], "circle-color": "#ffffff", "circle-stroke-color": "#0f172a", "circle-stroke-width": 2}});
    if (!map.getLayer("gtfs-stops-endpoints")) map.addLayer({id: "gtfs-stops-endpoints", type: "circle", source: "gtfs-stops", filter: ["in", ["get", "endpoint"], ["literal", ["origin", "destination"]]], paint: {"circle-radius": 7, "circle-color": ["match", ["get", "endpoint"], "origin", "#16a34a", "destination", "#dc2626", "#ffffff"], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2}});
  }

  function popupText(feature) {
    const properties = feature.properties || {};
    const content = document.createElement("div");
    const popup = properties.popup || {};
    const line = (label, value) => {
      if (!value) return;
      const item = document.createElement("div");
      item.textContent = `${label}${value}`;
      content.appendChild(item);
    };
    const title = document.createElement("strong");
    title.textContent = properties.name || "Sin nombre";
    content.appendChild(title);
    line("Parada ", properties.id || "Sin ID");
    if (Number.isInteger(properties.sequence)) line("Secuencia ", String(properties.sequence));
    line("Línea ", popup.route || "");
    line("Destino ", popup.headsign || "");
    line("Operador: ", popup.agency || "");
    line("Llegada ", popup.arrival || "");
    line("Salida ", popup.departure || "");
    const others = Array.isArray(popup.other_routes) ? popup.other_routes : [];
    if (others.length) {
      const heading = document.createElement("div");
      heading.textContent = "También pasan:";
      content.appendChild(heading);
      others.forEach((other) => {
        const item = document.createElement("div");
        const times = Array.isArray(other.times) ? other.times.join(" · ") : "";
        item.textContent = `${other.route || "Ruta"}${other.agency ? ` · ${other.agency}` : ""}${times ? `\nHorario programado: ${times}` : ""}`;
        item.style.whiteSpace = "pre-line";
        content.appendChild(item);
      });
    }
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
    ).filter((coordinate) => Array.isArray(coordinate) && coordinate.length >= 2
      && Number.isFinite(coordinate[0]) && Number.isFinite(coordinate[1])
      && coordinate[0] >= -180 && coordinate[0] <= 180 && coordinate[1] >= -90 && coordinate[1] <= 90);
    if (!coordinates.length) return;
    const bounds = coordinates.reduce(
      (result, coordinate) => result.extend(coordinate),
      new window.GTFSExplorerMap.maplibregl.LngLatBounds(coordinates[0], coordinates[0])
    );
    map.fitBounds(bounds, {padding: 36, maxZoom: 16, duration: 0});
  }

  function fitBounds(west, south, east, north) {
    if (![west, south, east, north].every(Number.isFinite)) return;
    const safeWest = Math.max(-180, Math.min(180, west));
    const safeEast = Math.max(-180, Math.min(180, east));
    const safeSouth = Math.max(-90, Math.min(90, south));
    const safeNorth = Math.max(-90, Math.min(90, north));
    if (safeWest > safeEast || safeSouth > safeNorth) return;
    const epsilon = 0.0001;
    const expandedWest = safeWest === safeEast ? safeWest - epsilon : safeWest;
    const expandedEast = safeWest === safeEast ? safeEast + epsilon : safeEast;
    const expandedSouth = safeSouth === safeNorth ? safeSouth - epsilon : safeSouth;
    const expandedNorth = safeSouth === safeNorth ? safeNorth + epsilon : safeNorth;
    const bounds = new window.GTFSExplorerMap.maplibregl.LngLatBounds(
      [expandedWest, expandedSouth], [expandedEast, expandedNorth]
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
      // QWebEngine puede cambiar de tamaño al arrastrar el splitter de Explorar.
      // MapLibre mantiene el canvas sincronizado mediante ResizeObserver.
      trackResize: true,
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
    const {command, payload} = event.detail;
    if (command === "fitBounds") fitBounds(payload.west, payload.south, payload.east, payload.north);
    else map.jumpTo({center: [payload.longitude, payload.latitude], zoom: payload.zoom});
  });
  window.addEventListener("gtfs-explorer-map-bridge-ready", reportMapReadyWhenBridgeIsAvailable);
  initialize();
}());

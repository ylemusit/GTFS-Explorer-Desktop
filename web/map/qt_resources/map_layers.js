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
  let stopDrag = null;
  let vertexDrag = null;
  let editMode = "NORMAL";
  let vertexAction = null;
  let applySerial = 0;
  let lastApplyTimings = null;
  let idleSerial = 0;
  let reportedIdleSerial = 0;
  let uiTexts = {
    stopNameUnknown: "Parada sin nombre",
    routeChip: "Ruta",
    route: "Ruta",
    origin: "Origen",
    intermediate: "Intermedia",
    destination: "Destino",
    operations: "Operación",
    scheduledTime: "Horario programado",
    arrival: "Llegada",
    departure: "Salida",
    sequence: "Secuencia",
    previous: "Anterior",
    next: "Siguiente",
    dwell: "Permanencia",
    context: "Contexto",
    agency: "Agencia",
    trip: "Viaje",
    service: "Servicio",
    headsign: "Destino",
    technical: "Datos técnicos",
    otherRoutes: "Otras rutas",
    stopId: "stop_id",
    routeId: "route_id",
    actions: "Acciones",
    center: "Centrar",
    edit: "Editar parada",
    details: "Más detalles",
    notAvailable: "—",
  };

  function reportEdit(payload) {
    const bridge = window.GTFSExplorerMapBridge;
    if (!bridge || typeof bridge.editGesture !== "function") return false;
    return bridge.editGesture(payload) === true;
  }

  function reportMapReadyWhenBridgeIsAvailable() {
    const bridge = window.GTFSExplorerMapBridge;
    if (!mapLoaded || mapReadyReported || !bridge || !layersAreReady()) return;
    mapReadyReported = bridge.mapReady() === true;
  }

  function layersAreReady() {
    return !!map && map.isStyleLoaded() && !!map.getSource("gtfs-shapes")
      && !!map.getSource("gtfs-stops") && !!map.getSource("gtfs-shape-points");
  }

  function installTransitLayers() {
    if (!map) return;
    if (!map.getSource("gtfs-shapes")) map.addSource("gtfs-shapes", {type: "geojson", data: EMPTY});
    if (!map.getSource("gtfs-stops")) map.addSource("gtfs-stops", {type: "geojson", data: EMPTY});
    if (!map.getSource("gtfs-shape-points")) map.addSource("gtfs-shape-points", {type: "geojson", data: EMPTY});
    if (!map.getLayer("gtfs-route-stroke-halo")) map.addLayer({id: "gtfs-route-stroke-halo", type: "line", source: "gtfs-shapes", minzoom: 0, maxzoom: 24, paint: {"line-color": ["coalesce", ["get", "halo_color"], "#111827"], "line-width": ["+", ["coalesce", ["get", "line_width"], 4], ["case", ["get", "route_selected"], 7, 4]], "line-offset": ["coalesce", ["get", "lane_offset"], 0], "line-opacity": ["case", ["get", "route_selected"], 1, ["get", "dimmed"], 0.2, ["get", "route_locked"], 0.55, 0.9]}});
    if (!map.getLayer("gtfs-route-context")) map.addLayer({id: "gtfs-route-context", type: "line", source: "gtfs-shapes", minzoom: 0, maxzoom: 24, paint: {"line-color": ["get", "color"], "line-width": ["+", ["coalesce", ["get", "line_width"], 4], 4], "line-offset": ["coalesce", ["get", "lane_offset"], 0], "line-opacity": ["case", ["get", "dimmed"], 0.1, ["get", "route_locked"], 0.22, ["get", "route_active"], 0.45, 0.2]}});
    if (!map.getLayer("gtfs-shapes-line")) map.addLayer({id: "gtfs-shapes-line", type: "line", source: "gtfs-shapes", minzoom: 0, maxzoom: 24, paint: {"line-color": ["get", "color"], "line-width": ["+", ["coalesce", ["get", "line_width"], 4], ["case", ["get", "route_selected"], 2, 0]], "line-offset": ["coalesce", ["get", "lane_offset"], 0], "line-opacity": ["case", ["get", "route_selected"], 1, ["get", "dimmed"], 0.18, ["get", "route_locked"], 0.55, ["get", "route_active"], 1, 0.72]}});
    if (!map.getLayer("gtfs-stops-circle")) map.addLayer({id: "gtfs-stops-circle", type: "circle", source: "gtfs-stops", minzoom: 0, maxzoom: 24, paint: {"circle-radius": ["interpolate", ["linear"], ["zoom"], 0, 4, 8, 5, 14, 6, 20, 8], "circle-color": ["get", "color"], "circle-opacity": ["case", ["get", "dimmed"], 0.25, ["get", "route_locked"], 0.65, 1], "circle-stroke-color": "#ffffff", "circle-stroke-opacity": ["case", ["get", "selected"], 1, ["get", "dimmed"], 0.3, 1], "circle-stroke-width": ["case", ["get", "selected"], 3, 2]}});
    if (!map.getLayer("gtfs-stops-endpoints")) map.addLayer({id: "gtfs-stops-endpoints", type: "circle", source: "gtfs-stops", minzoom: 0, maxzoom: 24, filter: ["in", ["get", "endpoint"], ["literal", ["origin", "destination"]]], paint: {"circle-radius": ["interpolate", ["linear"], ["zoom"], 0, 5, 14, 7, 20, 9], "circle-color": ["match", ["get", "endpoint"], "origin", "#16a34a", "destination", "#dc2626", "#ffffff"], "circle-opacity": ["case", ["get", "dimmed"], 0.35, 1], "circle-stroke-color": "#ffffff", "circle-stroke-opacity": ["case", ["get", "dimmed"], 0.35, 1], "circle-stroke-width": 2}});
    if (!map.getLayer("gtfs-shape-points-circle")) map.addLayer({id: "gtfs-shape-points-circle", type: "circle", source: "gtfs-shape-points", minzoom: 0, maxzoom: 24, paint: {"circle-radius": ["case", ["get", "route_active"], 6, 4], "circle-color": ["get", "color"], "circle-opacity": ["case", ["get", "dimmed"], 0.25, ["get", "route_locked"], 0.55, 1], "circle-stroke-color": "#ffffff", "circle-stroke-width": 2}});
  }

  function popupText(feature) {
    const properties = feature.properties || {}, popup = properties.popup || {};
    const content = document.createElement("div"), stopId = String(properties.id || popup.stop_id || "");
    const add = (value, tag = "div") => { if (!value) return; const item = document.createElement(tag); item.textContent = value; content.appendChild(item); };
    const row = (label, value) => add(label ? `${label}: ${value || uiTexts.notAvailable}` : value);
    add(popup.name || properties.name || uiTexts.stopNameUnknown, "strong");
    const chip = document.createElement("span");
    chip.textContent = `${uiTexts.routeChip} ${popup.route_short_name || properties.route_id || uiTexts.notAvailable}`;
    chip.style.cssText = `padding:2px 7px;margin:4px 0;border-radius:10px;color:#fff;background:${popup.route_color || properties.color || "#2563eb"}`;
    content.appendChild(chip);
    add(popup.route_long_name || popup.route || "");
    row("", properties.endpoint === "origin" || popup.endpoint === "origin" ? uiTexts.origin : properties.endpoint === "destination" || popup.endpoint === "destination" ? uiTexts.destination : uiTexts.intermediate);
    // El popup es un resumen de orientación; `other_routes` y el resto de la
    // ficha completa viven en el inspector Qt, estable ante zoom y paneo.
    [[uiTexts.arrival, popup.arrival || popup.arrival_time], [uiTexts.departure, popup.departure || popup.departure_time], [uiTexts.sequence, popup.sequence !== undefined ? popup.sequence : properties.sequence]].forEach(([label, value]) => row(label, value));
    [["center", uiTexts.center], ["details", uiTexts.details]].forEach(([action, label]) => { const button = document.createElement("button"); button.type = "button"; button.textContent = label; button.addEventListener("click", () => { const bridge = window.GTFSExplorerMapBridge; if (bridge && typeof bridge.featureClicked === "function") bridge.featureClicked({kind: "stop", id: stopId, action}); }); content.appendChild(button); });
    return content;
  }

  function centerStop(stopId) {
    if (!map) return false;
    const source = map.getSource("gtfs-stops");
    if (!source || typeof source.serialize !== "function") return false;
    const data = source.serialize().data || EMPTY;
    const feature = (data.features || []).find((candidate) =>
      candidate && candidate.properties && String(candidate.properties.id) === String(stopId));
    const coordinates = feature && feature.geometry && feature.geometry.coordinates;
    if (!Array.isArray(coordinates) || coordinates.length < 2) return false;
    map.easeTo({center: coordinates, duration: 0});
    selectedStopId = String(stopId);
    updateSelection();
    return true;
  }

  function setUiTexts(texts) {
    if (!texts || typeof texts !== "object") return false;
    uiTexts = {...uiTexts, ...texts};
    return true;
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

  function updatePointSource(sourceId, id, longitude, latitude) {
    if (!map) return;
    const source = map.getSource(sourceId);
    if (!source || typeof source.serialize !== "function") return;
    const data = source.serialize().data || EMPTY;
    source.setData({
      ...data,
      features: (data.features || []).map((feature) => {
        if (!feature.properties || String(feature.properties.id) !== String(id)) return feature;
        return {...feature, geometry: {type: "Point", coordinates: [longitude, latitude]}};
      }),
    });
  }

  function setEditMode(mode) {
    editMode = ["NORMAL", "EDIT_ROUTE", "SELECT_SEGMENT", "REDRAW_SEGMENT"].includes(mode)
      ? mode : "NORMAL";
    stopDrag = null;
    vertexDrag = null;
    vertexAction = null;
    if (map && map.dragPan && typeof map.dragPan.enable === "function") map.dragPan.enable();
    if (editMode === "NORMAL" && map) {
      const source = map.getSource("gtfs-shape-points");
      if (source) source.setData(EMPTY);
    }
    return editMode;
  }

  function setVertexAction(action) {
    vertexAction = ["add", "delete"].includes(action) ? action : null;
    return vertexAction;
  }

  function nearestSegment(coordinates, point) {
    if (!Array.isArray(coordinates) || coordinates.length < 2) return null;
    let best = 0;
    let distance = Infinity;
    coordinates.slice(0, -1).forEach((candidate, index) => {
      const next = coordinates[index + 1];
      const dx = next[0] - candidate[0];
      const dy = next[1] - candidate[1];
      const denominator = dx * dx + dy * dy || 1;
      const projection = Math.max(0, Math.min(1,
        ((point.lng - candidate[0]) * dx + (point.lat - candidate[1]) * dy) / denominator));
      const longitude = candidate[0] + projection * dx;
      const latitude = candidate[1] + projection * dy;
      const value = (point.lng - longitude) ** 2 + (point.lat - latitude) ** 2;
      if (value < distance) { distance = value; best = index; }
    });
    return best + 1;
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

  function visibleRouteCount(payload) {
    const routeIds = new Set();
    [payload.shapes, payload.stops, payload.shape_points].forEach((collection) => {
      const features = collection && Array.isArray(collection.features) ? collection.features : [];
      features.forEach((feature) => {
        const routeId = feature && feature.properties && feature.properties.route_id;
        if (routeId !== undefined && routeId !== null && String(routeId)) routeIds.add(String(routeId));
      });
    });
    return routeIds.size;
  }

  function routeLineWidth(sharedRouteCount, active) {
    const count = Math.max(1, Number(sharedRouteCount) || 1);
    let width = Math.max(2.2, Math.min(6, 5.5 / count + 0.8));
    if (active) width = Math.min(7.5, width + 1.2);
    return width;
  }

  function reportPerformanceWhenIdle(serial) {
    if (!lastApplyTimings || lastApplyTimings.apply_serial !== serial
      || lastApplyTimings.idle_final !== null || serial <= reportedIdleSerial) return;
    lastApplyTimings.idle_final = performance.now();
    idleSerial = serial;
    reportedIdleSerial = serial;
    const bridge = window.GTFSExplorerMapBridge;
    if (bridge && typeof bridge.performanceTimings === "function") {
      bridge.performanceTimings({...lastApplyTimings});
    }
  }

  function applyReplacement(payload, fit, resetSelection, generationId = null) {
    if (!layersAreReady()) return false;
    const serial = ++applySerial;
    const payloadReceived = performance.now();
    const started = payloadReceived;
    map.resize();
    const shapes = payload.shapes || EMPTY;
    const stops = payload.stops || EMPTY;
    const shapePoints = payload.shape_points || EMPTY;
    if (resetSelection) selectedStopId = null;
    const shapesStarted = performance.now();
    map.getSource("gtfs-shapes").setData(shapes);
    const shapesFinished = performance.now();
    const selectedStops = Array.isArray(stops.features) ? {
      ...stops,
      features: stops.features.map((feature) => ({
        ...feature,
        properties: {...feature.properties, selected: feature.properties && feature.properties.id === selectedStopId},
      })),
    } : stops;
    const stopsStarted = performance.now();
    map.getSource("gtfs-stops").setData(selectedStops);
    const stopsFinished = performance.now();
    const overlaysStarted = performance.now();
    map.getSource("gtfs-shape-points").setData(shapePoints);
    const overlaysFinished = performance.now();
    if (fit) fitData(shapes, stops);
    lastApplyTimings = {
      generation_id: Number.isInteger(generationId) ? generationId : null,
      serial,
      apply_serial: serial,
      payload_received: payloadReceived,
      shapes_setdata_start: shapesStarted,
      shapes_setdata_end: shapesFinished,
      stops_setdata_start: stopsStarted,
      stops_setdata_end: stopsFinished,
      other_setdata_start: overlaysStarted,
      other_setdata_end: overlaysFinished,
      render_final: performance.now(),
      idle_final: null,
      final_visible_routes: visibleRouteCount(payload),
      shapes_ms: shapesFinished - shapesStarted,
      stops_ms: stopsFinished - stopsStarted,
      overlays_ms: overlaysFinished - overlaysStarted,
      total_ms: performance.now() - started,
    };
    return true;
  }

  function updateRouteStates(states) {
    if (!layersAreReady() || !Array.isArray(states)) return false;
    const byRoute = new Map(states.map((state) => [String(state.route_id), state]));
    ["gtfs-shapes", "gtfs-stops", "gtfs-shape-points"].forEach((sourceId) => {
      const source = map.getSource(sourceId);
      if (!source || typeof source.serialize !== "function") return;
      const data = source.serialize().data || EMPTY;
      const features = Array.isArray(data.features) ? data.features : [];
      let changed = false;
      const updated = {
        ...data,
        features: features.map((feature) => {
          const properties = feature.properties || {};
          const state = byRoute.get(String(properties.route_id));
          if (!state) return feature;
          changed = true;
          return {
            ...feature,
            properties: {
              ...properties,
              dimmed: !!state.dimmed,
              route_visible: !!state.visible,
              route_active: !!state.active,
              route_editable: !!state.editable,
              route_locked: !!state.locked,
              line_width: properties.shared_route_count === undefined
                ? properties.line_width
                : routeLineWidth(properties.shared_route_count, !!state.active),
            },
          };
        }),
      };
      if (changed) source.setData(updated);
    });
    return true;
  }

  function updateRouteSelection(routeId) {
    if (!layersAreReady()) return false;
    const selected = routeId == null ? null : String(routeId);
    ["gtfs-shapes", "gtfs-stops", "gtfs-shape-points"].forEach((sourceId) => {
      const source = map.getSource(sourceId);
      if (!source || typeof source.serialize !== "function") return;
      const data = source.serialize().data || EMPTY;
      const features = Array.isArray(data.features) ? data.features : [];
      source.setData({...data, features: features.map((feature) => ({
        ...feature,
        properties: {...(feature.properties || {}), route_selected: String((feature.properties || {}).route_id) === selected},
      }))});
    });
    return true;
  }

  function flushPendingReplacement() {
    if (!pendingReplacement) return;
    const {payload, fit, resetSelection, generationId} = pendingReplacement;
    if (applyReplacement(payload, fit, resetSelection, generationId)) pendingReplacement = null;
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
    map.on("render", () => {
      if (lastApplyTimings && lastApplyTimings.apply_serial === applySerial) {
        lastApplyTimings.render_final = performance.now();
      }
    });
    map.on("error", () => reportMapError("map"));
    map.on("load", () => {
      mapLoaded = true;
      installTransitLayers();
      map.on("click", "gtfs-stops-circle", (event) => {
        if (stopDrag) return;
        const feature = event.features[0];
        const id = feature.properties && feature.properties.id;
        if (typeof id !== "string") return;
        selectedStopId = id;
        updateSelection();
        const popup = new maplibregl.Popup();
        popup.setLngLat(event.lngLat).setDOMContent(popupText(feature)).addTo(map);
        const bridge = window.GTFSExplorerMapBridge;
        if (bridge) bridge.featureClicked({kind: "stop", id});
      });
      map.on("mouseenter", "gtfs-stops-circle", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "gtfs-stops-circle", () => { map.getCanvas().style.cursor = ""; });
      map.on("mousedown", "gtfs-stops-circle", (event) => {
        // El modo y Shift son dos confirmaciones visibles contra arrastres accidentales.
        if (editMode !== "EDIT_ROUTE" || !event.originalEvent || !event.originalEvent.shiftKey) return;
        const feature = event.features && event.features[0];
        const properties = feature && feature.properties;
        const id = properties && properties.id;
        if (typeof id !== "string") return;
        stopDrag = {id, route_id: typeof properties.route_id === "string" ? properties.route_id : null};
        if (map.dragPan && typeof map.dragPan.disable === "function") map.dragPan.disable();
        if (event.preventDefault) event.preventDefault();
      });
      map.on("mousemove", (event) => {
        if (!stopDrag || !event.lngLat) return;
        updatePointSource("gtfs-stops", stopDrag.id, event.lngLat.lng, event.lngLat.lat);
      });
      map.on("mouseup", (event) => {
        if (!stopDrag || !event.lngLat) return;
        const current = stopDrag;
        stopDrag = null;
        if (map.dragPan && typeof map.dragPan.enable === "function") map.dragPan.enable();
        reportEdit({
          action: "drag_end", entity_type: "stop", entity_id: current.id,
          route_id: current.route_id, longitude: event.lngLat.lng, latitude: event.lngLat.lat,
        });
      });
      map.on("click", "gtfs-shape-points-circle", (event) => {
        if (editMode === "REDRAW_SEGMENT" && vertexAction === "delete") {
          const feature = event.features && event.features[0];
          const properties = feature && feature.properties;
          if (properties && typeof properties.id === "string") {
            vertexAction = null;
            reportEdit({action: "delete_vertex", entity_type: "shape_vertex", entity_id: properties.id,
              shape_id: properties.shape_id || null, route_id: properties.route_id || null});
          }
          return;
        }
        if (editMode !== "SELECT_SEGMENT") return;
        const feature = event.features && event.features[0];
        const properties = feature && feature.properties;
        const id = properties && properties.id;
        if (typeof id !== "string") return;
        reportEdit({action: "select", entity_type: "shape_vertex", entity_id: id,
          shape_id: properties.shape_id || null, route_id: properties.route_id || null,
          position: Number.isInteger(properties.position) ? properties.position : null});
      });
      map.on("click", "gtfs-shapes-line", (event) => {
        if (editMode !== "REDRAW_SEGMENT" || vertexAction !== "add" || !event.lngLat) return;
        const feature = event.features && event.features[0];
        const properties = feature && feature.properties;
        const coordinates = feature && feature.geometry && feature.geometry.coordinates;
        const position = nearestSegment(coordinates, event.lngLat);
        if (!properties || typeof properties.shape_id !== "string" || position === null) return;
        vertexAction = null;
        reportEdit({action: "add_vertex", entity_type: "shape_vertex", entity_id: properties.shape_id,
          route_id: properties.route_id || null, position, longitude: event.lngLat.lng, latitude: event.lngLat.lat});
      });
      map.on("mousedown", "gtfs-shape-points-circle", (event) => {
        if (editMode !== "EDIT_ROUTE" && editMode !== "REDRAW_SEGMENT") return;
        const feature = event.features && event.features[0];
        const properties = feature && feature.properties;
        const id = properties && properties.id;
        if (typeof id !== "string") return;
        vertexDrag = {id, shape_id: properties.shape_id, route_id: properties.route_id || null};
        if (map.dragPan && typeof map.dragPan.disable === "function") map.dragPan.disable();
        if (event.preventDefault) event.preventDefault();
      });
      map.on("mousemove", (event) => {
        if (!vertexDrag || !event.lngLat) return;
        updatePointSource("gtfs-shape-points", vertexDrag.id, event.lngLat.lng, event.lngLat.lat);
      });
      map.on("mouseup", (event) => {
        if (!vertexDrag || !event.lngLat) return;
        const current = vertexDrag;
        vertexDrag = null;
        if (map.dragPan && typeof map.dragPan.enable === "function") map.dragPan.enable();
        reportEdit({action: "drag_end", entity_type: "shape_vertex", entity_id: current.id,
          shape_id: current.shape_id, route_id: current.route_id,
          longitude: event.lngLat.lng, latitude: event.lngLat.lat});
      });
      map.on("moveend", () => {
        const bounds = map.getBounds();
        viewportRequest += 1;
        // El contador permite a Qt desechar cualquier respuesta anterior al último pan/zoom.
        const bridge = window.GTFSExplorerMapBridge;
        if (bridge) bridge.viewportChanged({request: viewportRequest, west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth(), zoom: map.getZoom()});
      });
      map.on("idle", () => {
        const settledSerial = applySerial;
        if (applySerial) idleSerial = applySerial;
        reportMapReadyWhenBridgeIsAvailable();
        if (settledSerial) reportPerformanceWhenIdle(settledSerial);
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
    replace: function (payload, fit = true, resetSelection = true, generationId = null) {
      latestReplacement = {payload, fit, resetSelection, generationId};
      if (!styleTransitionPending && applyReplacement(payload, fit, resetSelection, generationId)) {
        pendingReplacement = null;
        return true;
      }
      // Conserva únicamente el estado visual más reciente. El evento idle lo
      // aplicará cuando MapLibre termine de publicar el estilo y sus fuentes.
      pendingReplacement = {payload, fit, resetSelection, generationId};
      return false;
    },
    getPerformance: function () {
      return {apply: lastApplyTimings, idle_serial: idleSerial};
    },
    updateRouteStates: updateRouteStates,
    updateRouteSelection: updateRouteSelection,
    setEditMode: setEditMode,
    setVertexAction: setVertexAction,
    setUiTexts: setUiTexts,
    resize: function () { if (map) map.resize(); },
    centerStop: centerStop,
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

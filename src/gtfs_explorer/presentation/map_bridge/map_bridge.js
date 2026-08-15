/* Protocolo local v1 del mapa. No expone filesystem, SQL ni acceso a red. */
(function () {
  "use strict";

  const VERSION = 1;
  const MAX_MESSAGE_BYTES = 16 * 1024;
  const MAX_PENDING_COMMANDS = 32;
  let channelCreated = false;
  let bridge = null;
  let sequence = 0;
  let mapReady = false;
  const pending = [];

  function sizeIsAllowed(message) {
    return new TextEncoder().encode(message).length <= MAX_MESSAGE_BYTES;
  }

  function report(event, payload) {
    const message = JSON.stringify({version: VERSION, type: "event", event, sequence: sequence++, payload});
    if (!sizeIsAllowed(message)) return false;
    bridge.receive(message);
    return true;
  }

  function dispatchCommand(serialized) {
    if (!sizeIsAllowed(serialized)) return;
    let command;
    try { command = JSON.parse(serialized); } catch (_) { return; }
    if (command.version !== VERSION || command.type !== "command" || command.command !== "navigate") return;
    const payload = command.payload;
    if (!payload || !Number.isFinite(payload.longitude) || !Number.isFinite(payload.latitude) || !Number.isFinite(payload.zoom)) return;
    if (!mapReady) {
      if (pending.length < MAX_PENDING_COMMANDS) pending.push(serialized);
      return;
    }
    window.dispatchEvent(new CustomEvent("gtfs-explorer-map-command", {detail: command}));
  }

  function flushPending() {
    while (pending.length) dispatchCommand(pending.shift());
  }

  function create(channel) {
    if (channelCreated) return;
    channelCreated = true;
    bridge = channel.objects.mapBridge;
    bridge.command_available.connect(dispatchCommand);
    window.GTFSExplorerMapBridge = {
      mapReady: function () {
        if (mapReady) return false;
        mapReady = true;
        const accepted = report("mapReady", {});
        flushPending();
        return accepted;
      },
      featureClicked: function (payload) { return mapReady && report("featureClicked", payload); },
      viewportChanged: function (payload) { return mapReady && report("viewportChanged", payload); },
      mapError: function (payload) { return report("mapError", payload); },
    };
    // QWebChannel se inicializa de forma asíncrona. Las capas pueden haber
    // terminado de cargar antes; notificamos explícitamente que ya es seguro
    // informar de mapReady y enviar eventos hacia Qt.
    window.dispatchEvent(new Event("gtfs-explorer-map-bridge-ready"));
  }

  // Una única creación de QWebChannel por página, protegida contra cargas repetidas.
  new QWebChannel(qt.webChannelTransport, create);
}());

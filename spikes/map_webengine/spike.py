"""Spike aislado para comprobar la frontera Qt WebEngine/recursos locales.

No forma parte de la aplicación. Se ejecuta en un proceso independiente porque
los esquemas de WebEngine deben registrarse antes de crear QApplication.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, QUrl, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineUrlRequestInterceptor,
    QWebEngineUrlRequestJob,
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

SCHEME_NAME = b"gtfs-spike"
ORIGIN = "gtfs-spike://map"
ASSETS = Path(__file__).with_name("assets")
PMTILES_BYTES = b"PMTiles spike fixture: local ranges are deliberately requested."


def register_scheme() -> None:
    """Registra un esquema seguro antes de instanciar QApplication."""
    scheme = QWebEngineUrlScheme(SCHEME_NAME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)


@dataclass
class Evidence:
    bridge_events: list[str] = field(default_factory=list)
    requested_ranges: list[str] = field(default_factory=list)
    external_requests: list[str] = field(default_factory=list)
    fetch_status: int | None = None
    fetch_content_range: str | None = None
    load_ok: bool = False
    console_messages: list[str] = field(default_factory=list)


class Bridge(QObject):
    def __init__(self, evidence: Evidence, done: Callable[[], None]) -> None:
        super().__init__()
        self._evidence = evidence
        self._done = done

    @Slot(str)
    def report(self, value: str) -> None:
        event = json.loads(value)
        kind = event["kind"]
        if kind == "feature-clicked":
            self._evidence.bridge_events.append(event["feature"])
        elif kind == "range-result":
            self._evidence.fetch_status = event["status"]
            self._evidence.fetch_content_range = event["contentRange"]
            self._done()


class LocalHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, evidence: Evidence) -> None:
        super().__init__()
        self._evidence = evidence
        self._buffers: list[QBuffer] = []

    def _reply(self, job: QWebEngineUrlRequestJob, mime_type: bytes, content: bytes) -> None:
        buffer = QBuffer(self)
        buffer.setData(QByteArray(content))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._buffers.append(buffer)
        job.reply(mime_type, buffer)

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802 - API Qt
        path = job.requestUrl().path()
        if path == "/tiles/sample.pmtiles":
            headers = {bytes(key).lower(): bytes(value) for key, value in job.requestHeaders()}
            range_header = headers.get(b"range", b"").decode("ascii")
            if range_header:
                self._evidence.requested_ranges.append(range_header)
            # QWebEngineUrlRequestJob no expone un método para emitir HTTP 206.
            # La cabecera por sí sola no transforma el status 200 de reply().
            job.setAdditionalResponseHeaders(
                [(b"Accept-Ranges", b"bytes"), (b"Content-Range", b"bytes 0-7/58")]
            )
            self._reply(job, b"application/vnd.pmtiles", PMTILES_BYTES[:8])
            return
        if path == "/index.html":
            content = (ASSETS / "index.html").read_bytes()
            self._reply(job, b"text/html", content)
            return
        job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)


class NetworkMonitor(QWebEngineUrlRequestInterceptor):
    def __init__(self, evidence: Evidence) -> None:
        super().__init__()
        self._evidence = evidence

    def interceptRequest(self, info: object) -> None:  # noqa: N802 - API Qt
        url = info.requestUrl().toString()  # type: ignore[attr-defined]
        if not url.startswith(ORIGIN) and not url.startswith("qrc:///"):
            self._evidence.external_requests.append(url)
            info.block(True)  # type: ignore[attr-defined]


class Page(QWebEnginePage):
    def __init__(self, evidence: Evidence) -> None:
        super().__init__()
        self._evidence = evidence

    def javaScriptConsoleMessage(
        self, level: QWebEnginePage.JavaScriptConsoleMessageLevel, message: str, line: int, source: str
    ) -> None:  # noqa: N802 - API Qt
        self._evidence.console_messages.append(f"{level.name}:{line}:{message}:{source}")


def run() -> Evidence:
    """Ejecuta el smoke y devuelve evidencia serializable."""
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    app = QApplication(sys.argv)
    evidence = Evidence()
    view = QWebEngineView()
    view.setPage(Page(evidence))
    handler = LocalHandler(evidence)
    profile = view.page().profile()
    profile.installUrlSchemeHandler(SCHEME_NAME, handler)
    profile.setUrlRequestInterceptor(NetworkMonitor(evidence))

    def finish() -> None:
        if evidence.fetch_status is None:
            return
        view.close()
        app.quit()

    channel = QWebChannel(view.page())
    channel.registerObject("spikeBridge", Bridge(evidence, finish))
    view.page().setWebChannel(channel)
    view.loadFinished.connect(lambda ok: setattr(evidence, "load_ok", ok))
    QTimer.singleShot(2_000, app.quit)
    view.load(QUrl(f"{ORIGIN}/index.html"))
    app.exec()
    return evidence


if __name__ == "__main__":
    register_scheme()
    print(json.dumps(asdict(run()), sort_keys=True), flush=True)
    # Chromium puede mantener procesos auxiliares brevemente tras el cierre de
    # QApplication; el spike no deja recursos persistentes y debe terminar de
    # forma determinista para que la evidencia sea automatizable.
    os._exit(0)

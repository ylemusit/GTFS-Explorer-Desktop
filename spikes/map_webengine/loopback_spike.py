"""Spike aislado para validar Qt WebChannel y rangos PMTiles por loopback.

No forma parte todavía de la aplicación. El servidor solo enlaza 127.0.0.1,
usa un token efímero en cada ruta y expone tres recursos cerrados.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import struct
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).with_name("assets")
_RANGE = re.compile(r"bytes=(?P<start>\d+)-(?P<end>\d*)\Z")


def _minimal_pmtiles() -> bytes:
    """Crea un PMTiles v3 válido con una tesela PNG transparente en z0/0/0."""
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
        "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
    )
    root = bytes((1, 0, 1, len(png), 1))
    metadata = b"{}"
    header = bytearray(127)
    header[:7] = b"PMTiles"
    header[7] = 3
    sections = (
        (8, 127),
        (16, len(root)),
        (24, 127 + len(root)),
        (32, len(metadata)),
        (40, 127 + len(root) + len(metadata)),
        (48, 0),
        (56, 127 + len(root) + len(metadata)),
        (64, len(png)),
        (72, 1),
        (80, 1),
        (88, 1),
    )
    for offset, value in sections:
        struct.pack_into("<Q", header, offset, value)
    header[96:102] = bytes((1, 1, 1, 2, 0, 0))
    struct.pack_into("<i", header, 102, -1800000000)
    struct.pack_into("<i", header, 106, -850000000)
    struct.pack_into("<i", header, 110, 1800000000)
    struct.pack_into("<i", header, 114, 850000000)
    header[118] = 0
    struct.pack_into("<i", header, 119, 0)
    struct.pack_into("<i", header, 123, 0)
    return bytes(header) + root + metadata + png


PMTILES_BYTES = _minimal_pmtiles()


@dataclass
class Evidence:
    bridge_events: list[str] = field(default_factory=list)
    requested_ranges: list[str] = field(default_factory=list)
    external_requests: list[str] = field(default_factory=list)
    fetch_status: int | None = None
    fetch_content_range: str | None = None
    fetched_bytes: int | None = None
    map_loaded: bool = False
    pmtiles_spec_version: int | None = None
    map_errors: list[str] = field(default_factory=list)
    bridge_roundtrip: str | None = None
    rendered_kinds: list[str] = field(default_factory=list)
    load_ok: bool = False
    console_messages: list[str] = field(default_factory=list)
    bound_to_loopback: bool = False
    token_protected: bool = False


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, token: str, evidence: Evidence, pmtiles_bytes: bytes) -> None:
        self.token = token
        self.evidence = evidence
        self.pmtiles_bytes = pmtiles_bytes
        super().__init__(("127.0.0.1", 0), _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server: _LoopbackServer

    def log_message(self, format: str, *args: object) -> None:
        """Evita registrar token, rutas o payloads del usuario."""

    def do_GET(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        self._serve(include_body=True)

    def do_HEAD(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        self._serve(include_body=False)

    def do_POST(self) -> None:  # noqa: N802 - API de BaseHTTPRequestHandler
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def _serve(self, *, include_body: bool) -> None:
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected_host:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        path = urlsplit(self.path).path
        prefix = f"/{self.server.token}/"
        if not path.startswith(prefix):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.server.evidence.token_protected = True
        resource = path.removeprefix(prefix)
        if resource == "index.html":
            self._send_bytes(
                (ASSETS / "loopback_index.html").read_bytes(),
                "text/html; charset=utf-8",
                include_body=include_body,
                extra_headers=(
                    (
                        "Content-Security-Policy",
                        "default-src 'none'; script-src 'self' qrc:; "
                        "connect-src 'self'; style-src 'self'; "
                        "worker-src 'self' blob:; img-src data: blob:",
                    ),
                ),
            )
            return
        if resource in {"map_bundle.js", "map_worker.mjs", "maplibre-gl-shared.mjs"}:
            self._send_bytes(
                (ASSETS / resource).read_bytes(),
                "text/javascript; charset=utf-8",
                include_body=include_body,
            )
            return
        if resource == "sample.pmtiles":
            self._send_pmtiles(include_body=include_body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _send_pmtiles(self, *, include_body: bool) -> None:
        pmtiles_bytes = self.server.pmtiles_bytes
        range_header = self.headers.get("Range")
        if range_header is None:
            self._send_bytes(
                pmtiles_bytes,
                "application/vnd.pmtiles",
                include_body=include_body,
                extra_headers=(("Accept-Ranges", "bytes"),),
            )
            return
        self.server.evidence.requested_ranges.append(range_header)
        match = _RANGE.fullmatch(range_header)
        if match is None:
            self._range_not_satisfiable()
            return
        start = int(match.group("start"))
        end_text = match.group("end")
        end = int(end_text) if end_text else len(PMTILES_BYTES) - 1
        if start >= len(pmtiles_bytes) or end < start:
            self._range_not_satisfiable()
            return
        end = min(end, len(pmtiles_bytes) - 1)
        payload = pmtiles_bytes[start : end + 1]
        content_range = f"bytes {start}-{end}/{len(pmtiles_bytes)}"
        self.server.evidence.fetch_status = HTTPStatus.PARTIAL_CONTENT
        self.server.evidence.fetch_content_range = content_range
        self.server.evidence.fetched_bytes = len(payload)
        self._send_bytes(
            payload,
            "application/vnd.pmtiles",
            status=HTTPStatus.PARTIAL_CONTENT,
            include_body=include_body,
            extra_headers=(
                ("Accept-Ranges", "bytes"),
                ("Content-Range", content_range),
            ),
        )

    def _range_not_satisfiable(self) -> None:
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.send_header("Content-Range", f"bytes */{len(self.server.pmtiles_bytes)}")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_bytes(
        self,
        payload: bytes,
        content_type: str,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        include_body: bool,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        if include_body:
            self.wfile.write(payload)


class LoopbackMapServer:
    """Servidor efímero, sin acceso genérico al filesystem ni red externa."""

    def __init__(
        self,
        evidence: Evidence,
        *,
        token: str | None = None,
        pmtiles_bytes: bytes = PMTILES_BYTES,
    ) -> None:
        self._token = token or secrets.token_urlsafe(24)
        self._server = _LoopbackServer(self._token, evidence, pmtiles_bytes)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    @property
    def entrypoint(self) -> str:
        return f"{self.origin}/{self._token}/index.html"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self) -> LoopbackMapServer:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


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
        elif kind == "map-result":
            self._evidence.map_loaded = event["loaded"]
            self._evidence.pmtiles_spec_version = event["specVersion"]
            self._evidence.bridge_roundtrip = event["roundtrip"]
            self._evidence.rendered_kinds = event["renderedKinds"]
            self._done()
        elif kind == "map-error":
            self._evidence.map_errors.append(event["message"])
        elif kind == "map-failure":
            self._evidence.map_errors.append(event["message"])
            self._done()

    @Slot(str, result=str)
    def echo(self, value: str) -> str:
        return f"python:{value}"


class NetworkMonitor(QWebEngineUrlRequestInterceptor):
    def __init__(self, evidence: Evidence, allowed_origin: str) -> None:
        super().__init__()
        self._evidence = evidence
        self._allowed_origin = allowed_origin

    def interceptRequest(self, info: object) -> None:  # noqa: N802 - API Qt
        url = info.requestUrl().toString()  # type: ignore[attr-defined]
        if not url.startswith(self._allowed_origin + "/") and not url.startswith("qrc:///"):
            self._evidence.external_requests.append(url)
            info.block(True)  # type: ignore[attr-defined]


class Page(QWebEnginePage):
    def __init__(self, evidence: Evidence) -> None:
        super().__init__()
        self._evidence = evidence

    def javaScriptConsoleMessage(
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line: int,
        source: str,
    ) -> None:  # noqa: N802 - API Qt
        self._evidence.console_messages.append(f"{level.name}:{line}:{message}:{source}")


def run(*, corrupt_pmtiles: bool = False) -> Evidence:
    """Ejecuta el smoke WebEngine completo y devuelve evidencia serializable."""
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--use-angle=swiftshader")
    app = QApplication(sys.argv)
    evidence = Evidence(bound_to_loopback=True)
    pmtiles_bytes = b"corrupt-pmtiles" if corrupt_pmtiles else PMTILES_BYTES
    with LoopbackMapServer(evidence, pmtiles_bytes=pmtiles_bytes) as server:
        view = QWebEngineView()
        view.resize(640, 480)
        view.setPage(Page(evidence))
        view.page().setUrlRequestInterceptor(NetworkMonitor(evidence, server.origin))

        def finish() -> None:
            if evidence.fetch_status is None:
                return
            view.close()
            app.quit()

        channel = QWebChannel(view.page())
        bridge = Bridge(evidence, finish)
        channel.registerObject("spikeBridge", bridge)
        view.page().setWebChannel(channel)
        view.loadFinished.connect(lambda ok: setattr(evidence, "load_ok", ok))
        QTimer.singleShot(10_000, app.quit)
        view.load(QUrl(server.entrypoint))
        view.show()
        app.exec()
    return evidence


if __name__ == "__main__":
    result = run(corrupt_pmtiles="--corrupt" in sys.argv)
    print(json.dumps(asdict(result), sort_keys=True), flush=True)
    os._exit(0)

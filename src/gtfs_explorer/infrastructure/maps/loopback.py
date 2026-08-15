"""Servidor efímero para un paquete de mapa ya validado."""

from __future__ import annotations

import re
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from gtfs_explorer.infrastructure.maps.package import MapPackage

_RANGE = re.compile(r"bytes=(?P<start>\d+)-(?P<end>\d*)\Z")


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, package: MapPackage, token: str) -> None:
        self.package, self.token = package, token
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self._serve(True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(False)

    def do_OPTIONS(self) -> None:  # noqa: N802
        relative = self._allowed_path()
        origin = self.headers.get("Origin")
        if relative is None or origin not in {"null", "file://"}:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve(self, body: bool) -> None:
        relative = self._allowed_path()
        if relative is None:
            return
        file_path = self.server.package.root / relative
        payload = file_path.read_bytes()
        if file_path == self.server.package.basemap:
            self._pmtiles(payload, body)
            return
        content_type = (
            "application/json; charset=utf-8"
            if file_path.suffix == ".json"
            else "application/octet-stream"
        )
        self._send(payload, content_type, body)

    def _allowed_path(self) -> PurePosixPath | None:
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(HTTPStatus.FORBIDDEN)
            return None
        path = urlsplit(self.path).path
        prefix = f"/{self.server.token}/"
        if not path.startswith(prefix):
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        relative = PurePosixPath(path.removeprefix(prefix))
        allowed = set(self.server.package.files)
        if relative not in allowed:
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        return relative

    def _pmtiles(self, payload: bytes, body: bool) -> None:
        requested = self.headers.get("Range")
        if requested is None:
            self._send(payload, "application/vnd.pmtiles", body, (("Accept-Ranges", "bytes"),))
            return
        match = _RANGE.fullmatch(requested)
        if match is None:
            self._unsatisfiable(len(payload))
            return
        start, end_text = int(match.group("start")), match.group("end")
        end = int(end_text) if end_text else len(payload) - 1
        if start >= len(payload) or end < start:
            self._unsatisfiable(len(payload))
            return
        end = min(end, len(payload) - 1)
        self._send(
            payload[start : end + 1],
            "application/vnd.pmtiles",
            body,
            (("Accept-Ranges", "bytes"), ("Content-Range", f"bytes {start}-{end}/{len(payload)}")),
            HTTPStatus.PARTIAL_CONTENT,
        )

    def _unsatisfiable(self, total: int) -> None:
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.send_header("Content-Range", f"bytes */{total}")
        self.send_header("Content-Length", "0")
        self._send_cors_header()
        self.end_headers()

    def _send(
        self,
        payload: bytes,
        content_type: str,
        body: bool,
        headers: tuple[tuple[str, str], ...] = (),
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._send_cors_header()
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if body:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                # WebEngine cancela rangos que ya no necesita al mover/cerrar
                # el mapa. Es un cierre normal del cliente, no un fallo local.
                return

    def _send_cors_header(self) -> None:
        origin = self.headers.get("Origin")
        if origin in {"null", "file://"}:
            self.send_header("Access-Control-Allow-Origin", origin)


class MapPackageServer:
    """Expone únicamente los ficheros comprobados del paquete seleccionado."""

    def __init__(self, package: MapPackage) -> None:
        self._server = _Server(package, secrets.token_urlsafe(24))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def url_for(self, relative: PurePosixPath) -> str:
        return f"{self.origin}/{self._server.token}/{relative.as_posix()}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def __enter__(self) -> MapPackageServer:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

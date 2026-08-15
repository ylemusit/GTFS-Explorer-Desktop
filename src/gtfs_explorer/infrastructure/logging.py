"""Diagnóstico local con redacción por defecto; nunca envía datos fuera del equipo."""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile

_ALLOWED_CONTEXT = frozenset({"event", "job_id", "project_id", "feed_id", "error_code"})
_SENSITIVE = re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*[^\s,]+")


@dataclass(frozen=True)
class DiagnosticPreview:
    """Contenido local que el usuario verá antes de exportar un diagnóstico."""

    files: tuple[Path, ...]

    @property
    def total_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.files)

    def summary(self) -> str:
        names = ", ".join(path.name for path in self.files) or "ningún archivo"
        return f"Se exportarán: {names}. Tamaño total: {self.total_bytes} bytes."


def safe_context(context: Mapping[str, object]) -> dict[str, str]:
    """Conserva solo IDs operativos; descarta filas, rutas y payloads del feed."""
    return {key: str(value) for key, value in context.items() if key in _ALLOWED_CONTEXT}


def redact(value: str) -> str:
    """Evita que secretos triviales alcancen el diagnóstico local."""
    return _SENSITIVE.sub("[REDACTED]", value)


def configure_logging(directory: Path, *, debug: bool = False) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gtfs_explorer")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    for existing_handler in logger.handlers:
        existing_handler.close()
    logger.handlers.clear()
    handler = RotatingFileHandler(
        directory / "gtfs-explorer.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def preview_diagnostics(directory: Path) -> DiagnosticPreview:
    """Enumera exclusivamente los logs rotatorios propios, nunca feeds ni proyectos."""
    files = tuple(
        path
        for path in sorted(directory.glob("gtfs-explorer.log*"))
        if path.is_file()
        and path.name
        in {
            "gtfs-explorer.log",
            "gtfs-explorer.log.1",
            "gtfs-explorer.log.2",
            "gtfs-explorer.log.3",
        }
    )
    return DiagnosticPreview(files)


def export_diagnostics(preview: DiagnosticPreview, destination: Path) -> Path:
    """Publica un ZIP local de los archivos previamente confirmados por el usuario."""
    if destination.suffix.casefold() != ".zip":
        raise ValueError("El diagnóstico debe exportarse como un archivo ZIP.")
    if not preview.files:
        raise ValueError("No hay logs de diagnóstico para exportar.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in preview.files:
                archive.write(path, arcname=path.name)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def install_exception_handler(logger: logging.Logger, *, debug: bool = False) -> None:
    previous = sys.excepthook

    def handle(
        exception_type: type[BaseException], value: BaseException, traceback: object
    ) -> None:
        logger.error(
            "UNHANDLED_EXCEPTION error=%s",
            redact(str(value) or exception_type.__name__),
            exc_info=debug,
        )
        if debug:
            previous(exception_type, value, traceback)  # type: ignore[arg-type]

    sys.excepthook = handle

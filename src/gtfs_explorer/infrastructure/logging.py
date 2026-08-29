"""Diagnóstico local con redacción por defecto; nunca envía datos fuera del equipo."""

from __future__ import annotations

import logging
import re
import sys
import traceback as traceback_module
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from gtfs_explorer.product import IDENTITY, runtime_architecture, runtime_build_id

_ALLOWED_CONTEXT = frozenset(
    {
        "event",
        "operation",
        "job_id",
        "project_id",
        "project_name",
        "feed_id",
        "error_code",
        "app_state",
        "product",
        "version",
        "build_id",
        "gtfs_spec_revision",
        "architecture",
    }
)
_SENSITIVE = re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*[=:]\s*[^\s,]+")
_TOKEN_LIKE = re.compile(r"(?i)\b[A-Za-z0-9_-]*(?:token|secret)[A-Za-z0-9_-]*\b")
_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[a-z]:[\\/][^\s,;]+|/Users/[^\s,;]+|/home/[^\s,;]+)"
)
_TRACEBACK_FILE = re.compile(r'(?m)^(\s*File ")([^"\r\n]+)("\s*, line \d+, in .*)$')


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
    """Conserva contexto operativo y elimina rutas/payloads del feed."""
    return {
        key: sanitize_text(str(value)) for key, value in context.items() if key in _ALLOWED_CONTEXT
    }


def redact(value: str) -> str:
    """Evita que secretos triviales alcancen el diagnóstico local."""
    redacted = _SENSITIVE.sub("[REDACTED]", value)
    return _TOKEN_LIKE.sub("[REDACTED]", redacted)


def sanitize_text(value: str) -> str:
    """Redacta secretos y rutas absolutas sin volcar datos del workspace."""
    return _ABSOLUTE_PATH.sub("[PATH]", redact(value))


def sanitize_traceback(value: str) -> str:
    """Conserva el archivo de cada frame, pero nunca sus directorios."""

    def replace_frame(match: re.Match[str]) -> str:
        path = match.group(2)
        basename = re.split(r"[\\/]", path)[-1]
        return f"{match.group(1)}{basename}{match.group(3)}"

    return sanitize_text(_TRACEBACK_FILE.sub(replace_frame, value))


def diagnostic_identity_context() -> dict[str, str]:
    """Identidad segura que acompaña a cualquier error de aplicación."""
    return {
        "product": IDENTITY.name,
        "version": IDENTITY.version,
        "build_id": runtime_build_id(),
        "gtfs_spec_revision": IDENTITY.gtfs_spec_revision,
        "architecture": runtime_architecture(),
    }


def capture_application_error(
    logger: logging.Logger,
    *,
    error_code: str,
    operation: str,
    exception: BaseException,
    context: Mapping[str, object] | None = None,
) -> None:
    """Registra una excepción UI completa mientras su traceback sigue disponible."""
    payload: dict[str, object] = {key: str(value) for key, value in (context or {}).items()}
    payload.update(diagnostic_identity_context())
    payload.update({"error_code": error_code, "operation": operation})
    formatted_traceback = "".join(traceback_module.format_exception(exception))
    logger.error(
        "APPLICATION_ERROR code=%s context=%s exception_type=%s exception_message=%s\ntraceback=%s",
        error_code,
        safe_context(payload),
        type(exception).__name__,
        sanitize_text(str(exception) or type(exception).__name__),
        sanitize_traceback(formatted_traceback),
    )


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

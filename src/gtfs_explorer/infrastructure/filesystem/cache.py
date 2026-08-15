"""Caché local descartable con claves estables y publicación atómica."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CACHE_FORMAT_VERSION = 1


@dataclass(frozen=True)
class CacheKey:
    """Identifica un derivado por el feed, consulta, selección y opciones."""

    feed_hash: str
    query_version: str
    selection: Any
    options: Any

    def to_dict(self) -> dict[str, object]:
        return {
            "feed_hash": self.feed_hash,
            "query_version": self.query_version,
            "selection": self.selection,
            "options": self.options,
        }


class CacheStore:
    """Almacena derivados sin convertir la caché en fuente de verdad."""

    def __init__(self, directory: Path, *, format_version: int = CACHE_FORMAT_VERSION) -> None:
        if format_version < 1:
            raise ValueError("La versión de formato de caché debe ser positiva.")
        self.directory = directory
        self._format_version = format_version

    def read(self, key: CacheKey) -> bytes | None:
        """Devuelve un derivado completo o ignora una entrada inválida/antigua."""
        path = self._path_for(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("version") != self._format_version
                or payload.get("key") != key.to_dict()
            ):
                self._discard(path)
                return None
            encoded_value = payload.get("value")
            if not isinstance(encoded_value, str):
                self._discard(path)
                return None
            return base64.b64decode(encoded_value.encode("ascii"), validate=True)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            self._discard(path)
            return None

    def write(self, key: CacheKey, value: bytes) -> None:
        """Publica el derivado íntegro en un único reemplazo atómico."""
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self._path_for(key)
        payload = {
            "version": self._format_version,
            "key": key.to_dict(),
            "value": base64.b64encode(value).decode("ascii"),
        }
        descriptor = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, prefix=".cache-", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(descriptor)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
        finally:
            if temporary_path is not None:
                self._discard(temporary_path)

    def clear(self) -> None:
        """Borra solo derivados publicados, nunca la base DuckDB del proyecto."""
        if not self.directory.exists():
            return
        for path in self.directory.glob("*.cache.json"):
            self._discard(path)

    def _path_for(self, key: CacheKey) -> Path:
        try:
            identity = json.dumps(key.to_dict(), sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ValueError("La clave de caché debe ser serializable como JSON.") from error
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.cache.json"

    @staticmethod
    def _discard(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Una entrada que no puede limpiarse sigue sin poder considerarse válida.
            pass

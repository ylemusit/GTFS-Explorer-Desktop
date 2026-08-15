"""Escritura local atómica para todos los exportadores posteriores."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile

from gtfs_explorer.domain.exporting import (
    ExportCancelled,
    ExportDestinationError,
    ExportDestinationExistsError,
    ExportError,
    ExportManifest,
)

CancellationCheck = Callable[[], bool]
FreeSpaceCheck = Callable[[Path, int], bool]


def _has_free_space(directory: Path, required_bytes: int) -> bool:
    return shutil.disk_usage(directory).free >= required_bytes


class AtomicOutputWriter:
    """Publica artefactos y su manifiesto sin archivos finales parciales."""

    def __init__(
        self,
        *,
        protected_roots: Iterable[Path] = (),
        has_free_space: FreeSpaceCheck = _has_free_space,
    ) -> None:
        self._protected_roots = tuple(root.resolve() for root in protected_roots)
        self._has_free_space = has_free_space

    def write(
        self,
        destination: Path,
        chunks: Iterable[bytes],
        *,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
        manifest_metadata: Mapping[str, str | bool] | None = None,
    ) -> ExportManifest:
        """Escribe ``chunks`` y un manifiesto lateral en el directorio de destino.

        El temporal vive junto al resultado, de modo que la publicación mediante
        ``replace`` no cruza volúmenes. Una cancelación o fallo elimina temporales
        y conserva cualquier archivo final que ya existiera.
        """
        final_path = self._validate_destination(destination)
        manifest_path = final_path.with_name(f"{final_path.name}.manifest.json")
        self._ensure_overwrite_is_explicit(final_path, manifest_path, overwrite)
        self._raise_if_cancelled(is_cancelled)

        artifact_temporary_path = self._new_temporary_path(final_path.parent, final_path.name)
        artifact_temporary: Path | None = artifact_temporary_path
        manifest_temporary: Path | None = None
        try:
            sha256, size_bytes = self._write_temporary(
                artifact_temporary_path, chunks, final_path.parent, is_cancelled
            )
            manifest = ExportManifest(
                artifact_name=final_path.name,
                sha256=sha256,
                size_bytes=size_bytes,
                manifest_name=manifest_path.name,
                metadata=dict(manifest_metadata or {}),
            )
            manifest_temporary = self._new_temporary_path(final_path.parent, manifest_path.name)
            payload = (json.dumps(_manifest_payload(manifest), sort_keys=True) + "\n").encode(
                "utf-8"
            )
            self._write_temporary(manifest_temporary, (payload,), final_path.parent, is_cancelled)
            self._raise_if_cancelled(is_cancelled)
            self._publish(artifact_temporary_path, final_path, overwrite)
            artifact_temporary = None
            self._publish(manifest_temporary, manifest_path, overwrite)
            manifest_temporary = None
            return manifest
        except OSError as error:
            raise ExportError("No se ha podido escribir la salida de exportación.") from error
        finally:
            _remove_if_present(artifact_temporary)
            _remove_if_present(manifest_temporary)

    def _validate_destination(self, destination: Path) -> Path:
        if destination.name in {"", ".", ".."}:
            raise ExportDestinationError("La exportación requiere un nombre de archivo válido.")
        if destination.exists() and destination.is_dir():
            raise ExportDestinationError("El destino de exportación no puede ser una carpeta.")
        parent = destination.parent.resolve()
        if not parent.is_dir():
            raise ExportDestinationError("La carpeta de destino no existe.")
        final_path = (parent / destination.name).resolve()
        if final_path.parent != parent:
            raise ExportDestinationError("El nombre de destino no puede salir de su carpeta.")
        if any(_is_within(final_path, root) for root in self._protected_roots):
            raise ExportDestinationError("El destino está dentro de una ruta interna protegida.")
        return final_path

    @staticmethod
    def _ensure_overwrite_is_explicit(
        final_path: Path, manifest_path: Path, overwrite: bool
    ) -> None:
        if not overwrite and (final_path.exists() or manifest_path.exists()):
            raise ExportDestinationExistsError(
                "El destino o su manifiesto ya existe; confirme explícitamente la sobrescritura."
            )

    def _write_temporary(
        self,
        temporary_path: Path,
        chunks: Iterable[bytes],
        directory: Path,
        is_cancelled: CancellationCheck,
    ) -> tuple[str, int]:
        digest = hashlib.sha256()
        size_bytes = 0
        with temporary_path.open("r+b") as output:
            for chunk in chunks:
                self._raise_if_cancelled(is_cancelled)
                if not isinstance(chunk, bytes):
                    raise TypeError("Los fragmentos de exportación deben ser bytes.")
                if not self._has_free_space(directory, len(chunk)):
                    raise ExportError("El espacio libre se agotó durante la exportación.")
                output.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        return digest.hexdigest(), size_bytes

    @staticmethod
    def _new_temporary_path(directory: Path, prefix: str) -> Path:
        with NamedTemporaryFile(
            prefix=f".{prefix}.", suffix=".tmp", dir=directory, delete=False
        ) as file:
            return Path(file.name)

    @staticmethod
    def _publish(temporary_path: Path, final_path: Path, overwrite: bool) -> None:
        if not overwrite and final_path.exists():
            raise ExportDestinationExistsError(
                "El destino apareció durante la exportación; no se ha sobrescrito."
            )
        os.replace(temporary_path, final_path)

    @staticmethod
    def _raise_if_cancelled(is_cancelled: CancellationCheck) -> None:
        if is_cancelled():
            raise ExportCancelled("La exportación se ha cancelado.")


def _manifest_payload(manifest: ExportManifest) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_name": manifest.artifact_name,
        "schema_version": manifest.schema_version,
        "sha256": manifest.sha256,
        "size_bytes": manifest.size_bytes,
    }
    if manifest.metadata:
        payload["metadata"] = dict(sorted(manifest.metadata.items()))
    return payload


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _remove_if_present(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass

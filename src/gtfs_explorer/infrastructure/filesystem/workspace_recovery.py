"""Operaciones confinadas para recuperar temporales de un workspace."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class WorkspaceAction:
    """Una acción de cuarentena o limpieza con su objetivo absoluto exacto."""

    kind: str
    target: Path


class WorkspaceRecovery:
    """Mueve temporales huérfanos a cuarentena y los borra solo bajo confirmación."""

    def __init__(self, temporary_directory: Path) -> None:
        self._temporary_directory = temporary_directory
        self._quarantine_directory = temporary_directory / "quarantine"

    def quarantine_import_temporary_directories(self) -> tuple[WorkspaceAction, ...]:
        """Aísla directorios ``import-*`` que pertenecen al temporal del proyecto."""
        if not self._temporary_directory.is_dir():
            return ()
        actions: list[WorkspaceAction] = []
        for candidate in self._temporary_directory.glob("import-*"):
            target = self._verified_child(candidate, self._temporary_directory)
            if target is None or not target.is_dir():
                continue
            self._quarantine_directory.mkdir(parents=True, exist_ok=True)
            destination = self._quarantine_directory / f"{target.name}-{uuid4().hex}"
            target.rename(destination)
            actions.append(WorkspaceAction("QUARANTINED", destination.resolve()))
        return tuple(actions)

    def cleanup_quarantine(self, *, confirmed: bool) -> tuple[WorkspaceAction, ...]:
        """Elimina cuarentenas verificadas únicamente tras confirmación del llamador."""
        if not confirmed or not self._quarantine_directory.is_dir():
            return ()
        actions: list[WorkspaceAction] = []
        for candidate in self._quarantine_directory.iterdir():
            target = self._verified_child(candidate, self._quarantine_directory)
            if target is None or not target.is_dir():
                continue
            shutil.rmtree(target)
            actions.append(WorkspaceAction("DELETED", target))
        return tuple(actions)

    @staticmethod
    def _verified_child(candidate: Path, parent: Path) -> Path | None:
        """Acepta solo hijos reales del directorio controlado, nunca enlaces que escapen."""
        resolved_parent = parent.resolve()
        try:
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(resolved_parent)
        except (OSError, ValueError):
            return None
        if resolved_candidate.parent != resolved_parent:
            return None
        return resolved_candidate

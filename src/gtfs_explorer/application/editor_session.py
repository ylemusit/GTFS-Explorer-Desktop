"""Caso de uso que expone el borrador del editor a la UI sin exponer SQL."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from gtfs_explorer.application.commands.open_project import OpenedProject, OpenProject
from gtfs_explorer.domain.changesets import (
    EditorCommand,
    ImpactAnalysis,
    RouteWorkspaceState,
    WorkingCopy,
)
from gtfs_explorer.domain.edit_validation import WorkingCopyValidator
from gtfs_explorer.domain.spec import ScheduleSpec
from gtfs_explorer.domain.subset import SubsetSelection
from gtfs_explorer.domain.validation import ValidationIssue, ValidationSeverity
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.duckdb.repositories.editor import DuckDbEditorRepository
from gtfs_explorer.infrastructure.exporting.revision import (
    RevisionExportPreview,
    WorkingCopyGtfsBuilder,
)


class RevisionConfirmationError(ValueError):
    """La revisión no puede publicarse mientras conserve errores bloqueantes."""


MAX_EDITING_ROUTES = 3


@dataclass(frozen=True)
class EditSession:
    """Contexto de rutas cargadas en una edición cartográfica.

    El orden de ``route_ids`` es estable y también sirve para mostrar el
    ordinal en la lista, el encabezado y la ventana desacoplada. Solo
    ``active_route_id`` es mutable; las demás rutas son referencias.
    """

    route_ids: tuple[str, ...]
    active_route_id: str
    history_start: int = 0
    initial_route_states: tuple[RouteWorkspaceState, ...] = ()

    def __post_init__(self) -> None:
        unique = tuple(dict.fromkeys(route_id for route_id in self.route_ids if route_id))
        if not 1 <= len(unique) <= MAX_EDITING_ROUTES:
            raise ValueError(
                f"Una sesión de edición debe contener entre 1 y {MAX_EDITING_ROUTES} rutas."
            )
        if self.active_route_id not in unique:
            raise ValueError("La ruta activa debe pertenecer a las rutas cargadas.")
        if unique != self.route_ids:
            object.__setattr__(self, "route_ids", unique)

    @classmethod
    def create(
        cls,
        route_ids: tuple[str, ...] | list[str],
        *,
        active_route_id: str | None = None,
        history_start: int = 0,
        initial_route_states: tuple[RouteWorkspaceState, ...] = (),
    ) -> "EditSession":
        ordered = tuple(dict.fromkeys(str(route_id) for route_id in route_ids if str(route_id)))
        if not ordered:
            raise ValueError("Selecciona al menos una ruta para iniciar la edición.")
        return cls(
            ordered,
            active_route_id or ordered[0],
            history_start=history_start,
            initial_route_states=initial_route_states,
        )

    @property
    def loaded_route_ids(self) -> tuple[str, ...]:
        return self.route_ids

    @property
    def reference_route_ids(self) -> tuple[str, ...]:
        return tuple(route_id for route_id in self.route_ids if route_id != self.active_route_id)

    @property
    def total_routes(self) -> int:
        return len(self.route_ids)

    def ordinal(self, route_id: str) -> int:
        try:
            return self.route_ids.index(route_id) + 1
        except ValueError as error:
            raise ValueError(f"La ruta no pertenece a la sesión: {route_id}") from error

    def with_active(self, route_id: str) -> "EditSession":
        if route_id not in self.route_ids:
            raise ValueError(f"La ruta no pertenece a la sesión: {route_id}")
        return type(self)(
            self.route_ids,
            route_id,
            history_start=self.history_start,
            initial_route_states=self.initial_route_states,
        )


# Nombres expresivos para consumidores que prefieren describir el contexto
# como una sesión de edición de rutas.
RouteEditingSession = EditSession
EditingSession = EditSession


@dataclass
class EditorSession:
    """Sesión local de edición; cada operación persistente es transaccional."""

    _unit_of_work: DuckDbUnitOfWork
    working_copy: WorkingCopy
    _opened_project: OpenedProject | None = None
    validation_issues: tuple[ValidationIssue, ...] = ()
    editing_session: EditSession | None = None
    validation_current: bool = False

    @classmethod
    def open_project(cls, project_directory: Path) -> "EditorSession":
        """Abre un proyecto existente y recupera su borrador persistido."""
        opened = OpenProject(project_directory).execute()
        try:
            unit_of_work = DuckDbUnitOfWork(opened.database)
            return cls(
                unit_of_work,
                DuckDbEditorRepository(unit_of_work.connection).create_or_recover(),
                opened,
            )
        except Exception:
            if "unit_of_work" in locals():
                unit_of_work.rollback()
                unit_of_work.connection.close()
            opened.close()
            raise

    @classmethod
    def open(cls, unit_of_work: DuckDbUnitOfWork) -> "EditorSession":
        repository = DuckDbEditorRepository(unit_of_work.connection)
        return cls(unit_of_work, repository.create_or_recover())

    def preview_impact(self, command: EditorCommand) -> ImpactAnalysis:
        """Calcula el impacto efectivo sin tocar el borrador ni DuckDB."""
        return self.working_copy.analyze_impact(command)

    def prepare_command(
        self,
        command: EditorCommand,
        impact: ImpactAnalysis,
        *,
        resolution: str | None = None,
        replacement_id: str | None = None,
    ) -> EditorCommand:
        """Adjunta una confirmación de impacto y, si procede, cambios secundarios."""
        return self.working_copy.prepare_command(
            command,
            impact,
            resolution=resolution,
            replacement_id=replacement_id,
        )

    def apply(
        self, command: EditorCommand, *, impact: ImpactAnalysis | None = None
    ) -> EditorCommand:
        result = (
            self.working_copy.apply_with_impact(command, impact)
            if impact is not None
            else self.working_copy.apply(command)
        )
        self._invalidate_validation()
        self._persist()
        return result

    def apply_batch(self, commands: tuple[EditorCommand, ...]) -> tuple[EditorCommand, ...]:
        """Aplica un lote y lo persiste solo cuando el lote completo es válido."""
        impacts = tuple(self.working_copy.analyze_impact(command) for command in commands)
        result = self.working_copy.apply_batch(commands, impacts)
        self._invalidate_validation()
        self._persist()
        return result

    @property
    def dirty(self) -> bool:
        return self.working_copy.dirty

    @property
    def data_draft_dirty(self) -> bool:
        return self.working_copy.data_draft_dirty

    @property
    def workspace_dirty(self) -> bool:
        return self.working_copy.workspace_dirty

    @property
    def working_revision_id(self) -> str:
        return self.working_copy.base_revision_id

    def save_draft(self) -> None:
        """Fuerza el checkpoint persistente sin publicar una WorkingRevision."""
        self._persist()
        self._unit_of_work.checkpoint()

    def confirm_revision(self, revision_id: str | None = None) -> str:
        """Valida y publica atómicamente el borrador como nueva revisión de trabajo."""
        issues = self.validate()
        self.validation_issues = issues
        blocking = tuple(
            issue
            for issue in issues
            if issue.severity in {ValidationSeverity.ERROR, ValidationSeverity.FATAL}
        )
        if blocking:
            raise RevisionConfirmationError(
                "No se puede confirmar la revisión: "
                f"{len(blocking)} incidencias bloqueantes pendientes."
            )
        selected_revision_id = revision_id or f"revision-{uuid4()}"
        DuckDbEditorRepository(self._unit_of_work.connection).publish_revision(
            self.working_copy,
            revision_id=selected_revision_id,
        )
        return selected_revision_id

    def commit_revision(self, revision_id: str | None = None) -> str:
        """Alias de aplicación para el paso explícito de confirmación."""
        return self.confirm_revision(revision_id)

    def save(self, revision_id: str | None = None) -> str | None:
        """Publica solo un borrador de datos pendiente; un editor limpio es no-op."""
        if not self.data_draft_dirty:
            return None
        return self.confirm_revision(revision_id)

    def revisions(self) -> tuple[tuple[str, str | None, str], ...]:
        return DuckDbEditorRepository(self._unit_of_work.connection).revisions()

    def undo(self) -> EditorCommand:
        result = self.working_copy.undo()
        self._invalidate_validation()
        self._persist()
        return result

    def redo(self) -> EditorCommand:
        result = self.working_copy.redo()
        self._invalidate_validation()
        self._persist()
        return result

    def discard(self) -> None:
        self.working_copy.discard()
        DuckDbEditorRepository(self._unit_of_work.connection).discard_working_revision(
            self.working_copy
        )
        self._invalidate_validation()

    def set_route_workspace_state(self, state: RouteWorkspaceState) -> None:
        """Guarda solo el estado visual afectado dentro de la transacción abierta."""
        before = self.working_copy.route_states
        self.working_copy.set_route_workspace_state(state)
        after = self.working_copy.route_states
        changed = tuple(
            after[route_id]
            for route_id in sorted(set(before) | set(after))
            if before.get(route_id) != after.get(route_id) and route_id in after
        )
        DuckDbEditorRepository(self._unit_of_work.connection).persist_route_workspace_states(
            changed
        )

    def set_route_workspace_states(self, states: tuple[RouteWorkspaceState, ...]) -> None:
        """Aplica y persiste un lote de estados visuales con un único UPSERT."""
        if not states:
            return
        before = self.working_copy.route_states
        for state in states:
            self.working_copy.set_route_workspace_state(state)
        after = self.working_copy.route_states
        changed = tuple(
            after[route_id]
            for route_id in sorted(set(before) | set(after))
            if before.get(route_id) != after.get(route_id) and route_id in after
        )
        DuckDbEditorRepository(self._unit_of_work.connection).persist_route_workspace_states(
            changed
        )

    def start_editing(
        self,
        route_ids: tuple[str, ...] | list[str],
        *,
        active_route_id: str | None = None,
    ) -> EditSession:
        """Abre un contexto de una a tres rutas sobre los mismos índices.

        Cambiar estados de ruta solo actualiza el overlay visual persistido;
        no reconstruye entidades ni geometrías y no crea una segunda working
        copy.
        """
        if self.editing_session is not None:
            raise ValueError("Ya hay una sesión de edición cartográfica abierta.")
        ordered = tuple(dict.fromkeys(str(route_id) for route_id in route_ids if str(route_id)))
        if not 1 <= len(ordered) <= MAX_EDITING_ROUTES:
            raise ValueError(f"Puedes cargar entre 1 y {MAX_EDITING_ROUTES} rutas como contexto.")
        available = self.working_copy.entity_index.routes_by_id
        missing = tuple(route_id for route_id in ordered if route_id not in available)
        if missing:
            raise ValueError(f"No existen las rutas seleccionadas: {', '.join(missing)}")
        active = active_route_id or ordered[0]
        if active not in ordered:
            raise ValueError("La ruta activa debe pertenecer a las rutas seleccionadas.")
        active_state = self.working_copy.route_state(active)
        if active_state.locked:
            raise ValueError("La ruta activa está bloqueada y no puede editarse.")
        initial_states = tuple(self.working_copy.route_state(route_id) for route_id in ordered)
        editing = EditSession.create(
            ordered,
            active_route_id=active,
            history_start=len(self.working_copy.changeset.active_commands),
            initial_route_states=initial_states,
        )
        states = tuple(
            replace(
                self.working_copy.route_state(route_id),
                visible=True,
                active=route_id == active,
                editable=route_id == active,
                locked=route_id != active,
            )
            for route_id in ordered
        )
        self.set_route_workspace_states(states)
        self.editing_session = editing
        return editing

    def activate_editing_route(self, route_id: str) -> EditSession:
        """Cambia la ruta mutable dentro del contexto sin reconstruir el mapa."""
        editing = self.editing_session
        if editing is None:
            raise ValueError("No hay una sesión de edición abierta.")
        if route_id not in editing.route_ids:
            raise ValueError("Solo puedes activar una ruta cargada como referencia.")
        current = self.working_copy.route_state(route_id)
        if current.locked and route_id != editing.active_route_id:
            # El bloqueo de una referencia es una convención de la sesión, no
            # una prohibición permanente: se sustituye por el nuevo rol activo.
            pass
        states = tuple(
            replace(
                self.working_copy.route_state(candidate),
                visible=True,
                active=candidate == route_id,
                editable=candidate == route_id,
                locked=candidate != route_id,
            )
            for candidate in editing.route_ids
        )
        self.set_route_workspace_states(states)
        self.editing_session = editing.with_active(route_id)
        return self.editing_session

    def finish_editing(self, *, discard_session_changes: bool = False) -> None:
        """Cierra el contexto; opcionalmente revierte solo sus comandos."""
        editing = self.editing_session
        if editing is None:
            return
        if discard_session_changes:
            while len(self.working_copy.changeset.active_commands) > editing.history_start:
                self.undo()
            if editing.initial_route_states:
                self.set_route_workspace_states(editing.initial_route_states)
        elif editing.initial_route_states:
            # Los roles activo/referencia son contexto temporal de la sesión;
            # no deben quedar persistidos como flags al volver a Explorar.
            self.set_route_workspace_states(editing.initial_route_states)
        self.editing_session = None

    @property
    def editing_dirty(self) -> bool:
        """Indica si esta sesión concreta introdujo cambios en el borrador."""
        editing = self.editing_session
        if editing is None:
            return False
        return len(self.working_copy.changeset.active_commands) > editing.history_start

    def can_edit_route(self, route_id: str) -> bool:
        return self.working_copy.can_edit_route(route_id)

    def validate(self) -> tuple[ValidationIssue, ...]:
        """Recalcula y registra la validación completa del borrador efectivo."""
        self.validation_issues = WorkingCopyValidator().validate(self.working_copy)
        self.validation_current = True
        return self.validation_issues

    def _invalidate_validation(self) -> None:
        self.validation_issues = ()
        self.validation_current = False

    def preview_revision_export(
        self,
        specification: ScheduleSpec,
        *,
        revision_id: str = "draft",
        selection: SubsetSelection | None = None,
    ) -> RevisionExportPreview:
        """Calcula el cierre de exportación sin publicar ningún archivo."""
        return WorkingCopyGtfsBuilder(self.working_copy, specification).preview(
            revision_id=revision_id,
            selection=selection,
        )

    def _persist(self) -> None:
        DuckDbEditorRepository(self._unit_of_work.connection).persist(self.working_copy)

    def close(self) -> None:
        """Confirma la transacción y libera el escritor del proyecto."""
        # Si COMMIT falla, la sesión queda abierta para permitir reintento o
        # decisión explícita; cerrar aquí haría que la UI conservase una
        # referencia irrecuperable tras comunicar el error.
        self._unit_of_work.commit()
        self._unit_of_work.connection.close()
        if self._opened_project is not None:
            self._opened_project.close()

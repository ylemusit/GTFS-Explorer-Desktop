"""Pruebas focales de exportación GTFS desde una revisión de trabajo."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import EditorCommand, EditorCommandKind, WorkingCopy
from gtfs_explorer.domain.exporting import ExportError
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.domain.subset import SubsetSelection
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.infrastructure.exporting.revision import RevisionGtfsExporter
from tests.helpers.export_contract import SPEC_PATH, prepare_contract_feed


def test_revision_export_is_explicit_and_reimportable(tmp_path: Path) -> None:
    prepared = prepare_contract_feed(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    with DuckDbUnitOfWork(prepared.database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        with pytest.raises(ExportError, match="borrador"):
            RevisionGtfsExporter(specification).write(
                tmp_path / "draft.zip",
                session.working_copy,
                revision_id="draft",
                confirmed=False,
            )
        session.confirm_revision("working-1")
        destination = tmp_path / "revision.zip"
        manifest = RevisionGtfsExporter(specification).write(
            destination,
            session.working_copy,
            revision_id="working-1",
            confirmed=True,
            selection=SubsetSelection(frozenset({"A"})),
        )

    assert manifest.artifact_name == "revision.zip"
    with ZipFile(destination) as archive:
        assert {"agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt"} <= {
            name for name in archive.namelist()
        }


def test_complete_and_new_version_exports_do_not_mutate_working_copy(
    tmp_path: Path,
) -> None:
    prepared = prepare_contract_feed(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    with DuckDbUnitOfWork(prepared.database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        session.confirm_revision("working-1")
        before = session.working_copy.get(("gtfs_feed_info", "1"))
        complete = tmp_path / "complete.zip"
        RevisionGtfsExporter(specification).write(
            complete,
            session.working_copy,
            revision_id="working-1",
            confirmed=True,
        )
        versioned = tmp_path / "versioned.zip"
        RevisionGtfsExporter(specification).write(
            versioned,
            session.working_copy,
            revision_id="working-1",
            confirmed=True,
            version_id="0.2.0-edited",
        )
        after = session.working_copy.get(("gtfs_feed_info", "1"))

    assert complete.is_file() and complete.stat().st_size > 0
    assert versioned.is_file() and versioned.stat().st_size > 0
    assert after == before


def test_revision_export_rejects_dirty_working_copy(tmp_path: Path) -> None:
    prepared = prepare_contract_feed(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    with DuckDbUnitOfWork(prepared.database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        before = session.working_copy.get(("gtfs_routes", "A"))
        assert before is not None
        after = dict(before)
        after["route_long_name"] = "Borrador"
        command = EditorCommand(EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "A"), before, after)
        session.apply(command, impact=session.preview_impact(command))
        with pytest.raises(ExportError, match="DIRTY"):
            RevisionGtfsExporter(specification).write(
                tmp_path / "dirty.zip",
                session.working_copy,
                revision_id="working-1",
                confirmed=True,
                selection=SubsetSelection(frozenset({"A"})),
            )


def test_confirmed_snapshot_export_excludes_a_later_dirty_draft(tmp_path: Path) -> None:
    prepared = prepare_contract_feed(tmp_path)
    specification = load_schedule_spec(SPEC_PATH)
    with DuckDbUnitOfWork(prepared.database) as unit_of_work:
        session = EditorSession.open(unit_of_work)
        session.confirm_revision("working-1")
        before = session.working_copy.get(("gtfs_routes", "A"))
        assert before is not None
        after = dict(before)
        after["route_long_name"] = "Solo borrador"
        command = EditorCommand(EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "A"), before, after)
        session.apply(command, impact=session.preview_impact(command))

        confirmed = WorkingCopy(
            session.working_copy.original,
            base_revision_id=session.working_revision_id,
            base_entities=session.working_copy.base_entities,
        )
        destination = tmp_path / "confirmed.zip"
        RevisionGtfsExporter(specification).write(
            destination,
            confirmed,
            revision_id="working-1",
            confirmed=True,
        )
        assert session.data_draft_dirty

    with ZipFile(destination) as archive:
        assert "Solo borrador" not in archive.read("routes.txt").decode("utf-8")


class _PolicyHost:
    def __init__(self, session):
        from types import SimpleNamespace

        self.session = session
        self.refreshes = 0
        self._editor = SimpleNamespace(refresh=self.refresh)

    def refresh(self):
        self.refreshes += 1

    def _get_editor_session(self):
        return self.session

    def _export_snapshot(self, session, *, confirmed):
        from gtfs_explorer.presentation.desktop.main_window import MainWindow

        return MainWindow._export_snapshot(session, confirmed=confirmed)


def _choose_policy(monkeypatch, choice):
    class Dialog:
        def __init__(self, *args):
            self.buttons = []

        def setWindowTitle(self, *args):
            pass

        def setText(self, *args):
            pass

        def addButton(self, *args):
            button = object()
            self.buttons.append(button)
            return button

        def exec(self):
            pass

        def clickedButton(self):
            return (
                None
                if choice == "close"
                else self.buttons[{"save": 0, "without": 1, "cancel": 2}[choice]]
            )

    from PySide6.QtWidgets import QMessageBox

    Dialog.ButtonRole = QMessageBox.ButtonRole
    Dialog.warning = staticmethod(lambda *args: None)
    monkeypatch.setattr("gtfs_explorer.presentation.desktop.main_window.QMessageBox", Dialog)


def _rename_route(session, name):
    before = session.working_copy.get(("gtfs_routes", "A"))
    after = dict(before, route_long_name=name)
    command = EditorCommand(EditorCommandKind.UPDATE_ROUTE, ("gtfs_routes", "A"), before, after)
    session.apply(command, impact=session.preview_impact(command))


@pytest.mark.parametrize("choice", ["save", "without", "cancel", "close"])
@pytest.mark.parametrize("format_name", ["COMPLETE_GTFS", "NEW_GTFS_VERSION"])
def test_full_export_preflight_decisions(tmp_path, monkeypatch, choice, format_name):
    from gtfs_explorer.presentation.desktop.exporter.widget import ExportFormat, ExportRequest
    from gtfs_explorer.presentation.desktop.main_window import MainWindow

    prepared = prepare_contract_feed(tmp_path)
    with DuckDbUnitOfWork(prepared.database) as uow:
        session = EditorSession.open(uow)
        session.confirm_revision("base-1")
        _rename_route(session, "Draft route")
        before_history = session.working_copy.changeset.active_commands
        _choose_policy(monkeypatch, choice)
        host = _PolicyHost(session)
        request = ExportRequest(
            ExportFormat[format_name],
            tmp_path / "out.zip",
            version_id="next-version" if format_name == "NEW_GTFS_VERSION" else None,
        )
        result = MainWindow._prepare_export_policy(host, request)
        if choice in {"cancel", "close"}:
            assert result is None
            assert session.working_revision_id == "base-1"
            assert session.data_draft_dirty
            assert session.working_copy.changeset.active_commands == before_history
            assert not request.destination.exists()
            return
        assert result.source_working_copy.base_revision_id == session.working_revision_id
        assert session.data_draft_dirty is (choice == "without")
        assert host.refreshes == (1 if choice == "save" else 0)
        if choice == "save":
            assert session.working_revision_id != "base-1"
            assert session.validation_current
            assert not session.working_copy.changeset.undo_available
            assert not session.working_copy.changeset.redo_available
        else:
            assert session.working_revision_id == "base-1"
        exported = MainWindow._write_revision_export(
            host, result, result.source_working_copy, "feed", lambda: False
        )
        assert exported.manifest.metadata["revision_id"] == session.working_revision_id
        with ZipFile(request.destination) as archive:
            assert ("Draft route" in archive.read("routes.txt").decode()) is (choice == "save")


def test_preflight_failed_save_refreshes_current_validation(tmp_path, monkeypatch):
    from gtfs_explorer.presentation.desktop.exporter.widget import ExportFormat, ExportRequest
    from gtfs_explorer.presentation.desktop.main_window import MainWindow

    prepared = prepare_contract_feed(tmp_path)
    with DuckDbUnitOfWork(prepared.database) as uow:
        session = EditorSession.open(uow)
        before = session.working_copy.get(("gtfs_stops", "S1"))
        if before is None:
            key = next(key for key in session.working_copy.entities if key[0] == "gtfs_stops")
            before = session.working_copy.get(key)
        else:
            key = ("gtfs_stops", "S1")
        session.apply(
            EditorCommand(EditorCommandKind.MOVE_STOP, key, before, dict(before, stop_lat=100.0))
        )
        base = session.working_revision_id
        _choose_policy(monkeypatch, "save")
        host = _PolicyHost(session)
        assert (
            MainWindow._prepare_export_policy(
                host, ExportRequest(ExportFormat.COMPLETE_GTFS, tmp_path / "bad.zip")
            )
            is None
        )
        assert host.refreshes == 1
        assert session.validation_current and session.validation_issues
        assert session.working_revision_id == base
        assert session.data_draft_dirty
        assert not (tmp_path / "bad.zip").exists()


@pytest.mark.parametrize("format_name", ["JSON", "CSV", "GEOJSON", "MINI_GTFS", "KML", "KMZ"])
def test_dirty_subset_provenance_and_snapshot_isolation(tmp_path, format_name):
    import json

    from gtfs_explorer.presentation.desktop.exporter.widget import ExportFormat, ExportRequest
    from gtfs_explorer.presentation.desktop.main_window import MainWindow

    prepared = prepare_contract_feed(tmp_path)
    with DuckDbUnitOfWork(prepared.database) as uow:
        session = EditorSession.open(uow)
        session.confirm_revision("base-1")
        _rename_route(session, "Snapshot route")
        host = _PolicyHost(session)
        format_ = ExportFormat[format_name]
        suffix = {"MINI_GTFS": "zip", "GEOJSON": "geojson"}.get(format_name, format_name.lower())
        request = ExportRequest(
            format_, tmp_path / ("snapshot." + suffix), route_ids=frozenset({"A"})
        )
        snapshot = MainWindow._prepare_export_policy(host, request)
        assert snapshot.source_is_draft
        assert (
            snapshot.source_working_copy.get(("gtfs_routes", "A"))["route_long_name"]
            == "Snapshot route"
        )
        _rename_route(session, "Later route")
        result = MainWindow._write_revision_export(
            host, snapshot, snapshot.source_working_copy, "feed", lambda: False
        )
        assert result.manifest.metadata["base_revision_id"] == "base-1"
        assert result.manifest.metadata["source_state"] == "unpublished_effective"
        assert result.manifest.metadata.get("revision_id") is None
        if format_name == "JSON":
            payload = json.loads(request.destination.read_text(encoding="utf-8"))
            assert payload["revision"]["revision_id"] is None
            assert payload["revision"]["source_state"] == "unpublished_effective"
            assert payload["tables"]["routes.txt"][0]["route_long_name"] == "Snapshot route"
        elif format_name == "CSV":
            assert "Snapshot route" in request.destination.read_text(encoding="utf-8")
        elif format_name == "GEOJSON":
            payload = json.loads(request.destination.read_text(encoding="utf-8"))
            assert payload["metadata"]["revision_id"] is None
            assert all(f["properties"]["revision_id"] is None for f in payload["features"])
        elif format_name == "MINI_GTFS":
            with ZipFile(request.destination) as archive:
                assert "Snapshot route" in archive.read("routes.txt").decode()
        else:
            from xml.etree import ElementTree as ET

            if format_name == "KMZ":
                with ZipFile(request.destination) as archive:
                    content = archive.read("doc.kml")
            else:
                content = request.destination.read_bytes()
            root = ET.fromstring(content)
            names = [d.get("name") for d in root.iter() if d.tag.endswith("}Data")]
            assert "revision_id" not in names
            assert "base_revision_id" in names and "source_state" in names
        assert session.working_revision_id == "base-1"
        assert session.data_draft_dirty
        assert (
            snapshot.source_working_copy.get(("gtfs_routes", "A"))["route_long_name"]
            == "Snapshot route"
        )

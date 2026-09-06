"""Pruebas focales de exportación GTFS desde una revisión de trabajo."""

from pathlib import Path
from zipfile import ZipFile

import pytest

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import EditorCommand, EditorCommandKind
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

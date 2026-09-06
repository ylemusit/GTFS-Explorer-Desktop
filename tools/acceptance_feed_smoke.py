"""Smoke técnico aislado para una copia de AcceptanceFeedTest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from gtfs_explorer.application.editor_session import EditorSession
from gtfs_explorer.domain.changesets import RouteWorkspaceState
from gtfs_explorer.domain.operations import OperationStatus, OperationType
from gtfs_explorer.domain.ports import PageRequest
from gtfs_explorer.infrastructure.duckdb.repositories import DuckDbUnitOfWork
from gtfs_explorer.presentation.desktop.exporter import ExportFormat, ExportRequest
from gtfs_explorer.presentation.desktop.main_window import MainWindow


class _ApplicationExportHarness:
    """Subset bound of the real MainWindow export orchestration."""

    _export_feed = MainWindow._export_feed
    _write_feed_export = MainWindow._write_feed_export
    _write_revision_export = MainWindow._write_revision_export

    def __init__(self, opened: object) -> None:
        self._opened_project = opened


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def _manifest_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.name}.manifest.json")


def _assert_manifest(destination: Path) -> dict[str, object]:
    assert destination.is_file() and destination.stat().st_size > 0
    manifest_path = _manifest_path(destination)
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["artifact_name"] == destination.name
    assert payload["size_bytes"] == destination.stat().st_size
    assert payload["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    return payload


def _assert_gtfs(destination: Path) -> None:
    expected = {"agency.txt", "routes.txt", "trips.txt", "stops.txt", "stop_times.txt"}
    with ZipFile(destination) as archive:
        assert expected <= set(archive.namelist())
        assert all("/" not in n and "\\" not in n for n in archive.namelist())


def _assert_kml(destination: Path) -> None:
    root = ET.fromstring(destination.read_bytes())
    assert root.tag.rsplit("}", 1)[-1] == "kml"
    assert any(e.tag.rsplit("}", 1)[-1] == "Document" for e in root.iter())


def _assert_kmz(destination: Path) -> None:
    with ZipFile(destination) as archive:
        assert "doc.kml" in archive.namelist()
        ET.fromstring(archive.read("doc.kml"))


def _assert_history(database: object, project_id: str, artifact: str, format_: str) -> None:
    with DuckDbUnitOfWork(database) as unit_of_work:  # type: ignore[arg-type]
        operations = unit_of_work.operations.list_operations(
            project_id, PageRequest(limit=100), OperationType.EXPORT, OperationStatus.COMPLETED
        ).items
    matches = [
        item
        for item in operations
        if item.artifact_name == artifact and item.export_format == format_
    ]
    assert len(matches) == 1
    item = matches[0]
    assert item.status is OperationStatus.COMPLETED
    assert item.artifact_sha256 and item.artifact_size_bytes and item.artifact_size_bytes > 0


def _export(
    harness: _ApplicationExportHarness, request: ExportRequest, project_id: str, database: object
) -> None:
    result = harness._export_feed(request, lambda: False)
    _assert_manifest(request.destination)
    _assert_history(database, project_id, request.destination.name, request.format.value)
    assert result.manifest.artifact_name == request.destination.name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    original = parser.parse_args().original.resolve()
    before = _hash_tree(original)
    temporary_root = Path(tempfile.mkdtemp(prefix="gtfs-acceptance-smoke-"))
    temporary_project = temporary_root / original.name
    result: dict[str, object] = {
        "TEMP_COPY_CREATED": False,
        "TEMP_COPY_PATH": str(temporary_project),
        "REAL_FEED_CANCEL_SMOKE": "NOT_SUPPORTED",
        "CANCELLATION_AUTOMATED_COVERAGE_ALREADY_EXISTS": "YES",
    }
    session: EditorSession | None = None
    try:
        shutil.copytree(original, temporary_project)
        result["TEMP_COPY_CREATED"] = True
        session = EditorSession.open_project(temporary_project)
        opened = session._opened_project
        assert opened is not None
        project_id = opened.descriptor.project_id
        routes = session._unit_of_work.route_explorer.routes(PageRequest(limit=1)).items
        assert routes
        route_id = routes[0].route_id
        result.update(
            {
                "REAL_FEED_OPEN": "PASS",
                "REAL_FEED_EDITOR_SESSION": "PASS",
                "DATABASE_SCHEMA": session._unit_of_work.projects.schema_version(),
                "ROUTE_ID": route_id,
                "ORIGINAL_REVISION_STATE": "PASS"
                if (
                    session.working_revision_id == "original"
                    and not session.data_draft_dirty
                    and len(session.working_copy.changeset.active_commands) == 0
                )
                else "FAIL",
            }
        )
        assert result["ORIGINAL_REVISION_STATE"] == "PASS"
        opened_for_export = SimpleNamespace(database=opened.database, descriptor=opened.descriptor)
        session.close()
        session = None
        harness = _ApplicationExportHarness(opened_for_export)
        for format_, name, checker, key in (
            (ExportFormat.JSON, "smoke.json", None, "JSON_EXPORT_SMOKE"),
            (ExportFormat.COMPLETE_GTFS, "smoke.zip", _assert_gtfs, "GTFS_EXPORT_SMOKE"),
            (ExportFormat.KML, "smoke.kml", _assert_kml, "KML_EXPORT_SMOKE"),
            (ExportFormat.KMZ, "smoke.kmz", _assert_kmz, "KMZ_EXPORT_SMOKE"),
        ):
            request = ExportRequest(
                format_,
                temporary_root / name,
                route_ids=frozenset({route_id})
                if format_ is not ExportFormat.COMPLETE_GTFS
                else frozenset(),
            )
            _export(harness, request, project_id, opened_for_export.database)
            if checker is not None:
                checker(request.destination)
            result[key] = "PASS"

        session = EditorSession.open_project(temporary_project)
        state = session.working_copy.route_state(route_id)
        session.set_route_workspace_state(
            RouteWorkspaceState(
                route_id,
                visible=not state.visible,
                active=state.active,
                editable=state.editable,
                locked=state.locked,
                dimmed=state.dimmed,
            )
        )
        result.update(
            {
                "COMMAND_COUNT": len(session.working_copy.changeset.active_commands),
                "DATA_DRAFT_DIRTY": session.data_draft_dirty,
                "WORKSPACE_DIRTY": session.workspace_dirty,
            }
        )
        assert result["COMMAND_COUNT"] == 0 and result["DATA_DRAFT_DIRTY"] is False
        assert result["WORKSPACE_DIRTY"] is True
        workspace_opened = session._opened_project
        assert workspace_opened is not None
        workspace_project = SimpleNamespace(
            database=workspace_opened.database, descriptor=workspace_opened.descriptor
        )
        workspace_database = workspace_opened.database
        session.close()
        session = None
        _export(
            _ApplicationExportHarness(workspace_project),
            ExportRequest(ExportFormat.COMPLETE_GTFS, temporary_root / "workspace-only.zip"),
            project_id,
            workspace_database,
        )
        result.update(
            {
                "WORKSPACE_ONLY_EXPORT_SMOKE": "PASS",
                "HISTORY_SMOKE": "PASS",
                "FORMAT_DESTINATION_SMOKE": "PASS",
                "REAL_FEED_CLOSE": "PASS",
            }
        )
    finally:
        if session is not None:
            session.close()
        shutil.rmtree(temporary_root)
        result["TEMP_OUTPUTS_DELETED"] = not temporary_root.exists()
        result["TEMP_COPY_DELETED"] = not temporary_root.exists()
        result["ORIGINAL_ACCEPTANCE_PROJECT_MUTATED"] = before != _hash_tree(original)
    keys = (
        "ORIGINAL_REVISION_STATE",
        "JSON_EXPORT_SMOKE",
        "GTFS_EXPORT_SMOKE",
        "KML_EXPORT_SMOKE",
        "KMZ_EXPORT_SMOKE",
        "WORKSPACE_ONLY_EXPORT_SMOKE",
        "HISTORY_SMOKE",
        "FORMAT_DESTINATION_SMOKE",
    )
    result["SMOKE_CLOSE_STATUS"] = (
        "PASS"
        if (
            all(result.get(key) == "PASS" for key in keys)
            and result["TEMP_OUTPUTS_DELETED"]
            and result["TEMP_COPY_DELETED"]
            and not result["ORIGINAL_ACCEPTANCE_PROJECT_MUTATED"]
        )
        else "BLOCKED"
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["SMOKE_CLOSE_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

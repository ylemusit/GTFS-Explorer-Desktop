"""Fixture pequeña y matriz contractual común para P1-15."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from gtfs_explorer.application.commands.import_feed import ImportFeed
from gtfs_explorer.domain.project import JobState, ProjectMetadata, ProjectStatus
from gtfs_explorer.domain.source import InputSource, InputSourceKind
from gtfs_explorer.domain.spec import load_schedule_spec
from gtfs_explorer.infrastructure.duckdb.database import DatabaseSettings, ProjectDatabase
from gtfs_explorer.presentation.desktop.exporter import ExportFormat

_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = _ROOT / "schemas" / "gtfs_schedule" / "2026-04-27" / "spec.json"
FIXTURE_PATH = _ROOT / "tests" / "fixtures" / "specs" / "mini_gtfs_contract.json"


@dataclass(frozen=True)
class ExportCapability:
    """Contrato verificable de un formato productivo actual."""

    format: ExportFormat
    extension: str
    supports_manifest: bool
    supports_subset: bool
    reimportable: bool
    expected_artifact_kind: str
    description_fragment: str
    manifest_metadata_keys: tuple[str, ...] = ()


EXPORT_CAPABILITIES: tuple[ExportCapability, ...] = (
    ExportCapability(
        ExportFormat.JSON,
        ".json",
        True,
        True,
        False,
        "json_bundle",
        "bundle json",
    ),
    ExportCapability(
        ExportFormat.GEOJSON,
        ".geojson",
        True,
        True,
        False,
        "geojson_feature_collection",
        "geojson",
    ),
    ExportCapability(
        ExportFormat.CSV,
        ".csv",
        True,
        True,
        False,
        "csv_route_view",
        "route_id",
        ("csv_delimiter", "encoding", "formula_neutralization", "mode", "utf8_bom"),
    ),
    ExportCapability(
        ExportFormat.MINI_GTFS,
        ".zip",
        True,
        True,
        True,
        "mini_gtfs_zip",
        "subconjunto gtfs autocontenido",
        ("formal_validation", "format", "internal_revalidation"),
    ),
)


@dataclass(frozen=True)
class PreparedContractFeed:
    database: ProjectDatabase
    source_directory: Path
    project_id: str
    feed_id: str


def prepare_contract_feed(
    root: Path,
    *,
    project_id: str = "project-1",
    feed_id: str = "feed-1",
    job_id: str = "job-1",
) -> PreparedContractFeed:
    """Importa el fixture común en una DuckDB aislada y lista para exportar."""
    source_directory = root / "contract-source"
    source_directory.mkdir(parents=True, exist_ok=True)
    write_contract_fixture(source_directory)

    database = ProjectDatabase(
        root / "project.duckdb",
        root / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    result = ImportFeed(
        database,
        ProjectMetadata(project_id, "P1-15 contract fixture", ProjectStatus.READY),
        InputSource(source_directory, InputSourceKind.DIRECTORY),
        load_schedule_spec(SPEC_PATH),
        job_id=job_id,
        feed_id=feed_id,
    ).execute()
    if result.state is not JobState.READY or result.issue_count != 0:
        raise AssertionError(
            f"El fixture contractual no está listo: {result.state=} {result.issue_count=}"
        )
    return PreparedContractFeed(database, source_directory, project_id, feed_id)


def make_database(root: Path) -> ProjectDatabase:
    """Crea una DuckDB vacía para una reimportación independiente."""
    root.mkdir(parents=True, exist_ok=True)
    database = ProjectDatabase(
        root / "project.duckdb",
        root / "temporary",
        settings=DatabaseSettings(memory_limit="128MB", max_temp_directory_size="128MB", threads=1),
    )
    database.initialize()
    return database


def write_contract_fixture(destination: Path) -> None:
    """Materializa el JSON versionable del fixture como archivos GTFS."""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for filename, table in fixture["tables"].items():
        with (destination / filename).open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=table["headers"],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(table["rows"])

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from gtfs_explorer.presentation.desktop.map.widget import _map_assets_directory
from gtfs_explorer.product import IDENTITY


def _load_builder() -> object:
    path = Path(__file__).parents[1] / "tools" / "build_portable.py"
    specification = importlib.util.spec_from_file_location("build_portable", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_map_assets_are_resolved_from_the_repository_not_the_cwd(monkeypatch) -> None:
    monkeypatch.chdir(Path.cwd().anchor)
    assert _map_assets_directory().name == "qt_resources"
    assert (_map_assets_directory() / "map_bundle.js").is_file()


def test_map_assets_are_resolved_next_to_the_compiled_executable(
    tmp_path: Path, monkeypatch
) -> None:
    executable = tmp_path / "GTFS Explorer.exe"
    executable.touch()
    assets = tmp_path / "web" / "map" / "qt_resources"
    assets.mkdir(parents=True)
    (assets / "map_bundle.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(executable))

    assert _map_assets_directory() == assets


def test_portable_zip_contains_the_offline_runtime_contract(tmp_path: Path) -> None:
    root = tmp_path / "GTFS-Explorer"
    (root / "web" / "map" / "qt_resources").mkdir(parents=True)
    (root / "GTFS Explorer.exe").write_bytes(b"exe")
    (root / "portable.flag").touch()
    (root / "LICENSES").mkdir()
    (root / "web" / "map" / "qt_resources" / "map_bundle.js").write_text("", encoding="utf-8")
    (root / "LICENSES" / "README.md").write_text("licencias", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.html").write_text("avisos", encoding="utf-8")
    (root / "SBOM.cdx.json").write_text("{}", encoding="utf-8")
    archive = tmp_path / "portable.zip"
    with zipfile.ZipFile(archive, "w") as packaged:
        for path in root.rglob("*"):
            if path.is_file():
                packaged.write(path, path.relative_to(tmp_path).as_posix())
    with zipfile.ZipFile(archive) as packaged:
        names = set(packaged.namelist())
    assert "GTFS-Explorer/GTFS Explorer.exe" in names
    assert "GTFS-Explorer/portable.flag" in names
    assert "GTFS-Explorer/web/map/qt_resources/map_bundle.js" in names
    assert "GTFS-Explorer/LICENSES/README.md" in names
    assert "GTFS-Explorer/THIRD_PARTY_NOTICES.html" in names
    assert "GTFS-Explorer/SBOM.cdx.json" in names


def test_distribution_includes_manifested_user_guide(tmp_path: Path, monkeypatch) -> None:
    builder = _load_builder()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    deployment = tmp_path / "packaging" / "portable" / "deployment" / "entrypoint.dist"
    deployment.mkdir(parents=True)
    (deployment / "entrypoint.exe").write_bytes(b"exe")
    map_assets = tmp_path / "web" / "map" / "qt_resources"
    map_assets.mkdir(parents=True)
    (map_assets / "map_bundle.js").write_text("map", encoding="utf-8")
    guide = tmp_path / "docs" / "USER_GUIDE.md"
    guide.parent.mkdir()
    guide.write_text("manual", encoding="utf-8")
    monkeypatch.setattr(builder, "MAP_ASSETS", map_assets)
    monkeypatch.setattr(builder, "USER_GUIDE", guide)

    destination = tmp_path / "payload"
    builder._copy_distribution(destination)

    assert (destination / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8") == "manual"


def test_external_duckdb_copy_keeps_source_and_extension_without_caches(tmp_path: Path) -> None:
    builder = _load_builder()
    source = tmp_path / "source" / "duckdb"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text(
        "from .duckdb import connect as connect\n", encoding="utf-8"
    )
    (source / "duckdb.cp312-win_amd64.pyd").write_bytes(b"extension")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "__init__.pyc").write_bytes(b"cache")
    destination = tmp_path / "portable"
    destination.mkdir()

    builder._copy_external_duckdb(destination, source=source)

    assert (destination / "duckdb" / "__init__.py").is_file()
    assert (destination / "duckdb" / "duckdb.cp312-win_amd64.pyd").is_file()
    assert not (destination / "duckdb" / "__pycache__").exists()


def test_external_duckdb_copy_rejects_a_package_without_extension(tmp_path: Path) -> None:
    builder = _load_builder()
    source = tmp_path / "duckdb"
    source.mkdir()

    with pytest.raises(RuntimeError, match="extensión Windows x64"):
        builder._copy_external_duckdb(tmp_path / "portable", source=source)


def test_deploy_excludes_duckdb_from_nuitka_compilation() -> None:
    specification = Path("packaging/portable/pysidedeploy.spec").read_text(encoding="utf-8")
    assert "--nofollow-import-to=duckdb" in specification
    assert "--include-data-dir=src/gtfs_explorer/infrastructure/duckdb/migrations=" in specification
    assert "--include-data-dir=schemas=schemas" in specification


def test_deploy_spec_receives_canonical_windows_metadata(monkeypatch) -> None:
    builder = _load_builder()
    monkeypatch.setattr(builder, "SPEC", Path("packaging/portable/pysidedeploy.spec"))

    rendered = builder._render_deploy_spec()

    assert f"--product-name={IDENTITY.name}" in rendered
    assert f"--company-name={IDENTITY.author}" in rendered
    assert f"--file-version={IDENTITY.windows_file_version}" in rendered
    assert f"--product-version={IDENTITY.windows_product_version}" in rendered
    assert f"--file-description={IDENTITY.file_description}" in rendered
    assert f"--copyright={IDENTITY.copyright_text}" in rendered


def test_previous_deployment_is_removed_before_build(tmp_path: Path, monkeypatch) -> None:
    builder = _load_builder()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    (tmp_path / "packaging" / "portable" / "deployment").mkdir(parents=True)
    (tmp_path / "packaging" / "portable" / "GTFS Explorer.dist").mkdir()

    builder._clean_previous_deployment()

    assert not (tmp_path / "packaging" / "portable" / "deployment").exists()
    assert not (tmp_path / "packaging" / "portable" / "GTFS Explorer.dist").exists()


def test_packaged_map_smoke_requires_rendered_route_evidence(tmp_path: Path, monkeypatch) -> None:
    builder = _load_builder()
    executable = tmp_path / "GTFS Explorer.exe"
    executable.touch()
    (tmp_path / "debug.log").write_text("chromium", encoding="utf-8")

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        report = Path(command[command.index("--map-runtime-smoke-report") + 1])
        report.write_text(
            json.dumps(
                {
                    "success": True,
                    "bridge_ready": True,
                    "route_blue_pixels": 250,
                    "width": 878,
                    "height": 457,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(builder.subprocess, "run", run)

    evidence = builder._smoke_map_runtime(tmp_path)

    assert evidence["bridge_ready"] is True
    assert evidence["route_blue_pixels"] == 250
    assert not (tmp_path / "debug.log").exists()


def test_portable_path_guard_reports_short_root_and_windows_estimates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _load_builder()
    monkeypatch.setattr(builder, "PRODUCT_DIRECTORY", "GTFS-Explorer")
    archive_path = tmp_path / "GTFS-Explorer-Portable-0.1.0-phase2-win-x64.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "GTFS-Explorer/gtfs_explorer/infrastructure/duckdb/migrations/005_geometry_optional_normalized.sql",
            b"sql",
        )

    report = builder._guard_portable_paths(archive_path)

    assert report["max_internal"] == 97
    estimates = report["estimated_absolute"]
    assert isinstance(estimates, dict)
    assert estimates["Desktop"] < builder.PORTABLE_WINDOWS_PATH_LIMIT
    assert estimates["Downloads"] < builder.PORTABLE_WINDOWS_PATH_LIMIT


def test_portable_path_guard_rejects_a_regressed_long_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _load_builder()
    monkeypatch.setattr(builder, "PRODUCT_DIRECTORY", "GTFS Explorer Portable")
    archive_path = tmp_path / "GTFS-Explorer-Portable-0.1.0-phase2-win-x64.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "GTFS Explorer Portable/" + "x" * 180 + ".dll",
            b"dll",
        )

    with pytest.raises(RuntimeError, match="umbral seguro"):
        builder._guard_portable_paths(archive_path)


def test_gtfs023_short_label_omits_redundant_version_from_artifact_name() -> None:
    builder = _load_builder()

    name = builder._artifact_name("GTFS-Explorer-Portable", "0.2.1", "GTFS023-C1", ".zip")

    assert name == "GTFS-Explorer-Portable-GTFS023-C1-win-x64.zip"

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path("tools/check_licenses.py")
    spec = importlib.util.spec_from_file_location("check_licenses", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_creates_cyclonedx_notices_and_license_directory(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "GTFS Explorer.exe").write_bytes(b"exe")

    module.prepare(tmp_path)

    sbom = json.loads((tmp_path / "SBOM.cdx.json").read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert (tmp_path / "THIRD_PARTY_NOTICES.html").is_file()
    assert (tmp_path / "LICENSES" / "maplibre-gl-6.3.0.txt").is_file()
    assert module.verify(tmp_path) == []


def test_verify_rejects_an_uninventoried_distributed_binary(tmp_path: Path) -> None:
    module = _module()
    module.prepare(tmp_path)
    (tmp_path / "mystery-runtime.dll").write_bytes(b"unknown")

    assert module.verify(tmp_path) == ["mystery-runtime.dll"]


def test_verify_attributes_nested_duckdb_runtime_files(tmp_path: Path) -> None:
    module = _module()
    module.prepare(tmp_path)
    nested = tmp_path / "duckdb" / "value"
    nested.mkdir(parents=True)
    (nested / "constant.py").write_text("", encoding="utf-8")
    (tmp_path / "duckdb" / "duckdb.cp312-win_amd64.pyd").write_bytes(b"extension")

    assert module.verify(tmp_path) == []


def test_verify_accepts_application_owned_schemas(tmp_path: Path) -> None:
    module = _module()
    module.prepare(tmp_path)
    schema = tmp_path / "schemas" / "project" / "project.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text("{}", encoding="utf-8")

    assert module.verify(tmp_path) == []

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gtfs_explorer.infrastructure.maps.package import load_map_package

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_map_package.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_map_package", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _arguments(tmp_path: Path, source: str) -> list[str]:
    style = tmp_path / "source-style.json"
    style.write_text('{"version": 8, "sources": {}, "layers": []}', encoding="utf-8")
    return [
        str(SCRIPT),
        "--source",
        source,
        "--output",
        str(tmp_path / "regional"),
        "--source-reference",
        "Archivo autorizado de pruebas",
        "--bbox=-5.9,43.0,-5.7,43.2",
        "--min-zoom",
        "0",
        "--max-zoom",
        "14",
        "--style",
        str(style),
        "--license",
        "ODbL-1.0",
        "--license-url",
        "https://opendatacommons.org/licenses/odbl/",
        "--attribution",
        "© OpenStreetMap contributors",
    ]


def test_package_builds_verifies_and_opens_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    source = tmp_path / "authorised.pmtiles"
    source.write_bytes(b"PMTiles\x03" + bytes(256))
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "sprite.json").write_text("{}", encoding="utf-8")
    commands: list[list[str]] = []

    def run(command: list[str]) -> None:
        commands.append(command)
        if command[1] == "extract":
            Path(command[3]).write_bytes(b"PMTiles\x03" + bytes(256))
        elif command[1] == "verify":
            assert Path(command[2]).read_bytes().startswith(b"PMTiles\x03")

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(module, "_pmtiles_version", lambda _: "pmtiles 3.2.0")
    monkeypatch.setattr(sys, "argv", [*_arguments(tmp_path, str(source)), "--assets", str(assets)])
    assert module.main() == 0
    package = load_map_package(tmp_path / "regional")
    manifest = json.loads((tmp_path / "regional" / "package.json").read_text(encoding="utf-8"))
    assert package.attribution == "© OpenStreetMap contributors"
    assert manifest["source"] == {"reference": "Archivo autorizado de pruebas", "remote": False}
    assert str(source) not in json.dumps(manifest)
    assert set(manifest["sha256"]) == {"assets/sprite.json", "basemap.pmtiles", "style.json"}
    assert [command[1] for command in commands] == ["extract", "verify"]


def test_remote_source_requires_explicit_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setattr(sys, "argv", _arguments(tmp_path, "https://example.invalid/source.pmtiles"))
    with pytest.raises(SystemExit) as error:
        module._parse_args()
    assert error.value.code == 2


def test_missing_or_unusable_pmtiles_cli_is_reported(tmp_path: Path) -> None:
    module = _module()
    with pytest.raises(module.BuildError, match="No se encuentra"):
        module._pmtiles_version(str(tmp_path / "missing-pmtiles"))


def test_pmtiles_cli_uses_the_supported_version_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="pmtiles 1.28.0\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)

    assert module._pmtiles_version("pmtiles") == "pmtiles 1.28.0"
    assert commands == [["pmtiles", "version"]]


def test_remote_style_is_rejected_before_pmtiles_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    source = tmp_path / "authorised.pmtiles"
    source.write_bytes(b"PMTiles\x03" + bytes(256))
    args = _arguments(tmp_path, str(source))
    style_index = args.index("--style") + 1
    Path(args[style_index]).write_text(
        '{"version": 8, "sprite": "https://cdn.invalid/sprite", "sources": {}, "layers": []}',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit) as error:
        module._parse_args()
    assert error.value.code == 2

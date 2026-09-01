from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest


def _module() -> object:
    path = Path(__file__).parents[1] / "tools" / "prepare_release_candidate.py"
    spec = importlib.util.spec_from_file_location("prepare_release_candidate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _artifacts(root: Path, version: str = "0.1.0") -> tuple[Path, Path]:
    dist = root / "dist"
    dist.mkdir()
    portable = dist / f"GTFS-Explorer-Portable-{version}-win-x64.zip"
    setup = dist / f"GTFS-Explorer-Setup-{version}-win-x64.exe"
    setup.write_bytes(b"setup")
    with zipfile.ZipFile(portable, "w") as archive:
        prefix = "GTFS-Explorer/"
        for name in _module().REQUIRED_PORTABLE_FILES:
            if name in {"manifest.json", "SBOM.cdx.json"}:
                continue
            content = b"{}" if name == "SBOM.cdx.json" else b"x"
            archive.writestr(prefix + name, content)
        archive.writestr(prefix + "manifest.json", json.dumps({"version": version}))
        archive.writestr(prefix + "SBOM.cdx.json", json.dumps({"specVersion": "1.5"}))
    for artifact in (portable, setup):
        artifact.with_suffix(artifact.suffix + ".sha256").write_text(
            f"{_module()._sha256(artifact)}  {artifact.name}\n", encoding="ascii"
        )
    setup.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "installer": {"file": setup.name, "sha256": _module()._sha256(setup)},
                "portable_source": {"file": portable.name, "sha256": _module()._sha256(portable)},
            }
        ),
        encoding="utf-8",
    )
    return portable, setup


def test_verify_accepts_consistent_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _artifacts(tmp_path)
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")

    result = module.verify("0.1.0")

    assert result["portable"]["file"].endswith(".zip")
    assert result["installer"]["file"].endswith(".exe")


def test_verify_rejects_mismatched_sidecar(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module()
    portable, _ = _artifacts(tmp_path)
    portable.with_suffix(".zip.sha256").write_text(
        "0" * 64 + f"  {portable.name}\n", encoding="ascii"
    )
    monkeypatch.setattr(module, "DIST", tmp_path / "dist")

    with pytest.raises(RuntimeError, match="hash lateral"):
        module.verify("0.1.0")

"""Contratos de la infraestructura P1-21; no comprueban tiempos concretos."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from gtfs_explorer.performance import PROFILES, generate_feed
from gtfs_explorer.product import IDENTITY, runtime_build_id


def _benchmark_module() -> Any:
    module_path = Path(__file__).parents[1] / "tools" / "benchmark.py"
    spec = importlib.util.spec_from_file_location("p1_21_benchmark", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profiles_have_expected_scale() -> None:
    assert PROFILES["small"].stop_times == 5_000
    assert 25_000 <= PROFILES["medium"].stop_times <= 75_000
    assert 150_000 <= PROFILES["large"].stop_times <= 300_000


def test_generator_is_deterministic_and_counted(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert generate_feed(first, PROFILES["small"]) == generate_feed(second, PROFILES["small"])
    for name in (
        "agency.txt",
        "routes.txt",
        "stops.txt",
        "trips.txt",
        "stop_times.txt",
        "shapes.txt",
    ):
        assert (
            hashlib.sha256((first / name).read_bytes()).digest()
            == hashlib.sha256((second / name).read_bytes()).digest()
        )


def test_benchmark_json_does_not_contain_identifying_fields() -> None:
    module = _benchmark_module()
    report = module.run("small", {"import"})
    encoded = json.dumps(report)
    assert "username" not in encoded.lower()
    assert "hostname" not in encoded.lower()
    assert "C:\\Users\\" not in encoded
    assert report["product"] == IDENTITY.name
    assert report["app_version"] == IDENTITY.version
    assert report["build_id"] == runtime_build_id()
    assert report["gtfs_spec_revision"] == IDENTITY.gtfs_spec_revision
    assert report["dataset_counts"] == PROFILES["small"].counts()
    assert report["import_result"] == "READY"


def test_benchmark_has_structured_phases_resource_metrics_and_no_paths(tmp_path: Path) -> None:
    module = _benchmark_module()
    report = module._run_single("small", "generate", root=tmp_path / "run")

    assert report["status"] == "PASS"
    assert [event["event"] for event in report["events"]] == [
        "scenario_start",
        "phase_start",
        "phase_end",
    ]
    assert report["phases"]["generate"]["duration_seconds"] > 0
    assert report["storage"]["feed_bytes"] > 0
    assert report["throughput"]["rows"] == sum(PROFILES["small"].counts().values())
    memory = report["memory"]
    assert memory == {"available": False} or memory["working_set_bytes"] >= 0
    encoded = json.dumps(report)
    assert str(tmp_path) not in encoded


def test_benchmark_timeout_isolated_and_matrix_continues(monkeypatch: Any) -> None:
    module = _benchmark_module()
    calls: list[str] = []

    def fake_worker(profile: str, scenario: str, max_duration: float) -> dict[str, object]:
        calls.append(scenario)
        status = "TIMEOUT" if scenario == "generate" else "PASS"
        return {"profile": profile, "scenario": scenario, "status": status}

    monkeypatch.setattr(module, "_run_isolated_scenario", fake_worker)
    report = module.run("small", {"generate", "workspace"}, max_duration=1)

    assert calls == ["generate", "workspace"]
    assert report["scenarios"]["generate"]["status"] == "TIMEOUT"
    assert report["scenarios"]["workspace"]["status"] == "PASS"


def test_worker_timeout_returns_timeout_and_cleans_worker_root(
    tmp_path: Path, monkeypatch: Any
) -> None:
    module = _benchmark_module()
    worker_root = tmp_path / "worker"

    def fake_mkdtemp(prefix: str) -> str:
        del prefix
        worker_root.mkdir()
        return str(worker_root)

    monkeypatch.setattr(module.tempfile, "mkdtemp", fake_mkdtemp)

    result = module._run_isolated_scenario("small", "generate", 0.001)

    assert result["status"] == "TIMEOUT"
    assert not worker_root.exists()

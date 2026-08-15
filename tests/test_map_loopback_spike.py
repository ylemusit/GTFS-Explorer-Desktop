from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from spikes.map_webengine.loopback_spike import PMTILES_BYTES, Evidence, LoopbackMapServer


def _run_spike(script: Path, *arguments: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_loopback_server_requires_token_and_supports_byte_ranges() -> None:
    evidence = Evidence()
    with LoopbackMapServer(evidence, token="test-token") as server:
        request = Request(
            f"{server.origin}/test-token/sample.pmtiles", headers={"Range": "bytes=2-9"}
        )
        with urlopen(request, timeout=2) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes 2-9/{len(PMTILES_BYTES)}"
            assert response.read() == PMTILES_BYTES[2:10]

        with pytest.raises(HTTPError) as missing_token:
            urlopen(f"{server.origin}/wrong/sample.pmtiles", timeout=2)
        assert missing_token.value.code == 404

    assert evidence.requested_ranges == ["bytes=2-9"]
    assert evidence.token_protected


@pytest.mark.integration
def test_webengine_bridge_and_range_contract_are_demonstrated() -> None:
    evidence = _run_spike(Path("spikes/map_webengine/loopback_spike.py"))

    assert evidence["load_ok"]
    assert evidence["bridge_events"] == ["stop:fixture"]
    assert "bytes=0-16383" in evidence["requested_ranges"]
    assert evidence["fetch_status"] == 206
    assert evidence["fetch_content_range"].startswith("bytes ")
    assert evidence["fetched_bytes"] > 0
    assert evidence["map_loaded"]
    assert evidence["pmtiles_spec_version"] == 3
    assert evidence["bridge_roundtrip"] == "python:js-ping"
    assert evidence["rendered_kinds"] == ["route", "stop"]
    assert evidence["map_errors"] == []
    assert evidence["external_requests"] == []
    assert evidence["bound_to_loopback"]
    assert evidence["token_protected"]


@pytest.mark.integration
def test_web_assets_and_pmtiles_open_from_a_unicode_path(tmp_path: Path) -> None:
    unicode_root = tmp_path / "ruta con ñ" / "map_webengine"
    unicode_root.mkdir(parents=True)
    shutil.copy2("spikes/map_webengine/loopback_spike.py", unicode_root / "loopback_spike.py")
    shutil.copytree("spikes/map_webengine/assets", unicode_root / "assets")
    evidence = _run_spike(unicode_root / "loopback_spike.py")

    assert evidence["load_ok"]
    assert evidence["bridge_events"] == ["stop:fixture"]
    assert "bytes=0-16383" in evidence["requested_ranges"]
    assert evidence["fetch_status"] == 206
    assert evidence["external_requests"] == []
    assert evidence["bound_to_loopback"]
    assert evidence["token_protected"]


@pytest.mark.integration
def test_corrupt_pmtiles_fails_locally_without_external_requests() -> None:
    evidence = _run_spike(Path("spikes/map_webengine/loopback_spike.py"), "--corrupt")
    assert evidence["load_ok"]
    assert not evidence["map_loaded"]
    assert any("magic" in message.casefold() for message in evidence["map_errors"])
    assert evidence["external_requests"] == []
    assert evidence["bound_to_loopback"]
    assert evidence["token_protected"]

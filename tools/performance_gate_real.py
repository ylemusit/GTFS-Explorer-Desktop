"""Runner nativo reproducible para el gate de rendimiento, WebEngine y lifecycle.

El proceso padre conserva el informe después de cada escenario. Cada escenario
se ejecuta en un proceso hijo con una ``QApplication`` y un ``QWebEngineView``
reales; los escenarios que cierran proyecto o aplicación quedan aislados para
que un timeout no destruya la evidencia anterior.

La copia temporal es una copia de trabajo del proyecto indicado. Nunca se
escribe en el proyecto fuente ni se incluye el feed en ``artifacts``.
Autor: Yeison Arbey Carrillo Lemus.
Todos los derechos reservados.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUTS: dict[str, float] = {
    "native_8": 60.0,
    "native_20": 90.0,
    "native_79": 120.0,
    "latest_0_79_8": 150.0,
    "latest_8_79_5": 150.0,
    "visible_burst": 120.0,
    "close_project_during_79": 150.0,
    "reopen_after_close": 180.0,
    "close_app_during_79": 180.0,
    "active_native": 90.0,
    "editable_native": 90.0,
    "warm_cache_native": 180.0,
}
SCENARIOS = tuple(DEFAULT_TIMEOUTS)


class ScenarioTimeout(RuntimeError):
    """El escenario no terminó dentro de su presupuesto explícito."""


class ProductFailure(RuntimeError):
    """La instrumentación terminó, pero no se cumplió un criterio de producto."""


class HarnessFailure(RuntimeError):
    """No se pudo obtener evidencia fiable del escenario."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(destination: Path, value: dict[str, object]) -> None:
    """Publica JSON completo mediante reemplazo en el mismo directorio."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_reference(project: Path) -> dict[str, object]:
    descriptor = project / "project.json"
    database = project / "data.duckdb"
    return {
        "path": str(project),
        "project_json_sha256": _sha256(descriptor),
        "database_bytes": database.stat().st_size if database.is_file() else None,
    }


def _parent_environment() -> dict[str, object]:
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "architecture_bits": struct.calcsize("P") * 8,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "performance_gate_opt_in": os.environ.get("GTFS_EXPLORER_PERFORMANCE_GATE") == "1",
    }


def _summary(delays: Iterable[float]) -> dict[str, float | int]:
    ordered = sorted(float(delay) for delay in delays)
    if not ordered:
        return {
            "max_stall_ms": 0.0,
            "p95_stall_ms": 0.0,
            "stalls_gt_100_ms": 0,
            "stalls_gt_200_ms": 0,
            "stalls_gt_500_ms": 0,
            "stalls_gt_1000_ms": 0,
            "sample_count": 0,
        }
    p95_index = min(len(ordered) - 1, max(0, (95 * len(ordered) + 99) // 100 - 1))
    return {
        "max_stall_ms": ordered[-1],
        "p95_stall_ms": ordered[p95_index],
        "stalls_gt_100_ms": sum(delay > 100 for delay in ordered),
        "stalls_gt_200_ms": sum(delay > 200 for delay in ordered),
        "stalls_gt_500_ms": sum(delay > 500 for delay in ordered),
        "stalls_gt_1000_ms": sum(delay > 1000 for delay in ordered),
        "sample_count": len(ordered),
    }


def _child_environment() -> dict[str, object]:
    import PySide6
    from PySide6.QtCore import QLibraryInfo, qVersion

    try:
        from PySide6.QtWebEngineCore import qWebEngineVersion

        webengine_version = str(qWebEngineVersion())
    except (ImportError, AttributeError):
        webengine_version = "unknown"
    return {
        **_parent_environment(),
        "pyside6": str(getattr(PySide6, "__version__", "unknown")),
        "qt": str(qVersion()),
        "qt_webengine": webengine_version,
        "qt_library_path": QLibraryInfo.path(QLibraryInfo.LibraryPath.LibrariesPath),
        "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM"),
        "pid": os.getpid(),
    }


def _timestamp(events: list[dict[str, object]], phase: str, *, last: bool = False) -> int | None:
    selected: list[int] = []
    for event in events:
        value = event.get("monotonic_ns")
        if event.get("phase") == phase and isinstance(value, int):
            selected.append(value)
    if not selected:
        return None
    return selected[-1] if last else selected[0]


def _duration_seconds(start: int | None, finish: int | None) -> float | None:
    if start is None or finish is None or finish < start:
        return None
    return (finish - start) / 1_000_000_000


def _pipeline_by_generation(
    events: list[dict[str, object]], js_timings: list[dict[str, object]]
) -> dict[str, dict[str, object]]:
    generations: set[int] = set()
    for event in events:
        value = event.get("generation")
        if isinstance(value, int):
            generations.add(value)
    for timing in js_timings:
        value = timing.get("generation_id")
        if isinstance(value, int):
            generations.add(value)
    result: dict[str, dict[str, object]] = {}
    for generation in sorted(generations):
        group = [event for event in events if event.get("generation") == generation]
        request = _timestamp(group, "T0_REQUEST_RECEIVED")
        worker_started = _timestamp(group, "T2_WORKER_STARTED")
        worker_finished = _timestamp(group, "T7_PAYLOAD_BUILT", last=True)
        serialization_started = _timestamp(group, "T8_SERIALIZATION_STARTED")
        serialization_finished = _timestamp(group, "T8_SERIALIZATION_FINISHED", last=True)
        result_received = _timestamp(group, "T9_RESULT_RECEIVED_GUI")
        webengine_started = _timestamp(group, "T11_RUNJAVASCRIPT_STARTED")
        timings = [timing for timing in js_timings if timing.get("generation_id") == generation]
        js = timings[-1] if timings else None
        maplibre_received = _timestamp(group, "T13_MAPLIBRE_TIMINGS_RECEIVED", last=True)
        record: dict[str, object] = {
            "generation_id": generation,
            "request_at_ns": request,
            "worker_started": worker_started is not None,
            "worker_finished": worker_finished is not None,
            "python_result_received": result_received is not None,
            "stale_decision": _timestamp(group, "T9_STALE_RESULT_DISCARDED") is not None,
            "runJavaScript_called": webengine_started is not None,
            "setData_called": js is not None,
            "worker_compute_s": _duration_seconds(worker_started, worker_finished),
            "gui_serialization_s": _duration_seconds(serialization_started, serialization_finished),
            "qt_webengine_transfer_s": _duration_seconds(webengine_started, maplibre_received),
            "total_request_to_idle_s": _duration_seconds(request, maplibre_received),
            "payload_bytes": next(
                (
                    event.get("payload_bytes")
                    for event in reversed(group)
                    if isinstance(event.get("payload_bytes"), int)
                ),
                None,
            ),
            "js_timings": js,
        }
        result[str(generation)] = record
    return result


def _phase_heartbeat(
    samples: Iterable[Mapping[str, object]], events: list[dict[str, object]]
) -> dict[str, object]:
    windows: dict[str, list[tuple[int, int]]] = {
        "WORKER_COMPUTE": [],
        "GUI_SERIALIZATION": [],
        "QT_WEBENGINE_TRANSFER": [],
    }
    generations: set[int] = set()
    for event in events:
        value = event.get("generation")
        if isinstance(value, int):
            generations.add(value)
    for generation in generations:
        group = [event for event in events if event.get("generation") == generation]
        for phase, start_name, end_name in (
            ("WORKER_COMPUTE", "T2_WORKER_STARTED", "T7_PAYLOAD_BUILT"),
            ("GUI_SERIALIZATION", "T8_SERIALIZATION_STARTED", "T8_SERIALIZATION_FINISHED"),
            ("QT_WEBENGINE_TRANSFER", "T11_RUNJAVASCRIPT_STARTED", "T13_MAPLIBRE_TIMINGS_RECEIVED"),
        ):
            start = _timestamp(group, start_name)
            finish = _timestamp(group, end_name, last=True)
            if start is not None and finish is not None and finish >= start:
                windows[phase].append((start, finish))

    by_phase: dict[str, object] = {}
    for phase, phase_windows in windows.items():
        phase_samples: list[float] = []
        for sample in samples:
            expected = sample.get("expected_ns")
            delay = sample.get("delay_ms")
            if (
                isinstance(expected, int)
                and isinstance(delay, (int, float))
                and any(start <= expected <= finish for start, finish in phase_windows)
            ):
                phase_samples.append(float(delay))
        by_phase[phase] = _summary(phase_samples)
    by_phase["MAPLIBRE_APPLY"] = {
        "measurement": "JS performance.now; no GUI heartbeat samples",
        **_summary(()),
    }
    by_phase["MAPLIBRE_IDLE"] = {
        "measurement": "JS idle event; no GUI heartbeat samples",
        **_summary(()),
    }
    return by_phase


def _safe_tail(value: str, limit: int = 4000) -> str:
    return value[-limit:]


def _wait_until(
    app: Any, predicate: Callable[[], bool], timeout_s: float, *, interval_ms: int = 10
) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(interval_ms)
    result = {"value": False}

    def finish(value: bool) -> None:
        if loop.isRunning():
            result["value"] = value
            loop.quit()

    def check() -> None:
        if predicate():
            finish(True)

    poll.timeout.connect(check)
    poll.start()
    QTimer.singleShot(max(1, int(timeout_s * 1000)), lambda: finish(False))
    check()
    loop.exec()
    poll.stop()
    return bool(result["value"])


class _WindowsResponsivenessProbe:
    """Consulta IsHungAppWindow sin afirmar nada si no hay HWND observable."""

    def __init__(self, window: Any, parent: Any) -> None:
        from PySide6.QtCore import QTimer

        self.window = window
        self.available = sys.platform == "win32"
        self.samples: list[dict[str, object]] = []
        self._user32: Any = None
        if self.available:
            try:
                import ctypes

                self._user32 = ctypes.windll.user32
                self._user32.IsHungAppWindow.argtypes = [ctypes.c_void_p]
                self._user32.IsHungAppWindow.restype = ctypes.c_bool
            except (AttributeError, OSError):
                self.available = False
        self.timer = QTimer(parent)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.timer.start()

    def reset(self) -> None:
        self.samples.clear()

    def stop(self) -> None:
        self.timer.stop()

    def _tick(self) -> None:
        if not self.available or self._user32 is None:
            return
        try:
            hwnd = int(self.window.winId())
            self.samples.append(
                {
                    "observed_at_ns": time.perf_counter_ns(),
                    "hung": bool(self._user32.IsHungAppWindow(hwnd)),
                }
            )
        except (AttributeError, OSError, TypeError, ValueError):
            self.available = False

    def summary(self) -> dict[str, object]:
        if not self.samples:
            return {"status": "NOT MEASURED", "sample_count": 0, "hung_samples": 0}
        hung = sum(bool(sample["hung"]) for sample in self.samples)
        return {
            "status": "YES" if hung else "NO",
            "sample_count": len(self.samples),
            "hung_samples": hung,
        }


class _NativeProbe:
    """Controlador de una sesión real de MainWindow, EditorWidget y WebEngine."""

    def __init__(self, project: Path) -> None:
        from PySide6.QtWidgets import QApplication

        from gtfs_explorer.application.commands.open_project import OpenProject
        from gtfs_explorer.performance_gate import GateTrace, QtHeartbeat
        from gtfs_explorer.presentation.desktop.main_window import MainWindow

        self.project = project
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.trace = GateTrace()
        self.js_timings: list[dict[str, object]] = []
        self.uncorrelated_js_timings: list[dict[str, object]] = []
        self.protocol_errors: list[str] = []
        self.map_errors: list[str] = []
        self.session_ids: list[str] = []
        self.close_project_at_ns: int | None = None
        self.close_app_request_at_ns: int | None = None
        self.close_app_event_loop_returned_at_ns: int | None = None
        self.close_app_threadpool_wait_started_at_ns: int | None = None
        self.close_app_threadpool_wait_finished_at_ns: int | None = None
        self.scenario_details: dict[str, object] | None = None
        self.window = MainWindow()
        self.window.resize(1400, 900)
        self.map_widget = self.window._explorer.map_widget  # noqa: SLF001 - native gate
        map_widget = self.map_widget
        if map_widget is None:
            raise HarnessFailure("RouteExplorerWidget no creó un MapWidget real.")
        self.editor = self.window._editor  # noqa: SLF001 - native gate
        map_widget._bridge.event_received.connect(self._event_received)  # noqa: SLF001
        map_widget._bridge.protocol_error.connect(self.protocol_errors.append)  # noqa: SLF001
        self.editor._performance_trace = self.trace  # noqa: SLF001 - opt-in del gate
        map_widget._performance_trace = self.trace  # noqa: SLF001 - opt-in del gate
        self.heartbeat = QtHeartbeat(interval_ms=25, parent=self.app)
        self.windows_probe = _WindowsResponsivenessProbe(self.window, self.app)
        self.windows_probe.start()
        self._open_project(OpenProject)
        self.window.show()
        self.window._navigation.setCurrentRow(1)  # noqa: SLF001
        if not _wait_until(
            self.app,
            lambda: bool(map_widget._bridge.ready),  # noqa: SLF001
            45.0,
        ):
            raise HarnessFailure("El bridge nativo no llegó a mapReady durante la preparación.")
        self.window._explorer.refresh()  # noqa: SLF001
        self.window._explore_tabs.setCurrentWidget(self.editor)  # noqa: SLF001

        def initial_map_ready() -> bool:
            return (
                bool(map_widget._bridge.ready)  # noqa: SLF001
                and bool(self.editor._map_rendered)  # noqa: SLF001
                and bool(self.js_timings or self.uncorrelated_js_timings)
            )

        if not _wait_until(
            self.app,
            initial_map_ready,
            45.0,
        ):
            js_generations = sorted(
                {timing.get("generation_id") for timing in self.js_timings}, key=str
            )
            last_js = self.js_timings[-1] if self.js_timings else None
            raise HarnessFailure(
                "El mapa nativo no llegó a bridge_ready + payload + idle durante la preparación: "
                f"bridge_ready={map_widget._bridge.ready}, "  # noqa: SLF001
                f"map_rendered={self.editor._map_rendered}, "  # noqa: SLF001
                f"generation={int(self.editor._map_rebuild_token)}, "  # noqa: SLF001
                f"js_timings={len(self.js_timings)}, "
                f"js_generations={js_generations!r}, last_js={last_js!r}, "
                f"map_errors={self.map_errors!r}, "
                f"protocol_errors={self.protocol_errors!r}."
            )
        self.trace = GateTrace()
        self.editor._performance_trace = self.trace  # noqa: SLF001
        map_widget._performance_trace = self.trace  # noqa: SLF001
        self.js_timings.clear()
        self.uncorrelated_js_timings.clear()
        self.protocol_errors.clear()
        self.map_errors.clear()
        self.windows_probe.reset()
        self.heartbeat.start()
        self.started_at_ns = time.perf_counter_ns()

    def _open_project(self, open_project_type: Any) -> None:
        opened = open_project_type(self.project).execute()
        self.window._opened_project = opened  # noqa: SLF001 - controlled native fixture
        self.session_ids.append(str(uuid4()))
        self.window.project_opened()  # noqa: SLF001

    def reopen_project(self) -> None:
        from gtfs_explorer.application.commands.open_project import OpenProject

        self._open_project(OpenProject)
        self.window._navigation.setCurrentRow(1)  # noqa: SLF001
        self.window._explorer.refresh()  # noqa: SLF001
        self.window._explore_tabs.setCurrentWidget(self.editor)  # noqa: SLF001

    def _event_received(self, event: object) -> None:
        name = getattr(event, "event", None)
        payload = getattr(event, "payload", {})
        if name == "mapError":
            self.map_errors.append(str(payload))
            return
        if name != "performanceTimings" or not isinstance(payload, dict):
            return
        timing = dict(payload)
        timing["python_received_at_ns"] = time.perf_counter_ns()
        generation = timing.get("generation_id")
        if isinstance(generation, int) and not isinstance(generation, bool):
            self.js_timings.append(timing)
            self.trace.mark("T13_MAPLIBRE_TIMINGS_RECEIVED", generation=generation)
        else:
            self.uncorrelated_js_timings.append(timing)

    def _has_event(self, phase: str, generation: int) -> bool:
        return any(
            event.phase == phase and event.generation == generation for event in self.trace.events
        )

    def _has_js_timing(self, generation: int) -> bool:
        return any(timing.get("generation_id") == generation for timing in self.js_timings)

    def route_ids(self) -> tuple[str, ...]:
        session = self.window._get_editor_session()  # noqa: SLF001
        if session is None:
            raise HarnessFailure("No se pudo crear la sesión del editor nativo.")
        return tuple(sorted(session.working_copy.entity_index.routes_by_id))

    def _session(self) -> Any:
        session = self.window._get_editor_session()  # noqa: SLF001
        if session is None:
            raise HarnessFailure("La sesión del editor no está disponible.")
        return session

    def set_visible_routes(
        self, selected: frozenset[str], *, persist: bool = True
    ) -> tuple[int, frozenset[str]]:
        from dataclasses import replace

        session = self._session()
        before = dict(session.working_copy.route_states)
        updates = tuple(
            replace(
                session.working_copy.route_state(route_id),
                visible=route_id in selected,
            )
            for route_id in self.route_ids()
        )
        if persist:
            session.set_route_workspace_states(updates)
        else:
            for state in updates:
                session.working_copy.set_route_workspace_state(state)
        after = dict(session.working_copy.route_states)
        self.editor._apply_route_state_view(  # noqa: SLF001
            before, after, geometry_changed=True, fit=False
        )
        generation = int(self.editor._map_rebuild_token)  # noqa: SLF001
        return generation, selected

    def set_visual_state(self, field: str, route_id: str, value: bool) -> None:
        from dataclasses import replace

        if field not in {"active", "editable", "locked", "dimmed"}:
            raise HarnessFailure(f"Campo visual no admitido por el escenario: {field}")
        session = self._session()
        before = dict(session.working_copy.route_states)
        updates: list[Any] = []
        for candidate in self.route_ids():
            state = session.working_copy.route_state(candidate)
            if field == "active":
                state = replace(state, active=value if candidate == route_id else False)
            elif candidate == route_id:
                state = replace(state, **{field: value})
            updates.append(state)
        session.set_route_workspace_states(tuple(updates))
        after = dict(session.working_copy.route_states)
        self.editor._apply_route_state_view(  # noqa: SLF001
            before, after, geometry_changed=False, fit=False
        )

    def wait_generation(
        self, generation: int, timeout_s: float, *, worker_only: bool = False
    ) -> None:
        if not _wait_until(
            self.app,
            lambda: self._has_event("T7_PAYLOAD_BUILT", generation)
            and (worker_only or self._has_js_timing(generation)),
            timeout_s,
        ):
            detail = "; ".join(self.map_errors + self.protocol_errors)
            raise ScenarioTimeout(
                f"La generación {generation} no completó pipeline/idle en {timeout_s:.1f}s"
                + (f" ({detail})" if detail else "")
            )

    def wait_worker_started(self, generation: int, timeout_s: float) -> None:
        if not _wait_until(
            self.app, lambda: self._has_event("T2_WORKER_STARTED", generation), timeout_s
        ):
            raise ScenarioTimeout(
                f"La generación {generation} no inició worker en {timeout_s:.1f}s"
            )

    @staticmethod
    def _dismiss_dirty_prompt() -> None:
        from PySide6.QtWidgets import QApplication, QMessageBox

        for widget in QApplication.topLevelWidgets():
            if not isinstance(widget, QMessageBox):
                continue
            for button in widget.buttons():
                if button.text().startswith("Descartar"):
                    button.click()
                    return

    def close_project(self) -> bool:
        from PySide6.QtCore import QTimer

        self.close_project_at_ns = time.perf_counter_ns()
        QTimer.singleShot(0, self._dismiss_dirty_prompt)
        return bool(self.window._close_project())  # noqa: SLF001

    def _prepare_selection(self, count: int, timeout_s: float) -> tuple[int, dict[str, object]]:
        ids = self.route_ids()
        if len(ids) < count:
            raise HarnessFailure(
                f"El proyecto solo contiene {len(ids)} rutas; se requieren {count}."
            )
        generation, _ = self.set_visible_routes(frozenset(ids[:count]))
        self.wait_generation(generation, timeout_s)
        timing = next(
            (
                timing
                for timing in reversed(self.js_timings)
                if timing.get("generation_id") == generation
            ),
            {},
        )
        final_routes = timing.get("final_visible_routes")
        if final_routes != count:
            raise ProductFailure(
                f"MapLibre informó {final_routes!r} rutas visibles; se esperaban {count}."
            )
        return generation, timing

    def run_native(self, count: int, timeout_s: float) -> dict[str, object]:
        generation, timing = self._prepare_selection(count, timeout_s)
        result: dict[str, object] = {
            "generation_id": generation,
            "compute": self._generation_value(generation, "worker_compute_s"),
            "serialization": self._generation_value(generation, "gui_serialization_s"),
            "webengine": self._generation_value(generation, "qt_webengine_transfer_s"),
            "maplibre": timing,
            "total": self._generation_value(generation, "total_request_to_idle_s"),
            "final_visible_routes": timing.get("final_visible_routes"),
            "windows_not_responding": self.windows_probe.summary(),
        }
        self.scenario_details = result
        heartbeat = self.heartbeat.summary()
        if int(heartbeat["stalls_gt_1000_ms"]) > 0:
            raise ProductFailure(f"Native {count} registró stall GUI >1 s: {result!r}")
        return result

    def _generation_value(self, generation: int, key: str) -> object:
        records = _pipeline_by_generation(self.trace.snapshot()["events"], self.js_timings)
        return records.get(str(generation), {}).get(key)

    def run_latest(
        self, initial_count: int, final_count: int, timeout_s: float
    ) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 79 or len(ids) < final_count:
            raise HarnessFailure("Latest-wins requiere las 79 rutas del AcceptanceFeedTest.")
        initial_generation, _ = self.set_visible_routes(frozenset(ids[:initial_count]))
        self.wait_generation(initial_generation, min(60.0, timeout_s))
        stale_generation, _ = self.set_visible_routes(frozenset(ids[:79]))
        self.wait_worker_started(stale_generation, 10.0)
        final_generation, _ = self.set_visible_routes(frozenset(ids[:final_count]))
        self.wait_generation(final_generation, timeout_s)
        if not _wait_until(
            self.app,
            lambda: self._has_event("T7_PAYLOAD_BUILT", stale_generation),
            timeout_s,
        ):
            raise ScenarioTimeout(f"El worker obsoleto {stale_generation} no terminó.")
        stale_js = any(
            timing.get("generation_id") == stale_generation for timing in self.js_timings
        )
        stale_run_js = self._generation_value(stale_generation, "runJavaScript_called")
        final_timing = next(
            (
                timing
                for timing in reversed(self.js_timings)
                if timing.get("generation_id") == final_generation
            ),
            {},
        )
        if stale_js or stale_run_js or final_timing.get("final_visible_routes") != final_count:
            raise ProductFailure(
                f"Latest-wins incumplido: stale_js={stale_js}, stale_runJavaScript={stale_run_js}, "
                f"final={final_timing.get('final_visible_routes')!r}."
            )
        return {
            "initial_count": initial_count,
            "generation_initial": initial_generation,
            "generation_79": {
                "generation_id": stale_generation,
                "worker_started": self._has_event("T2_WORKER_STARTED", stale_generation),
                "worker_finished": self._has_event("T7_PAYLOAD_BUILT", stale_generation),
                "python_result_received": self._has_event(
                    "T9_RESULT_RECEIVED_GUI", stale_generation
                ),
                "stale_decision": self._has_event("T9_STALE_RESULT_DISCARDED", stale_generation),
                "runJavaScript_called": bool(stale_run_js),
                "setData_called": stale_js,
            },
            "generation_final": final_generation,
            "final_visible_routes": final_timing.get("final_visible_routes"),
        }

    def run_visible_burst(self, timeout_s: float) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 8:
            raise HarnessFailure("Visible burst requiere al menos 8 rutas.")
        events: list[frozenset[str]] = []
        for index in range(100):
            count = 1 + (index % min(79, len(ids)))
            events.append(frozenset(ids[:count]))
        from PySide6.QtCore import QTimer

        state = {"index": 0}

        def fire_next() -> None:
            index = state["index"]
            self.set_visible_routes(events[index], persist=False)
            state["index"] = index + 1
            if state["index"] < len(events):
                QTimer.singleShot(10, fire_next)
            else:
                QTimer.singleShot(
                    10,
                    lambda: self.set_visible_routes(frozenset(ids[:8]), persist=False),
                )

        QTimer.singleShot(0, fire_next)
        if not _wait_until(
            self.app,
            lambda: bool(self.js_timings)
            and self.js_timings[-1].get("final_visible_routes") == 8
            and time.perf_counter_ns() - self.started_at_ns >= 1_150_000_000,
            timeout_s,
        ):
            raise ScenarioTimeout("La ráfaga de Visible no alcanzó la última selección 8 → idle.")
        input_events = len(events) + 1
        payloads_applied = len(self.js_timings)
        result: dict[str, object] = {
            "input_events": input_events,
            "debounce_fires": self._count_phase("T1_DEBOUNCE_COMPLETED"),
            "generation_requests": self._count_phase("T0_REQUEST_RECEIVED"),
            "workers_started": self._count_phase("T2_WORKER_STARTED"),
            "workers_finished": self._count_phase("T7_PAYLOAD_BUILT"),
            "results_discarded": self.trace.snapshot()["counters"].get(
                "stale_results_discarded", 0
            ),
            "payloads_applied": payloads_applied,
            "final_visible_routes": self.js_timings[-1].get("final_visible_routes"),
        }
        if payloads_applied >= input_events:
            raise ProductFailure(f"La ráfaga no coalesció actualizaciones: {result!r}")
        return result

    def _count_phase(self, phase: str) -> int:
        return sum(event.phase == phase for event in self.trace.events)

    def run_close_project(self, timeout_s: float) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 79:
            raise HarnessFailure("Close project requiere las 79 rutas del AcceptanceFeedTest.")
        generation, _ = self.set_visible_routes(frozenset(ids[:79]))
        self.wait_worker_started(generation, 10.0)
        requested = time.perf_counter_ns()
        closed = self.close_project()
        closed_at = time.perf_counter_ns()
        if not closed:
            raise ProductFailure("MainWindow rechazó el cierre del proyecto durante el worker.")
        if not _wait_until(
            self.app, lambda: self._has_event("T7_PAYLOAD_BUILT", generation), timeout_s
        ):
            raise ScenarioTimeout("El worker de cierre de proyecto no terminó.")
        close_latency = (closed_at - requested) / 1_000_000_000
        post_close_events = [
            event
            for event in self.trace.events
            if event.generation == generation
            and isinstance(event.monotonic_ns, int)
            and event.monotonic_ns >= closed_at
            and event.phase in {"T10_MAPWIDGET_SHOW_PAYLOAD", "T11_RUNJAVASCRIPT_STARTED"}
        ]
        ignored = not post_close_events
        result = {
            "generation_id": generation,
            "close_requested_at": requested,
            "project_closed_at": closed_at,
            "close_latency_s": close_latency,
            "worker_finished": self._has_event("T7_PAYLOAD_BUILT", generation),
            "result_ignored": ignored,
            "runJavaScript_called_after_close": any(
                event.phase == "T11_RUNJAVASCRIPT_STARTED" for event in post_close_events
            ),
            "exception": "NONE",
            "crash": "NO",
        }
        if close_latency > 2.0 or not ignored:
            raise ProductFailure(f"Cierre de proyecto incumplido: {result!r}")
        return result

    def run_reopen(self, timeout_s: float) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 79:
            raise HarnessFailure("Reopen requiere las 79 rutas del AcceptanceFeedTest.")
        old_session = self.session_ids[-1]
        old_generation, _ = self.set_visible_routes(frozenset(ids[:79]))
        self.wait_worker_started(old_generation, 10.0)
        requested = time.perf_counter_ns()
        if not self.close_project():
            raise ProductFailure("No se pudo cerrar el proyecto antes de reabrirlo.")
        closed_at = time.perf_counter_ns()
        self.reopen_project()
        reopened_at = time.perf_counter_ns()
        new_session = self.session_ids[-1]
        new_ids = self.route_ids()
        new_generation, _ = self.set_visible_routes(frozenset(new_ids[:8]))
        self.wait_generation(new_generation, timeout_s)
        if not _wait_until(
            self.app, lambda: self._has_event("T7_PAYLOAD_BUILT", old_generation), timeout_s
        ):
            raise ScenarioTimeout("El worker anterior no terminó después de reabrir.")
        close_latency = (closed_at - requested) / 1_000_000_000
        final_timing = next(
            (
                timing
                for timing in reversed(self.js_timings)
                if timing.get("generation_id") == new_generation
            ),
            {},
        )
        old_applied = any(
            timing.get("generation_id") == old_generation for timing in self.js_timings
        )
        result = {
            "old_session_id": old_session,
            "new_session_id": new_session,
            "old_generation": old_generation,
            "new_generation": new_generation,
            "new_generation_namespace_coherent": new_generation > old_generation,
            "close_latency_s": close_latency,
            "reopened_at": reopened_at,
            "old_worker_finished": self._has_event("T7_PAYLOAD_BUILT", old_generation),
            "old_result_applied": old_applied,
            "new_map_final_visible_routes": final_timing.get("final_visible_routes"),
            "old_callbacks": sum(
                event.generation == old_generation and event.phase == "T9_RESULT_RECEIVED_GUI"
                for event in self.trace.events
            ),
            "new_callbacks_from_old_session": sum(
                event.generation == old_generation
                and event.phase in {"T10_MAPWIDGET_SHOW_PAYLOAD", "T11_RUNJAVASCRIPT_STARTED"}
                and event.monotonic_ns >= reopened_at
                for event in self.trace.events
            ),
            "exception": "NONE",
            "crash": "NO",
        }
        if (
            close_latency > 2.0
            or not result["new_generation_namespace_coherent"]
            or result["old_result_applied"]
            or result["new_map_final_visible_routes"] != 8
            or result["new_callbacks_from_old_session"] != 0
        ):
            raise ProductFailure(f"Reapertura tras worker obsoleto incumplida: {result!r}")
        return result

    def run_close_app(self, timeout_s: float) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 79:
            raise HarnessFailure("Close app requiere las 79 rutas del AcceptanceFeedTest.")
        generation, _ = self.set_visible_routes(frozenset(ids[:79]))
        self.wait_worker_started(generation, 10.0)
        from PySide6.QtCore import QThreadPool, QTimer

        def request_close() -> None:
            self.close_app_request_at_ns = time.perf_counter_ns()
            accepted = bool(self.window.close())
            if not accepted or self.window.isVisible():
                self.app.quit()

        # La petición debe entrar primero: ``window.close()`` puede abrir el
        # diálogo modal de borrador y el dismiss se ejecuta entonces dentro
        # del event loop anidado de QMessageBox.
        QTimer.singleShot(0, request_close)
        QTimer.singleShot(0, self._dismiss_dirty_prompt)
        self.app.exec()
        self.close_app_event_loop_returned_at_ns = time.perf_counter_ns()
        self.close_app_threadpool_wait_started_at_ns = time.perf_counter_ns()
        QThreadPool.globalInstance().waitForDone(max(1, int(timeout_s * 1000)))
        self.close_app_threadpool_wait_finished_at_ns = time.perf_counter_ns()
        worker_finished = self._has_event("T7_PAYLOAD_BUILT", generation)
        app_closed_at = self.close_app_event_loop_returned_at_ns or 0
        elapsed = None
        if self.close_app_request_at_ns is not None:
            elapsed = (
                self.close_app_threadpool_wait_finished_at_ns - self.close_app_request_at_ns
            ) / 1e9
        result: dict[str, object] = {
            "generation_id": generation,
            "close_requested_at": self.close_app_request_at_ns,
            "event_loop_returned_at": self.close_app_event_loop_returned_at_ns,
            "threadpool_wait_started_at": self.close_app_threadpool_wait_started_at_ns,
            "threadpool_wait_finished_at": self.close_app_threadpool_wait_finished_at_ns,
            "close_latency_s": elapsed,
            "qthreadpool_worker_finished": worker_finished,
            "worker_finishing_state": "FINISHED" if worker_finished else "NOT OBSERVED",
            "gui_callbacks_after_app_close": sum(
                event.phase == "T9_RESULT_RECEIVED_GUI"
                and event.generation == generation
                and event.monotonic_ns >= app_closed_at
                for event in self.trace.events
            ),
            "runJavaScript_after_app_close": sum(
                event.phase == "T11_RUNJAVASCRIPT_STARTED"
                and event.generation == generation
                and event.monotonic_ns >= app_closed_at
                for event in self.trace.events
            ),
            "exceptions": [],
            "process_exit_code": 0,
            "classification": "BLOCKER_QTHREADPOOL_WAIT"
            if elapsed is not None and elapsed > 10.0
            else "PASS",
        }
        self.scenario_details = result
        if result["classification"] != "PASS":
            raise ProductFailure(f"Cierre de aplicación bloqueado por worker: {result!r}")
        return result

    def run_active_editable(self, field: str, timeout_s: float) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 8:
            raise HarnessFailure(f"{field} requiere 8 rutas.")
        generation, _ = self._prepare_selection(8, timeout_s)
        before_generation = int(self.editor._map_rebuild_token)  # noqa: SLF001
        before_applied = len(self.js_timings)
        before_workers = self._count_phase("T2_WORKER_STARTED")
        for route_id in ids[: min(5, 8)]:
            self.set_visual_state(field, route_id, True)
        if field == "editable":
            self.set_visual_state("editable", ids[0], False)
            self.set_visual_state("editable", ids[0], True)
        stable_after = time.perf_counter() + 0.35
        if not _wait_until(self.app, lambda: time.perf_counter() >= stable_after, 0.5):
            raise HarnessFailure("No se pudo dejar estabilizar el estado visual nativo.")
        after_generation = int(self.editor._map_rebuild_token)  # noqa: SLF001
        after_applied = len(self.js_timings)
        expected_route = ids[4] if field == "active" else ids[0]
        final_state = self._session().working_copy.route_state(expected_route)
        visual_state_updated = bool(
            final_state.active if field == "active" else final_state.editable
        )
        result = {
            "baseline_generation": generation,
            "generation_before": before_generation,
            "generation_after": after_generation,
            "full_payloads_before": before_applied,
            "full_payloads_after": after_applied,
            "geometry_worker_started_after": (
                self._count_phase("T2_WORKER_STARTED") - before_workers
            ),
            "maplibre_full_setData_after": after_applied - before_applied,
            "visual_state_updated": visual_state_updated,
            "final_visible_routes": self.js_timings[-1].get("final_visible_routes")
            if self.js_timings
            else None,
        }
        if (
            after_generation != before_generation
            or after_applied != before_applied
            or not visual_state_updated
        ):
            raise ProductFailure(f"{field} provocó una regeneración geométrica: {result!r}")
        return result

    def run_warm_cache(self, timeout_s: float) -> dict[str, object]:
        ids = self.route_ids()
        if len(ids) < 20:
            raise HarnessFailure("Warm cache requiere al menos 20 rutas.")
        sequence = (8, 20, 8, 20, 20)
        steps: list[dict[str, object]] = []
        previous_counters: dict[str, int] = {}
        for count in sequence:
            generation, timing = self._prepare_selection(count, timeout_s)
            counters = {
                key: int(value)
                for key, value in self.trace.snapshot()["counters"].items()
                if isinstance(value, int)
            }
            delta = {key: counters.get(key, 0) - previous_counters.get(key, 0) for key in counters}
            cache_hit = delta.get("visible_set_cache_hits", 0) > 0
            steps.append(
                {
                    "routes": count,
                    "generation_id": generation,
                    "visible_composition_cache_hit": cache_hit,
                    "counter_delta": delta,
                    "compute": self._generation_value(generation, "worker_compute_s"),
                    "payload_bytes": self._generation_value(generation, "payload_bytes"),
                    "webengine_applied": self._generation_value(generation, "setData_called"),
                    "maplibre": timing,
                }
            )
            previous_counters = counters
        last = steps[-1]
        if not bool(last["visible_composition_cache_hit"]):
            raise ProductFailure(
                f"La repetición final de 20 no obtuvo hit de composición: {steps!r}"
            )
        return {
            "sequence": steps,
            "composition_hit_retransmits_full_payload": bool(last["webengine_applied"]),
            "known_cost": (
                "composition cache HIT still transfers the complete payload to WebEngine"
                if bool(last["webengine_applied"])
                else "NOT OBSERVED"
            ),
        }

    def finish(
        self,
        scenario: str,
        status: str,
        timeout_s: float,
        *,
        started_at: str | None = None,
        **extra: object,
    ) -> dict[str, object]:
        self.heartbeat.stop()
        self.windows_probe.stop()
        events = self.trace.snapshot()["events"]
        heartbeat_samples = self.heartbeat.samples()
        pipeline = _pipeline_by_generation(events, self.js_timings)
        result: dict[str, object] = {
            "scenario_name": scenario,
            "started_at": started_at or _utc_now(),
            "finished_at": _utc_now(),
            "status": status,
            "timeout": timeout_s,
            "error": extra.pop("error", None),
            "environment": _child_environment(),
            "session_ids": list(self.session_ids),
            "generations": pipeline,
            "heartbeat": {
                "interval_ms": self.heartbeat.interval_ms,
                "overall": self.heartbeat.summary(),
                "phases": _phase_heartbeat(heartbeat_samples, events),
                "samples": len(heartbeat_samples),
            },
            "pipeline": pipeline,
            "maplibre_timings": list(self.js_timings),
            "uncorrelated_maplibre_timings": len(self.uncorrelated_js_timings),
            "final_visible_routes": (
                self.js_timings[-1].get("final_visible_routes") if self.js_timings else None
            ),
            "windows_not_responding": self.windows_probe.summary(),
            "counters": self.trace.snapshot()["counters"],
            "events": events,
            "errors": {"protocol": list(self.protocol_errors), "map": list(self.map_errors)},
            "scenario_details": self.scenario_details,
            **extra,
        }
        return result

    def close(self) -> None:
        self.heartbeat.stop()
        self.windows_probe.stop()
        try:
            if self.window._opened_project is not None:  # noqa: SLF001
                from PySide6.QtCore import QTimer

                QTimer.singleShot(0, self._dismiss_dirty_prompt)
                self.window._close_project()  # noqa: SLF001
        except (RuntimeError, TypeError, ValueError):
            pass
        try:
            self.window.close()
            self.app.processEvents()
        except (RuntimeError, TypeError):
            pass


def _dispatch_child(probe: _NativeProbe, scenario: str, timeout_s: float) -> dict[str, object]:
    if scenario == "native_8":
        return probe.run_native(8, timeout_s)
    if scenario == "native_20":
        return probe.run_native(20, timeout_s)
    if scenario == "native_79":
        return probe.run_native(79, timeout_s)
    if scenario == "latest_0_79_8":
        return probe.run_latest(0, 8, timeout_s)
    if scenario == "latest_8_79_5":
        return probe.run_latest(8, 5, timeout_s)
    if scenario == "visible_burst":
        return probe.run_visible_burst(timeout_s)
    if scenario == "close_project_during_79":
        return probe.run_close_project(timeout_s)
    if scenario == "reopen_after_close":
        return probe.run_reopen(timeout_s)
    if scenario == "close_app_during_79":
        return probe.run_close_app(timeout_s)
    if scenario == "active_native":
        return probe.run_active_editable("active", timeout_s)
    if scenario == "editable_native":
        return probe.run_active_editable("editable", timeout_s)
    if scenario == "warm_cache_native":
        return probe.run_warm_cache(timeout_s)
    raise HarnessFailure(f"Escenario no reconocido: {scenario}")


def _child_main(args: argparse.Namespace) -> int:
    os.environ["GTFS_EXPLORER_PERFORMANCE_GATE"] = "1"
    started = _utc_now()
    probe: _NativeProbe | None = None
    result: dict[str, object]
    failure_kind: str | None = None
    try:
        probe = _NativeProbe(args.project.resolve())
        extra = _dispatch_child(probe, args.scenario, args.timeout)
        result = probe.finish(args.scenario, "PASS", args.timeout, started_at=started, **extra)
    except ScenarioTimeout as error:
        failure_kind = "HARNESS_FAILURE"
        if probe is not None:
            result = probe.finish(
                args.scenario,
                "TIMEOUT",
                args.timeout,
                started_at=started,
                error=f"{type(error).__name__}: {error}",
            )
        else:
            result = {
                "scenario_name": args.scenario,
                "started_at": started,
                "finished_at": _utc_now(),
                "status": "TIMEOUT",
                "timeout": args.timeout,
                "error": f"{type(error).__name__}: {error}",
            }
    except ProductFailure as error:
        failure_kind = "PRODUCT_FAILURE"
        if probe is not None:
            result = probe.finish(
                args.scenario,
                "FAIL",
                args.timeout,
                started_at=started,
                error=f"{type(error).__name__}: {error}",
            )
        else:
            result = {
                "scenario_name": args.scenario,
                "started_at": started,
                "finished_at": _utc_now(),
                "status": "FAIL",
                "timeout": args.timeout,
                "error": f"{type(error).__name__}: {error}",
            }
    except Exception as error:  # pragma: no cover - diagnóstico del proceso hijo
        failure_kind = "HARNESS_FAILURE"
        if probe is not None:
            result = probe.finish(
                args.scenario,
                "FAIL",
                args.timeout,
                started_at=started,
                error=f"{type(error).__name__}: {error}",
                traceback=_safe_tail(traceback.format_exc()),
            )
        else:
            result = {
                "scenario_name": args.scenario,
                "started_at": started,
                "finished_at": _utc_now(),
                "status": "FAIL",
                "timeout": args.timeout,
                "error": f"{type(error).__name__}: {error}",
                "traceback": _safe_tail(traceback.format_exc()),
            }
    finally:
        result.setdefault("started_at", started)
        result["finished_at"] = _utc_now()
        result["failure_kind"] = failure_kind
        _atomic_write(args.child_report.resolve(), result)
        if probe is not None:
            probe.close()
    return 0 if result.get("status") == "PASS" else 1


def _initial_parent_report(source: Path, output: Path) -> dict[str, object]:
    return {
        "artifact": str(output.resolve()),
        "created_at": _utc_now(),
        "started_at": _utc_now(),
        "finished_at": None,
        "performance_gate_status": "NOT VERIFIED",
        "harness_status": "RUNNING",
        "source": _project_reference(source),
        "environment": _parent_environment(),
        "scenario_results": [],
        "harness_failures": [],
        "product_failures": [],
        "temporary_copy": None,
        "temporary_copy_deleted": False,
    }


def _evaluate_parent(report: dict[str, object]) -> None:
    results = report.get("scenario_results", [])
    records = results if isinstance(results, list) else []
    by_name = {
        str(record.get("scenario_name")): record for record in records if isinstance(record, dict)
    }
    harness_failures = [
        str(record.get("error") or record.get("scenario_name"))
        for record in records
        if isinstance(record, dict)
        and (
            record.get("status") == "TIMEOUT"
            or record.get("failure_kind") == "HARNESS_FAILURE"
            or (
                isinstance(record.get("process"), dict)
                and record.get("process", {}).get("timed_out") is True
            )
            or (
                isinstance(record.get("process"), dict)
                and record.get("process", {}).get("exit_code") not in {0, None}
                and record.get("failure_kind") != "PRODUCT_FAILURE"
            )
        )
    ]
    product_failures = [
        str(record.get("error") or record.get("scenario_name"))
        for record in records
        if isinstance(record, dict) and record.get("failure_kind") == "PRODUCT_FAILURE"
    ]
    missing = [name for name in SCENARIOS if name not in by_name]
    harness_failures.extend(f"escenario no ejecutado: {name}" for name in missing)
    report["harness_failures"] = harness_failures
    report["product_failures"] = product_failures
    report["harness_status"] = "PASS" if not harness_failures else "FAIL"
    all_pass = all(by_name.get(name, {}).get("status") == "PASS" for name in SCENARIOS)
    if all_pass and not harness_failures and not product_failures:
        report["performance_gate_status"] = "PASS"
    elif product_failures and not harness_failures:
        report["performance_gate_status"] = "BLOCKED"
    else:
        report["performance_gate_status"] = "NOT VERIFIED"
    native_79 = by_name.get("native_79", {})
    response = native_79.get("windows_not_responding", {"status": "NOT MEASURED"})
    report["windows_not_responding_79"] = response
    report["manual_windows_observation_required"] = (
        isinstance(response, dict) and response.get("status") == "NOT MEASURED"
    )
    report["manual_acceptance_ready"] = (
        "YES" if report["performance_gate_status"] == "PASS" else "NO"
    )
    report["known_costs"] = [
        "composition cache HIT still transfers the complete payload to WebEngine"
        for record in records
        if isinstance(record, dict)
        and record.get("scenario_name") == "warm_cache_native"
        and record.get("composition_hit_retransmits_full_payload")
    ]


def _run_one_child(
    args: argparse.Namespace, copy: Path, run_root: Path, scenario: str, timeout_s: float
) -> dict[str, object]:
    child_report = run_root / f"{scenario}.json"
    command = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        "--child",
        "--project",
        str(copy),
        "--scenario",
        scenario,
        "--timeout",
        str(timeout_s),
        "--child-report",
        str(child_report),
    ]
    environment = os.environ.copy()
    environment["GTFS_EXPLORER_PERFORMANCE_GATE"] = "1"
    source_path = str(ROOT / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source_path, environment.get("PYTHONPATH", "")) if value
    )
    started = time.perf_counter()
    started_at = _utc_now()
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=max(1.0, timeout_s + 30.0))
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate()
    finished = time.perf_counter()
    base: dict[str, object] = {
        "scenario_name": scenario,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "timeout": timeout_s,
        "process": {
            "exit_code": process.returncode,
            "duration_s": finished - started,
            "timed_out": timed_out,
            "stdout_tail": _safe_tail(stdout),
            "stderr_tail": _safe_tail(stderr),
        },
    }
    if child_report.is_file():
        try:
            child_value = json.loads(child_report.read_text(encoding="utf-8"))
            if isinstance(child_value, dict):
                base.update(child_value)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            base.update({"status": "NO REPORT", "error": f"Informe hijo ilegible: {error}"})
    else:
        base.update(
            {
                "status": "TIMEOUT" if timed_out else "NO REPORT",
                "error": "El proceso hijo no publicó un informe final.",
                "failure_kind": "HARNESS_FAILURE",
            }
        )
    if timed_out:
        child_status = base.get("status")
        base["child_status"] = child_status
        base["status"] = "TIMEOUT"
        base["failure_kind"] = "HARNESS_FAILURE"
        base["error"] = (
            f"El proceso hijo excedió el timeout del escenario ({timeout_s:.1f}s) "
            "más la gracia de terminación; se conserva el informe parcial si existía."
        )
    existing_process = base.get("process")
    process_details: dict[str, object] = {}
    if isinstance(existing_process, dict):
        process_details = {str(key): value for key, value in existing_process.items()}
    base["process"] = {
        **process_details,
        "exit_code": process.returncode,
        "duration_s": finished - started,
        "timed_out": timed_out,
        "stdout_tail": _safe_tail(stdout),
        "stderr_tail": _safe_tail(stderr),
    }
    return base


def _parent_main(args: argparse.Namespace) -> int:
    os.environ["GTFS_EXPLORER_PERFORMANCE_GATE"] = "1"
    source = args.project.resolve()
    output = args.output.resolve()
    report = _initial_parent_report(source, output)
    _atomic_write(output, report)
    run_root = Path(tempfile.mkdtemp(prefix="GTFS-Explorer-PerformanceGate-native-"))
    copy = run_root / source.name
    report["temporary_copy"] = str(copy)
    _atomic_write(output, report)
    selected = tuple(args.only) if args.only else SCENARIOS
    try:
        if not source.is_dir():
            raise HarnessFailure(f"El proyecto fuente no existe o no es carpeta: {source}")
        invalid = [scenario for scenario in selected if scenario not in SCENARIOS]
        if invalid:
            raise HarnessFailure(f"Escenarios no reconocidos: {', '.join(invalid)}")
        shutil.copytree(source, copy)
        for scenario in selected:
            record = _run_one_child(args, copy, run_root, scenario, DEFAULT_TIMEOUTS[scenario])
            records = report.setdefault("scenario_results", [])
            if isinstance(records, list):
                records.append(record)
            _evaluate_parent(report)
            _atomic_write(output, report)
    except Exception as error:
        failures = report.setdefault("harness_failures", [])
        if isinstance(failures, list):
            failures.append(f"{type(error).__name__}: {error}")
        report["harness_status"] = "FAIL"
        report["performance_gate_status"] = "NOT VERIFIED"
        report["error"] = f"{type(error).__name__}: {error}"
        _atomic_write(output, report)
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
        report["temporary_copy_deleted"] = not run_root.exists()
        report["finished_at"] = _utc_now()
        _evaluate_parent(report)
        if report.get("harness_failures"):
            report["performance_gate_status"] = "NOT VERIFIED"
        _atomic_write(output, report)
    return 0 if report.get("performance_gate_status") == "PASS" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / f"performance-gate-native-{datetime.now():%Y%m%d}.json",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=SCENARIOS,
        help="Ejecuta únicamente estos escenarios; el informe queda marcado como no completo.",
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scenario", choices=SCENARIOS, help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=120.0, help=argparse.SUPPRESS)
    parser.add_argument("--child-report", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.child:
        if args.scenario is None or args.child_report is None:
            parser.error("--child requiere --scenario y --child-report")
        return _child_main(args)
    return _parent_main(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Instrumentación focal y opt-in para el gate de responsividad 0.2.0.

No cambia el comportamiento del producto cuando no se inyecta un ``GateTrace``.
Autor: Yeison Arbey Carrillo Lemus.
Todos los derechos reservados.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QTimer

_CURRENT_TRACE: ContextVar[GateTrace | None] = ContextVar("gtfs_gate_trace", default=None)
_CURRENT_GENERATION: ContextVar[int | None] = ContextVar("gtfs_gate_generation", default=None)


@dataclass(frozen=True)
class GateEvent:
    phase: str
    monotonic_ns: int
    thread_id: int
    generation: int | None
    payload_bytes: int | None


@dataclass
class GateTrace:
    """Registro thread-safe de fases, cachés y resultados del gate."""

    events: list[GateEvent] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(
        self,
        phase: str,
        *,
        generation: int | None = None,
        payload_bytes: int | None = None,
    ) -> None:
        event = GateEvent(
            phase,
            time.perf_counter_ns(),
            threading.get_ident(),
            generation,
            payload_bytes,
        )
        with self._lock:
            self.events.append(event)

    def count(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events": [event.__dict__.copy() for event in self.events],
                "counters": dict(self.counters),
            }

    def write_json(self, destination: str) -> None:
        with open(destination, "w", encoding="utf-8") as stream:
            json.dump(self.snapshot(), stream, ensure_ascii=False, indent=2)


def mark(trace: GateTrace | None, phase: str, **kwargs: Any) -> None:
    if trace is not None:
        trace.mark(phase, **kwargs)


def mark_current(phase: str, **kwargs: Any) -> None:
    mark(_CURRENT_TRACE.get(), phase, **kwargs)


def count_current(name: str, amount: int = 1) -> None:
    trace = _CURRENT_TRACE.get()
    if trace is not None:
        trace.count(name, amount)


@contextmanager
def trace_scope(trace: GateTrace | None, *, generation: int | None = None) -> Iterator[None]:
    token = _CURRENT_TRACE.set(trace)
    generation_token = _CURRENT_GENERATION.set(generation)
    try:
        yield
    finally:
        _CURRENT_GENERATION.reset(generation_token)
        _CURRENT_TRACE.reset(token)


def current_generation() -> int | None:
    """Devuelve la generación de UI asociada al worker actual, si existe."""
    return _CURRENT_GENERATION.get()


class QtHeartbeat(QObject):
    """Probe real deltas del event loop Qt, sin inferirlas del worker."""

    def __init__(self, interval_ms: int = 25, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.interval_ms = interval_ms
        self.expected_ns: int | None = None
        self.delays_ms: list[float] = []
        self._samples: list[dict[str, int | float]] = []
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.expected_ns = time.perf_counter_ns() + self.interval_ms * 1_000_000
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()

    def _tick(self) -> None:
        now = time.perf_counter_ns()
        expected = self.expected_ns or now
        delay_ms = max(0.0, (now - expected) / 1_000_000)
        self.delays_ms.append(delay_ms)
        self._samples.append(
            {
                "expected_ns": expected,
                "observed_ns": now,
                "delay_ms": delay_ms,
            }
        )
        self.expected_ns = now + self.interval_ms * 1_000_000

    def samples(self) -> list[dict[str, int | float]]:
        """Devuelve muestras temporales para asignar stalls a fases del gate."""
        return [sample.copy() for sample in self._samples]

    def summary(self) -> dict[str, float | int]:
        ordered = sorted(self.delays_ms)
        if not ordered:
            return {
                "max_gui_stall_ms": 0.0,
                "p95_gui_stall_ms": 0.0,
                "stalls_gt_100_ms": 0,
                "stalls_gt_200_ms": 0,
                "stalls_gt_500_ms": 0,
                "stalls_gt_1000_ms": 0,
            }
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        return {
            "max_gui_stall_ms": max(ordered),
            "p95_gui_stall_ms": p95,
            "stalls_gt_100_ms": sum(delay > 100 for delay in ordered),
            "stalls_gt_200_ms": sum(delay > 200 for delay in ordered),
            "stalls_gt_500_ms": sum(delay > 500 for delay in ordered),
            "stalls_gt_1000_ms": sum(delay > 1000 for delay in ordered),
        }

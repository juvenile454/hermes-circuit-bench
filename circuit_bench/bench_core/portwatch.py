"""Port watcher: ``board.changed`` events while a Desktop client is connected.

One watcher per process (``watcher()`` = ``runtime.get("portwatch", PortWatcher)``). It polls ``board.list_ports()``
every ``interval`` seconds while a client is active: a serial WebSocket is open (``connect()``/``disconnect``) or a
route was called within ``active_window`` seconds (``touch()``). The thread starts on demand and ends by itself
when no client is active; the last port snapshot is kept, so the next run reports what changed meanwhile.

Per change exactly one event ``board.changed`` ``{port, state, simulated}``:
- ``linked``: a port appeared, or is usable again after ``busy``;
- ``lost``: a port disappeared;
- ``busy``: the broker paused the port (a flash is running) or another Circuit Bench process holds it.
The first poll of a process only records the baseline (the UI reads ``GET /ports`` when it starts).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from . import events, runtime

logger = logging.getLogger(__name__)

INTERVAL_S = 2.0
ACTIVE_WINDOW_S = 10.0
BUSY_STATES = frozenset({"paused", "busy"})


def _default_lister() -> list[dict[str, Any]]:
    from . import board  # lazy: board pulls in serialport, clitools ...
    return board.list_ports()


def _default_state_of(device: str) -> str | None:
    """Broker state of a port (``open``, ``closed``, ``paused`` ...); only the serialport module functions."""
    from . import serialport
    try:
        return serialport.port_status(device).get("state")
    except Exception:  # noqa: BLE001 - a broken status read must not stop the watcher
        return None


class PortWatcher:
    """Thread-safe; every dependency can be replaced (tests)."""

    def __init__(self, *, lister: Callable[[], list[Mapping[str, Any]]] | None = None,
                 emit: Callable[[str, Mapping[str, Any]], Any] | None = None,
                 state_of: Callable[[str], str | None] | None = None,
                 interval: float = INTERVAL_S, active_window: float = ACTIVE_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic):
        self._lister = lister or _default_lister
        self._emit = emit or events.emit
        self._state_of = state_of or _default_state_of
        self.interval = float(interval)
        self.active_window = float(active_window)
        self._clock = clock
        self._lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self._clients = 0
        self._last_touch: float | None = None
        self._snapshot: dict[str, tuple[str, bool]] | None = None  # device -> (state, simulated)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.polls = 0

    # ----------------------------------------------------------------- activity
    def touch(self) -> None:
        """A Desktop request arrived: keep watching for ``active_window`` seconds."""
        with self._lock:
            self._last_touch = self._clock()
        self.ensure_running()

    def connect(self) -> Callable[[], None]:
        """A serial WebSocket opened; returns ``disconnect()`` (idempotent)."""
        with self._lock:
            self._clients += 1
        done = threading.Event()

        def disconnect() -> None:
            if done.is_set():
                return
            done.set()
            with self._lock:
                self._clients = max(0, self._clients - 1)
                self._last_touch = self._clock()  # the window starts again when the socket closes

        self.ensure_running()
        return disconnect

    def active(self) -> bool:
        with self._lock:
            if self._clients > 0:
                return True
            return self._last_touch is not None and self._clock() - self._last_touch <= self.active_window

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    # ----------------------------------------------------------------- polling
    def _states(self) -> dict[str, tuple[str, bool]]:
        out: dict[str, tuple[str, bool]] = {}
        for p in self._lister() or []:
            device = p.get("device") if isinstance(p, Mapping) else None
            if not isinstance(device, str) or not device:
                continue
            state = "busy" if self._state_of(device) in BUSY_STATES else "linked"
            out[device] = (state, bool(p.get("simulated", device.startswith("sim://"))))
        return out

    def poll_once(self) -> list[dict[str, Any]]:
        """One comparison with the last snapshot; sends and returns the ``board.changed`` payloads."""
        with self._poll_lock:
            try:
                now = self._states()
            except Exception as e:  # noqa: BLE001 - a failing port list keeps the old snapshot
                logger.debug("circuit-bench: port list failed (%s)", type(e).__name__)
                return []
            self.polls += 1
            before, self._snapshot = self._snapshot, now
            if before is None:
                return []
            changes: list[dict[str, Any]] = []
            for device, (state, sim) in now.items():
                old = before.get(device)
                if old is None or old[0] != state:
                    changes.append({"port": device, "state": state, "simulated": sim})
            for device, (_state, sim) in before.items():
                if device not in now:
                    changes.append({"port": device, "state": "lost", "simulated": sim})
        for payload in changes:
            try:
                self._emit("board.changed", payload)
            except Exception as e:  # noqa: BLE001 - an event never stops the watcher
                logger.debug("circuit-bench: board.changed not sent (%s)", type(e).__name__)
        return changes

    def ensure_running(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="cb-portwatch", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set() and self.active():
            self.poll_once()
            if self._stop.wait(self.interval):
                break

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the thread (tests, shutdown); a later ``touch()`` starts it again."""
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)


def watcher() -> PortWatcher:
    """The process-wide port watcher (shared by every copy of the package)."""
    return runtime.get("portwatch", PortWatcher)

"""Process-wide singletons (broker, jobs, port watcher) shared by every copy of the package.

Hermes loads the tools as hermes_plugins.<slug> and dashboard/plugin_api.py loads bench_core again through its own
spec, so module-level globals would exist twice in one process. Objects stored here live in one fixed sys.modules
entry instead.
"""
from __future__ import annotations

import sys
import threading
import types
from collections.abc import Callable
from typing import Any, TypeVar

KEY = "circuit_bench_runtime"
T = TypeVar("T")
_INIT_LOCK = threading.Lock()


def _ns() -> types.ModuleType:
    mod = sys.modules.get(KEY)
    if mod is None:
        with _INIT_LOCK:
            mod = sys.modules.get(KEY)
            if mod is None:
                mod = types.ModuleType(KEY, "Circuit Bench process-wide objects")
                mod.objects = {}
                mod.lock = threading.RLock()
                sys.modules[KEY] = mod
    return mod


def get(name: str, factory: Callable[[], T]) -> T:
    """The process-wide object ``name``; created once with ``factory()``."""
    ns = _ns()
    with ns.lock:
        if name not in ns.objects:
            ns.objects[name] = factory()
        return ns.objects[name]


def peek(name: str) -> Any | None:
    return _ns().objects.get(name)


def reset() -> None:
    """Tests only: forget every object (does not close anything)."""
    ns = _ns()
    with ns.lock:
        ns.objects.clear()

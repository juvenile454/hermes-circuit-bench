"""Module check rules: one file per module family, auto-discovered.

bus.py, elec.py, <family>.py (one per module family). Each file registers its rules with
``@modcheck.rule("mod.…")``. ``load()`` imports every submodule in sorted order.

``load()`` is idempotent: Python caches imported modules, so a second call registers nothing twice. A file that
fails to import is recorded in ``LOAD_ERRORS`` ({module name: error text}), not retried in this process (its rules
may be half registered), and reported by ``modcheck.run`` as the check ``modules.rules`` (not_checked); the other
files still load. Files starting with ``_`` are skipped.

Imports in a rule file: ``from . import modcheck`` (bench_core files never use ``from ..``, test_p0_package), then
``@modcheck.rule("mod.<family>.<name>")``, ``modcheck.Ctx``, ``modcheck.Finding``, ``modcheck.fmt`` …
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any

# the engine, re-exported for the rule files (same module object as bench_core.modcheck)
modcheck: Any = importlib.import_module(__name__.rpartition(".")[0] + ".modcheck")

LOAD_ERRORS: dict[str, str] = {}


def names() -> list[str]:
    """Rule modules in this package, sorted."""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))


def load() -> list[str]:
    """Import every rule module (sorted); returns the names that are loaded."""
    loaded = []
    for name in names():
        if name in LOAD_ERRORS:
            continue
        try:
            importlib.import_module(f"{__name__}.{name}")
        except Exception as e:  # noqa: BLE001 - one broken family file must not stop the others
            LOAD_ERRORS[name] = f"{type(e).__name__}: {e}"
            continue
        loaded.append(name)
    return loaded

"""Circuit Bench backend routes under /api/plugins/circuit-bench/.

Hermes mounts this file (``dashboard/manifest.json`` -> ``"api": "plugin_api.py"``) with
``importlib.util.spec_from_file_location("hermes_dashboard_plugin_circuit-bench", path)`` and no parent package,
so ``from .. import bench_core`` cannot work. Both support packages are loaded by file location instead and
registered in ``sys.modules`` under fixed names, which keeps their own relative imports working:

- ``circuit_bench_api_core``: ``../bench_core`` (the route copy of the Hermes-independent core);
- ``circuit_bench_api_routes``: ``./routes`` (FastAPI route modules).

The tool half loads the same files as ``hermes_plugins.circuit_bench.bench_core``. Process-wide objects (serial
broker, jobs, port watcher, sim provider) live in ``bench_core.runtime`` (``sys.modules["circuit_bench_runtime"]``),
so both copies share them. A registration that points at another folder (a second install in the same process) is
evicted and loaded again; a failed load leaves nothing behind.

Nothing here touches hardware, the network or the disk at import time; schemdraw and pyserial stay lazy.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PLUGIN_ID = "circuit-bench"
DASHBOARD_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = DASHBOARD_DIR.parent
CORE_PACKAGE = "circuit_bench_api_core"
ROUTES_PACKAGE = "circuit_bench_api_routes"


def _evict(name: str) -> None:
    prefix = name + "."
    for key in [k for k in list(sys.modules) if k == name or k.startswith(prefix)]:
        sys.modules.pop(key, None)


def load_package(name: str, folder: Path) -> ModuleType:
    """Load (or reuse) the package in ``folder`` as ``name``; evicts a registration from another folder."""
    folder = folder.resolve()
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "_CB_DIR", None) == str(folder):
        return existing
    if existing is not None:
        _evict(name)
    init = folder / "__init__.py"
    if not init.is_file():
        raise RuntimeError(f"circuit-bench: package missing: {init}")
    spec = importlib.util.spec_from_file_location(name, init, submodule_search_locations=[str(folder)])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"circuit-bench: cannot create a module spec for {folder}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = name
    module.__path__ = [str(folder)]  # type: ignore[attr-defined]
    module._CB_DIR = str(folder)  # type: ignore[attr-defined]
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        _evict(name)
        raise
    return module


def load_router():
    """``(core package, routes package, APIRouter)``; a failure evicts both packages."""
    try:
        core = load_package(CORE_PACKAGE, PACKAGE_DIR / "bench_core")
        routes = load_package(ROUTES_PACKAGE, DASHBOARD_DIR / "routes")
        return core, routes, routes.create_router(core)
    except BaseException:
        _evict(ROUTES_PACKAGE)
        _evict(CORE_PACKAGE)
        raise


core, routes, router = load_router()

__all__ = ["PLUGIN_ID", "core", "load_package", "router", "routes"]

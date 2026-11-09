"""Route modules of the Circuit Bench backend.

dashboard/plugin_api.py loads this folder as a package by file location (Hermes gives it no parent package) and
calls ``create_router(core_pkg)`` with its own copy of bench_core. Route modules never import bench_core: they get
it through ``common.Core`` (lazy submodule access), so they work with whichever copy the loader registered.
"""
from types import ModuleType

from fastapi import APIRouter, Depends

from . import catalog, common, crash_routes, hardware, projects, serial_stream, system, workshop

MODULES = (system, projects, workshop, catalog, hardware, serial_stream, crash_routes)


def create_router(core_pkg: ModuleType) -> APIRouter:
    core = common.Core(core_pkg)

    def desktop_activity() -> None:
        """Every request keeps the port watcher running for its activity window."""
        try:
            core.portwatch.watcher().touch()
        except Exception:  # noqa: BLE001 - the watcher must never break a request
            common.logger.debug("circuit-bench: port watcher not started", exc_info=True)

    router = APIRouter(dependencies=[Depends(desktop_activity)])
    for module in MODULES:
        module.register(router, core)
    return router

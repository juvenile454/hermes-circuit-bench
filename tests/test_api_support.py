"""Shared harness of the backend route tests (no tests in here).

- ``load_plugin_api()`` imports dashboard/plugin_api.py exactly like Hermes' loader does: by file location, without
  a parent package (``hermes_dashboard_plugin_circuit-bench``).
- ``api_session(mp)`` mounts the router in a bare FastAPI app under /api/plugins/circuit-bench and isolates the
  route copy of bench_core (``circuit_bench_api_core``): the real port list is never read (``mock_ports``), the
  real sim module stays out, a ``TestProvider`` serves ``sim://`` ports (shared through runtime). Plain HTTP goes
  through ``httpx.ASGITransport``; WebSockets through Starlette's TestClient. A tiny ASGI wrapper plays Hermes'
  plugin WebSocket gate: it stamps the Desktop's native principal on the connection (``stamp=False`` leaves the
  socket anonymous).
- Fixtures ``api`` and ``events`` (fake ``hermes_cli.plugin_events`` that records every broadcast).

Usage: ``from test_api_support import *`` (fixtures from __all__) and ``import test_api_support as sup``.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import json
import queue
import sys
import threading
import time
import types
import warnings
from pathlib import Path
from typing import Any

import httpx
import pytest

import board_fixtures as bf

with warnings.catch_warnings():  # Starlette deprecates httpx for its TestClient (WebSocket tests need it)
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "circuit_bench"
API_FILE = PKG / "dashboard" / "plugin_api.py"
PREFIX = "/api/plugins/circuit-bench"
LOADER_NAME = "hermes_dashboard_plugin_circuit-bench"
CORE = "circuit_bench_api_core"
SHA_A = bf.SHA_A
__all__ = ["api", "events"]


def load_plugin_api(name: str = LOADER_NAME) -> types.ModuleType:
    """dashboard/plugin_api.py as Hermes loads it (hermes_cli.web_server_dashboard._mount_one_plugin_api)."""
    spec = importlib.util.spec_from_file_location(name, API_FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def route_module(name: str) -> types.ModuleType:
    """A module of the route copy of bench_core (``circuit_bench_api_core.<name>``)."""
    return importlib.import_module(f"{CORE}.{name}")


class StampPrincipal:
    """Plays Hermes' PluginApiWebSocketGate after it redeemed a Desktop native grant."""

    def __init__(self, app, enabled: bool = True, client: tuple[str, int] | None = None):
        self.app = app
        self.enabled = enabled
        self.client = client  # peer address; TestClient(client=...) needs a newer Starlette than our lowest bound

    async def __call__(self, scope, receive, send):
        if self.client is not None:
            scope["client"] = self.client
        if scope["type"] == "websocket" and self.enabled:
            scope.setdefault("state", {})["native_http_principal"] = {"profile_id": "default", "test": True}
        await self.app(scope, receive, send)


class Recorder:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.lock = threading.Lock()

    def __call__(self, plugin, event, payload):
        with self.lock:
            self.calls.append((plugin, event, payload))

    def of(self, event: str) -> list[dict]:
        with self.lock:
            return [p for _plugin, e, p in self.calls if e == event]


class WsSession:
    """WebSocket test session with time-limited receive (TestClient's receive blocks forever)."""

    def __init__(self, session):
        self.session = session
        self.inbox: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        while True:
            try:
                self.inbox.put(("msg", self.session.receive_json()))
            except Exception as e:  # noqa: BLE001 - disconnect or test end
                self.inbox.put(("end", e))
                return

    def get(self, timeout: float = 5.0) -> dict:
        kind, value = self.inbox.get(timeout=timeout)
        if kind == "end":
            raise AssertionError(f"socket ended: {value!r}")
        return value

    def until(self, predicate, timeout: float = 5.0, limit: int = 1000) -> list[dict]:
        """Messages up to and including the first one matching ``predicate``."""
        out: list[dict] = []
        deadline = time.monotonic() + timeout
        while len(out) < limit:
            msg = self.get(max(0.01, deadline - time.monotonic()))
            out.append(msg)
            if predicate(msg):
                return out
        raise AssertionError(f"no matching message in {out!r}")

    def quiet(self, timeout: float = 0.3) -> bool:
        try:
            self.inbox.get(timeout=timeout)
        except queue.Empty:
            return True
        return False


class Api:
    def __init__(self, mod, app, wrapped, provider):
        self.mod = mod
        self.app = app
        self.wrapped = wrapped
        self.provider = provider

    # ---- route copy of bench_core
    def core(self, name: str) -> types.ModuleType:
        return route_module(name)

    # ---- HTTP through httpx.ASGITransport
    def request(self, method: str, path: str, **kw) -> httpx.Response:
        async def go():
            transport = httpx.ASGITransport(app=self.wrapped)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                return await client.request(method, PREFIX + path, **kw)
        return asyncio.run(go())

    def get(self, path: str, **kw) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> httpx.Response:
        if body is not None:
            kw["json"] = body
        return self.request("POST", path, **kw)

    def patch(self, path: str, body: Any = None, **kw) -> httpx.Response:
        return self.request("PATCH", path, json=body, **kw)

    def delete(self, path: str, **kw) -> httpx.Response:
        return self.request("DELETE", path, **kw)

    # ---- helpers
    def ok(self, resp: httpx.Response, status: int = 200) -> dict:
        body = resp.json()
        assert resp.status_code == status, (resp.status_code, body)
        assert body["ok"] is True, body
        return body

    def err(self, resp: httpx.Response, status: int, code: str) -> dict:
        body = resp.json()
        assert resp.status_code == status, (resp.status_code, body)
        assert body["ok"] is False and body["error"]["code"] == code, body
        return body

    def wait_job(self, job_id: str, timeout: float = 10.0) -> dict:
        assert route_module("jobs").table().wait(job_id, timeout) is not None
        resp = self.get(f"/jobs/{job_id}")
        body = resp.json()
        assert resp.status_code == 200, body
        assert body["result"]["state"] in ("done", "failed"), body
        return body

    def create(self, pid: str = "bench-a", chip: str = "esp32s3", variant: str | None = "n16r8", **extra) -> dict:
        body = {"id": pid, "title": f"Test {pid}", "chip": chip, **extra}
        if variant is not None:
            body["variant"] = variant
        return self.ok(self.post("/projects", body))["result"]["project"]

    def project(self, pid: str) -> dict:
        return self.ok(self.get(f"/projects/{pid}"))["result"]["project"]

    def apply(self, pid: str, *ops: dict) -> dict:
        rev = self.project(pid)["rev"]
        return self.ok(self.patch(f"/projects/{pid}", {"expected_rev": rev, "ops": list(ops)}))

    def record(self, pid: str, *ops: dict) -> dict:
        """Result ops (set_detected/set_build/set_flash/set_debug) as the server's jobs write them (trusted);
        PATCH refuses them."""
        proj = route_module("project")
        env = proj.update(pid, self.project(pid)["rev"], list(ops), by="ui", trusted=True)
        assert env["ok"], env.get("error")
        return env

    def ws(self, path: str, *, stamp: bool = True, client=("127.0.0.1", 50000)):
        """Context manager: a WsSession on ``path`` (below the plugin prefix)."""

        @contextlib.contextmanager
        def session():
            app = StampPrincipal(self.app, enabled=stamp, client=client)
            with TestClient(app, base_url="http://127.0.0.1") as tc:
                with tc.websocket_connect(PREFIX + path) as s:
                    yield WsSession(s)
        return session()


def mock_ports(mp: pytest.MonkeyPatch, entries: list[tuple]) -> list:
    """Replace the route copy's board._comports by a fixed list (device, vid, pid, description[, serial_number])."""
    board = route_module("board")
    calls: list = []

    def fake():
        calls.append(1)
        return [types.SimpleNamespace(device=d, vid=v, pid=p, description=desc, product=None,
                                      serial_number=(rest[0] if rest else None),
                                      hwid=(f"USB VID:PID={v:04X}:{p:04X}" if v is not None else "n/a"))
                for d, v, p, desc, *rest in entries]

    mp.setattr(board, "_comports", fake)
    return calls


def _unmocked():
    raise AssertionError("test read the real serial port list; use test_api_support.mock_ports()")


@contextlib.contextmanager
def api_session(mp: pytest.MonkeyPatch, provider: bf.TestProvider | None = None):
    from fastapi import FastAPI

    mod = load_plugin_api()
    runtime = route_module("runtime")
    board = route_module("board")
    # the real sim module stays out; TestProvider plays sim:// (providers live in runtime: both copies)
    mp.setitem(sys.modules, f"{CORE}.sim", None)
    mp.setattr(board, "_comports", _unmocked)
    runtime.get("board.sim_registered", lambda: {"done": True})["done"] = True
    provider = provider or bf.TestProvider(lines=("boot", "ready"))
    board.register_provider("sim://", provider)
    app = FastAPI()
    app.include_router(mod.router, prefix=PREFIX)
    a = Api(mod, app, StampPrincipal(app), provider)
    try:
        yield a
    finally:
        shutdown()


def shutdown() -> None:
    """Stop the port watcher, finish jobs and close every port (before conftest resets runtime)."""
    runtime = route_module("runtime")
    pw = runtime.peek("portwatch")
    if pw is not None:
        pw.stop()
    jobs = runtime.peek("jobs")
    if jobs is not None:
        jobs.wait_all(10.0)
    broker = runtime.peek("broker")
    if broker is not None:
        broker.shutdown()
    relays = runtime.peek("api.panic_relays")
    if relays is not None:
        for entry in list(relays["ports"].values()):
            with contextlib.suppress(Exception):
                entry["unsubscribe"]()


@pytest.fixture
def api(monkeypatch):
    with api_session(monkeypatch) as a:
        yield a


@pytest.fixture
def events(monkeypatch) -> Recorder:
    """A fake hermes_cli.plugin_events: events.emit of both package copies lands here."""
    rec = Recorder()
    pkg = types.ModuleType("hermes_cli")
    mod = types.ModuleType("hermes_cli.plugin_events")
    mod.broadcast_plugin_event = rec
    pkg.plugin_events = mod
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", mod)
    return rec


def write_firmware(folder: Path, env: str = "s3") -> Path:
    """A minimal PlatformIO project folder (never built for real: fake pio or the sim provider)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "platformio.ini").write_text(f"[env:{env}]\nplatform = espressif32\nboard = esp32-s3-devkitc-1\n"
                                           "framework = arduino\n", encoding="utf-8")
    (folder / "src").mkdir(exist_ok=True)
    (folder / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return folder


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False)

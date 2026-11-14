"""Model view of bench_board answers: sources carry id, title, url and retrieved, never ``note``.

bench_core, the routes and the jobs keep the full sources. Simulated board (sim://) and, for real boards, only fakes:
fake esptool/pio, pty ports, mocked port lists, synthetic MACs.
"""
import json
import sys
import types
from pathlib import Path

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import fake_tools, hw_on, pty_port  # noqa: F401 - fixtures
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, contracts, project, runtime, serialport

sim = pytest.importorskip("circuit_bench.bench_core.sim")
MODEL_KEYS = {"id", "title", "url", "retrieved"}
CORE = ((board, "detect"), (board, "build"), (board, "flash"), (serialport, "monitor"))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    yield
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


def spy_core(monkeypatch) -> dict:
    """Record the envelope each bench_core function hands to the tool layer (keyed by function name)."""
    seen: dict = {}
    for mod, name in CORE:
        real = getattr(mod, name)

        def wrap(*a, _real=real, _name=name, **kw):
            env = _real(*a, **kw)
            seen[_name] = env
            return env

        monkeypatch.setattr(mod, name, wrap)
    return seen


TASK = "t"  # the task id Hermes passes to the hook and the handler alike


def call(host, name, **args):
    raw = tools.make_handlers(host)[name](args, task_id=TASK)
    env = json.loads(raw)
    assert contracts.validate_envelope(env) == [], env
    return env, len(raw.encode("utf-8"))


def ids(env):
    return [s["id"] for s in env["sources"]]


def assert_model_view(env, core):
    assert ids(env) == ids(core)
    assert all(set(s) <= MODEL_KEYS and MODEL_KEYS <= set(s) for s in env["sources"]), env["sources"]


def sim_demo(host):
    env, _ = call(host, "bench_project", action="demo")
    assert env["ok"], env
    return env["result"]["id"]


def test_sim_board_answers_carry_no_source_notes(monkeypatch):
    seen = spy_core(monkeypatch)
    host = tools.Host(hook_active=False)
    pid = sim_demo(host)
    answers = {"detect": call(host, "bench_board", action="detect", port=sim.PORT, project=pid)[0]}
    answers["build"] = call(host, "bench_board", action="build", project=pid)[0]
    sha = answers["build"]["result"]["elf_sha256"]
    answers["flash"] = call(host, "bench_board", action="flash", project=pid, elf_sha256=sha)[0]
    answers["monitor"] = call(host, "bench_board", action="monitor", port=sim.PORT, seconds=5)[0]
    for name, env in answers.items():
        assert env["ok"], (name, env["error"])
        assert_model_view(env, seen[name])
    assert answers["monitor"]["result"]["panics"]  # the demo firmware crashes: the panic warning cites its source
    assert any("note" in s for s in seen["monitor"]["sources"])  # bench_core keeps the note


def test_sim_elf_mismatch_refusal_is_short_and_keeps_the_source_ids(monkeypatch):
    host = tools.Host(hook_active=False)
    pid = sim_demo(host)
    assert call(host, "bench_board", action="detect", port=sim.PORT, project=pid)[0]["ok"]
    sha = call(host, "bench_board", action="build", project=pid)[0]["result"]["elf_sha256"]
    main = Path(project.get(pid)["result"]["project"]["firmware"]["dir"]) / "src" / "main.cpp"
    main.write_text(main.read_text(encoding="utf-8") + "\n// changed after the build\n", encoding="utf-8")
    seen = spy_core(monkeypatch)
    env, size = call(host, "bench_board", action="flash", project=pid, elf_sha256=sha)
    assert env["error"]["code"] == "elf_mismatch"
    assert_model_view(env, seen["flash"])
    assert len(env["sources"]) >= 4 and all("note" in s for s in seen["flash"]["sources"])
    assert size <= 1600, size


@pytest.mark.parametrize("name", ["detect", "build", "monitor"])
def test_refusals_from_bench_core_lose_the_notes_too(monkeypatch, name):
    host = tools.Host(hook_active=False)
    pid = sim_demo(host)
    src = {"id": "x-src", "title": "Synthetic source", "url": "https://example.invalid/x", "retrieved": "2026-11-08",
           "note": "a long explanation that is not a check"}
    action = {"detect": "board.detect", "build": "board.build", "monitor": "serial.monitor"}[name]
    mod = serialport if name == "monitor" else board
    monkeypatch.setattr(mod, name, lambda *a, **k: contracts.fail(action, "tool_failed", "synthetic failure",
                                                                   sources=[src]))
    args = {"detect": {"port": sim.PORT, "project": pid}, "build": {"project": pid},
            "monitor": {"port": sim.PORT, "seconds": 1}}[name]
    env, _ = call(host, "bench_board", action=name, **args)
    assert env["error"]["code"] == "tool_failed"
    assert env["sources"] == [{k: src[k] for k in ("id", "title", "url", "retrieved")}]


def test_real_board_flash_keeps_the_ids_without_notes(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fw = sup.write_firmware(tmp_path / "fw")
    fake_tools.scenario("board-pio-flash-ok.json")
    built = board.build(fw, "s3")
    assert built["ok"], built["error"]
    pid = "model-view"
    assert project.create(pid, "Model view", "esp32s3", "n16r8", "esp32-s3-devkitc-1", by="agent")["ok"]
    upd = project.update(pid, 1, [
        {"op": "set_detected", "port": pty_port.name, "mac": "aa:bb:cc:dd:ee:ff",
         "chip": "ESP32-S3 (QFN56) (revision v0.2)"},
        {"op": "set_firmware", "dir": str(fw), "env": "s3"}, {"op": "set_build", **built["result"]}],
        by="ui", trusted=True)
    assert upd["ok"], upd
    host = tools.Host(hook_active=True)
    args = {"action": "flash", "project": pid, "elf_sha256": built["result"]["elf_sha256"]}
    assert hooks.decide(host, "bench_board", args, TASK)["action"] == "approve"
    seen = spy_core(monkeypatch)
    env, _ = call(host, "bench_board", **args)
    assert env["ok"], env["error"]
    assert_model_view(env, seen["flash"])
    assert ids(env) and all("note" in s for s in seen["flash"]["sources"])


def test_route_flash_answer_keeps_the_notes(api, tmp_path):  # noqa: F811
    pid = "route-notes"
    api.create(pid)
    api.apply(pid, {"op": "set_firmware", "dir": str(sup.write_firmware(tmp_path / "fw")), "env": "s3"})
    for path, body in (("/board/detect", {"port": "sim://test-s3", "project": pid}), ("/board/build", {"project": pid})):
        assert api.wait_job(api.post(path, body).json()["result"]["job_id"])["result"]["state"] == "done"
    api.provider.sha = "b" * 64  # the firmware changed after the approved build
    confirm = {"port": "sim://test-s3", "mac": "aa:bb:cc:dd:ee:ff", "elf_sha256": bf.SHA_A}
    job = api.wait_job(api.post("/board/flash", {"project": pid, "confirm": confirm}).json()["result"]["job_id"])
    assert job is not None
    res = job["result"]["result"]
    assert res["error"]["code"] == "elf_mismatch"
    assert res["sources"] and all("note" in s for s in res["sources"])

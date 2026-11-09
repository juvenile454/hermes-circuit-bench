"""Backend routes through httpx.ASGITransport (loader, status codes, projects, workshop, board jobs, flash
approvals, crash decode, health/doctor, lazy imports, shared runtime objects)."""
import builtins
import importlib
import json
import sys
from pathlib import Path

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import fake_tools  # noqa: F401 - fixture
from test_api_support import *  # noqa: F403

from circuit_bench.bench_core import calckit, contracts

ROUTES = {
    ("GET", "/health"), ("GET", "/doctor"), ("GET", "/projects"), ("POST", "/projects"), ("POST", "/projects/demo"),
    ("GET", "/projects/{project_id}"), ("PATCH", "/projects/{project_id}"), ("DELETE", "/projects/{project_id}"),
    ("POST", "/projects/{project_id}/firmware/example"), ("POST", "/projects/{project_id}/solder/{step_id}"),
    ("POST", "/pins/check"), ("POST", "/pins/suggest"), ("GET", "/pins/info"), ("GET", "/calc"), ("POST", "/calc/{kind}"), ("GET", "/modules"),
    ("GET", "/modules/{module_id}"), ("POST", "/schematic"),
    ("POST", "/solder/plan"), ("GET", "/boards/{board_id}"), ("GET", "/ports"), ("POST", "/board/detect"),
    ("POST", "/board/build"), ("POST", "/board/flash"), ("GET", "/board/flash/check"), ("GET", "/jobs/{job_id}"), ("POST", "/serial/open"),
    ("POST", "/serial/close"), ("GET", "/serial/tail"), ("WS", "/serial/stream"), ("POST", "/crash/decode"),
}
# one static POST /calc/<kind> per registered calculator (the six basics plus every calcs/<kind>.py)
ROUTES |= {("POST", f"/calc/{kind}") for kind in calckit.kinds()}
CONFIRM_MAC = "aa:bb:cc:dd:ee:ff"


def route_set(router):
    out = set()
    for r in router.routes:
        methods = getattr(r, "methods", None) or {"WS"}
        out |= {(m, r.path) for m in methods}
    return out


# --------------------------------------------------------------------------------------------- loader

def test_loads_like_the_hermes_loader_without_a_parent_package():
    mod = sup.load_plugin_api()
    assert mod.__package__ in (None, "")  # no parent package, exactly like spec_from_file_location in Hermes
    assert route_set(mod.router) == ROUTES
    assert sys.modules["circuit_bench_api_core"]._CB_DIR == str((sup.PKG / "bench_core").resolve())
    assert sys.modules["circuit_bench_api_routes"]._CB_DIR == str((sup.PKG / "dashboard" / "routes").resolve())
    again = sup.load_plugin_api("hermes_dashboard_plugin_again")
    assert again.core is mod.core  # same folder: reused, no second copy
    assert route_set(again.router) == ROUTES


def test_a_registration_from_another_folder_is_replaced(tmp_path, monkeypatch):
    fake = tmp_path / "other_core"
    fake.mkdir()
    (fake / "__init__.py").write_text("MARK = 'other'\n", encoding="utf-8")
    mod = sup.load_plugin_api()
    other = mod.load_package("circuit_bench_api_core", fake)
    assert other.MARK == "other" and sys.modules["circuit_bench_api_core"] is other
    real = mod.load_package("circuit_bench_api_core", sup.PKG / "bench_core")
    assert not hasattr(real, "MARK") and real._CB_DIR == str((sup.PKG / "bench_core").resolve())


def test_failed_load_leaves_nothing_behind(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "__init__.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    mod = sup.load_plugin_api()
    with pytest.raises(RuntimeError):
        mod.load_package("cb_test_broken_pkg", broken)
    assert "cb_test_broken_pkg" not in sys.modules


def test_manifest_and_noop_entry():
    dash = sup.PKG / "dashboard"
    manifest = json.loads((dash / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "circuit-bench" and manifest["api"] == "plugin_api.py"
    assert manifest["tab"] == {"path": "/circuit-bench", "hidden": True} and manifest["slots"] == []
    assert manifest["entry"] == "dist/noop.js" and manifest["icon"] == "Cpu"
    noop = (dash / manifest["entry"]).read_text(encoding="utf-8")
    assert "window.__HERMES_PLUGINS__?.register?.('circuit-bench'" in noop and "return null" in noop
    assert not (dash / "__init__.py").exists()  # loaded by file location only, never as circuit_bench.dashboard


def test_every_module_imports_with_schemdraw_and_pyserial_blocked(monkeypatch):
    real_import = builtins.__import__

    def guarded(name, *a, **kw):
        if name.split(".")[0] in ("schemdraw", "serial"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *a, **kw)

    ours = ("circuit_bench_api_core", "circuit_bench_api_routes", sup.LOADER_NAME)
    before = {n for n in sys.modules if n.split(".")[0] in ours}
    for name in before:
        monkeypatch.delitem(sys.modules, name)
    try:
        _import_everything_blocked(monkeypatch, guarded)
    finally:
        sup.shutdown()
        for name in [n for n in sys.modules if n.split(".")[0] in ours and n not in before]:
            sys.modules.pop(name, None)  # monkeypatch puts the earlier copies back


def _import_everything_blocked(monkeypatch, guarded):
    monkeypatch.setattr(builtins, "__import__", guarded)
    mod = sup.load_plugin_api()
    for folder, pkg in ((sup.PKG / "bench_core", "circuit_bench_api_core"),
                        (sup.PKG / "dashboard" / "routes", "circuit_bench_api_routes")):
        for path in sorted(folder.glob("*.py")):
            if path.stem != "__init__":
                importlib.import_module(f"{pkg}.{path.stem}")
    assert route_set(mod.router) == ROUTES
    # the routes still answer; schematics need schemdraw -> dependency_missing (503), never a crash
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(mod.router, prefix=sup.PREFIX)
    a = sup.Api(mod, app, app, None)
    a.err(a.post("/schematic", {"block": "led", "params": {"r_series": "270"}}), 503, "dependency_missing")
    assert a.get("/health").json()["ok"] is True


# --------------------------------------------------------------------------------------------- envelopes, status

def test_every_answer_is_an_envelope_with_the_contract_status(api):
    bad_json = api.post("/pins/check", content=b"{nope", headers={"content-type": "application/json"})
    assert api.err(bad_json, 400, "invalid_args")["action"] == "pins.check"
    api.err(api.post("/pins/check", [1, 2]), 400, "invalid_args")
    api.err(api.post("/pins/check", {"chip": "esp32s3", "assignments": [], "extra": 1}), 400, "invalid_args")
    api.err(api.post("/pins/check", {"chip": "esp99", "assignments": [{"mode": "out", "pin": 4}]}), 400, "unknown_chip")
    api.err(api.get("/projects/nope"), 404, "project_not_found")
    api.err(api.get("/boards/nope"), 400, "unknown_board")
    api.err(api.get("/jobs/j-9999-000000"), 404, "job_not_found")
    assert api.post("/calc/unknown", {}).status_code == 404  # no route for unknown calculators


def test_body_limits(api):
    big = {"bom": "R1 1k\n" * 60000}  # > 256 kB of CSV
    body = api.err(api.post("/solder/plan", big), 400, "invalid_args")
    assert "too large" in body["summary"]
    huge_log = {"log": "x" * (600 * 1024)}
    api.err(api.post("/crash/decode", huge_log), 400, "invalid_args")
    api.err(api.post("/pins/check", content=b"{}", headers={"content-length": "999999999"}), 400, "invalid_args")


def test_status_table_covers_every_error_code():
    common = sup.route_module("contracts")  # same codes in the route copy
    routes_common = importlib.import_module("circuit_bench_api_routes.common")
    assert set(routes_common.STATUS) == set(common.ERROR_CODES) == set(contracts.ERROR_CODES)
    assert routes_common.STATUS["project_conflict"] == 409 and routes_common.STATUS["port_busy"] == 423
    assert routes_common.STATUS["tool_missing"] == 503 and routes_common.STATUS["timeout"] == 504


def test_handlers_never_raise(api, monkeypatch):
    def boom(*a, **kw):
        raise ZeroDivisionError("/secret/path")

    monkeypatch.setattr(api.core("pins"), "check", boom)
    body = api.err(api.post("/pins/check", {"chip": "esp32s3", "assignments": [{"mode": "out", "pin": 4}]}), 502,
                   "tool_failed")
    assert "ZeroDivisionError" in body["summary"] and "secret" not in json.dumps(body)


# --------------------------------------------------------------------------------------------- projects

def test_project_create_get_list_patch_conflict(api, events):
    p = api.create("bench-a")
    assert p["rev"] == 1 and p["board"]["variant"] == "n16r8"
    api.err(api.post("/projects", {"id": "bench-a", "title": "again", "chip": "esp32s3"}), 409, "project_conflict")
    listed = api.ok(api.get("/projects"))["result"]["projects"]
    assert [x["id"] for x in listed] == ["bench-a"]
    ok = api.ok(api.patch("/projects/bench-a", {"expected_rev": 1, "ops": [
        {"op": "assign", "role": "LASER", "mode": "out", "pin": 35}]}))
    assert ok["result"]["rev"] == 2 and ok["result"]["project"]["assignments"][0]["verdict"] == "blocked"  # N16R8
    old = api.err(api.patch("/projects/bench-a", {"expected_rev": 1, "ops": [{"op": "note", "text": "x"}]}), 409,
                  "project_conflict")
    assert old["result"] == {"rev": 2}
    api.err(api.patch("/projects/bench-a", {"ops": []}), 400, "invalid_args")
    api.err(api.patch("/projects/bench-a", {"expected_rev": 2, "ops": [{"op": "erase"}]}), 400, "invalid_args")
    updated = events.of("project.updated")
    assert [(e["id"], e["rev"], e["by"]) for e in updated] == [("bench-a", 1, "ui"), ("bench-a", 2, "ui")]


@pytest.mark.parametrize("op", [
    {"op": "set_detected", "port": "/dev/ttyACM0", "mac": "aa:bb:cc:dd:ee:ff", "chip": "ESP32-S3"},
    {"op": "set_build", "ok": True, "elf_sha256": "b" * 64, "elf": ".pio/build/s3/firmware.elf"},
    {"op": "set_flash", "ok": True, "port": "/dev/ttyACM0", "mac": "aa:bb:cc:dd:ee:ff", "elf_sha256": "b" * 64},
    {"op": "set_debug", "last_panic": {"kind": "panic", "reason": "LoadProhibited"}},
])
def test_patch_refuses_result_ops(api, op):
    """A client cannot fake a detected board or an approved build through PATCH /projects/{id}."""
    api.create("bench-r")
    body = api.err(api.patch("/projects/bench-r", {"expected_rev": 1, "ops": [{"op": "note", "text": "x"}, op]}), 400,
                   "invalid_args")
    assert "written by Circuit Bench itself" in body["error"]["message"]
    p = api.project("bench-r")
    assert p["rev"] == 1 and p["board"]["detected"] is None and p["firmware"]["last_build"] is None


def test_damaged_project_is_422(api):
    api.create("bench-d")
    path = sup.route_module("project").path("bench-d") / "project.json"
    path.write_text("{broken", encoding="utf-8")
    api.err(api.get("/projects/bench-d"), 422, "project_damaged")


def test_firmware_example_copy(api, monkeypatch, tmp_path):
    examples = tmp_path / "examples"
    sup.write_firmware(examples / "laser-trigger", env="s3")
    (examples / "laser-trigger" / ".pio").mkdir()
    (examples / "laser-trigger" / ".pio" / "junk").write_text("x", encoding="utf-8")
    routes_projects = importlib.import_module("circuit_bench_api_routes.projects")
    monkeypatch.setattr(routes_projects, "examples_dir", lambda core: examples)
    api.create("bench-f")
    env = api.ok(api.post("/projects/bench-f/firmware/example", {"example": "laser-trigger"}))
    fw = env["result"]["project"]["firmware"]
    dst = Path(fw["dir"])
    assert fw["env"] == "s3" and dst.name == "firmware" and dst.parent.name == "bench-f"
    assert (dst / "src" / "main.cpp").is_file() and not (dst / ".pio").exists()
    (dst / "src" / "main.cpp").write_text("// edited by the user\n", encoding="utf-8")
    api.err(api.post("/projects/bench-f/firmware/example", {"example": "laser-trigger"}), 409, "project_conflict")
    assert (dst / "src" / "main.cpp").read_text(encoding="utf-8") == "// edited by the user\n"
    api.ok(api.post("/projects/bench-f/firmware/example", {"example": "laser-trigger", "overwrite": True}))
    assert "edited" not in (dst / "src" / "main.cpp").read_text(encoding="utf-8")
    for bad in ("../etc", "Laser", "a" * 49, 5):
        api.err(api.post("/projects/bench-f/firmware/example", {"example": bad}), 400, "invalid_args")
    api.err(api.post("/projects/bench-f/firmware/example", {"example": "radar"}), 400, "invalid_args")
    api.err(api.post("/projects/nope/firmware/example", {"example": "laser-trigger"}), 404, "project_not_found")


def test_demo_without_sim_module_is_503(api, monkeypatch):
    monkeypatch.setitem(sys.modules, f"{sup.CORE}.sim", None)  # the import fails as in an install without sim.py
    body = api.err(api.post("/projects/demo"), 503, "dependency_missing")
    assert body["action"] == "sim.demo"


def test_demo_with_sim(api, monkeypatch):
    monkeypatch.delitem(sys.modules, "circuit_bench_api_core.sim")
    first = api.ok(api.post("/projects/demo"))
    assert first["simulated"] is True
    second = api.ok(api.post("/projects/demo"))
    assert api.project("laser-trigger")["rev"] == (second["result"].get("rev") or second["result"]["project"]["rev"])


# --------------------------------------------------------------------------------------------- workshop

def test_pins_routes_with_and_without_project(api):
    body = {"chip": "esp32s3", "variant": "n16r8", "wifi": True, "devkit": "esp32-s3-devkitc-1",
            "assignments": [{"role": "LASER", "mode": "out", "pin": 14}, {"role": "BAD", "mode": "out", "pin": 35}]}
    res = api.ok(api.post("/pins/check", body))["result"]
    assert res["counts"]["blocked"] == 1
    api.create("bench-p")
    api.apply("bench-p", {"op": "set_board", "devkit": "esp32-s3-devkitc-1"},
              {"op": "assign", "role": "LASER", "mode": "out", "pin": 14})
    from_project = api.ok(api.post("/pins/check", {"project": "bench-p"}))["result"]
    assert [p["role"] for p in from_project["pins"]] == ["LASER"] and from_project["variant"] == "n16r8"
    sug = api.ok(api.post("/pins/suggest", {"project": "bench-p", "requests": [{"role": "BTN", "mode": "in_pullup"}]}))
    assert 14 in sug["result"]["taken"]
    info = api.ok(api.get("/pins/info", params={"chip": "esp32s3", "pin": "GPIO35", "variant": "n16r8"}))
    assert info["result"]["gpio"] == 35
    api.err(api.get("/pins/info", params={"chip": "esp32s3"}), 400, "invalid_args")
    api.err(api.post("/pins/check", {"project": "nope"}), 404, "project_not_found")
    api.create("bench-empty")
    api.err(api.post("/pins/check", {"project": "bench-empty"}), 400, "invalid_args")


@pytest.mark.parametrize(("kind", "params"), [
    ("led", {"v_supply": "3V3", "v_f": "2V", "i_f": "10mA"}),
    ("npn", {"v_drive": "3V3", "r_base": "1k", "i_load": "13mA", "part": "2N2222A", "r_pulldown": "10k"}),
    ("divider", {"v_in_max": "4.2V", "r1": "100k", "r2": "100k"}),
    ("i2c_pullup", {"v_dd": "3V3", "c_bus": "100pF"}),
    ("mosfet", {"i_load": "2A", "v_supply": "12V", "part": "AO3400A"}),
    ("ldo", {"v_in": "5V", "v_out": "3V3", "i_load": "500mA", "part": "AMS1117-3.3"}),
])
def test_calculators(api, kind, params):
    env = api.ok(api.post(f"/calc/{kind}", params))
    assert env["action"] == f"calc.{kind}" and contracts.validate_envelope(env) == []
    api.err(api.post(f"/calc/{kind}", {**params, "bogus": 1}), 400, "invalid_args")


def test_schematic_solder_and_board_layout(api):
    pytest.importorskip("schemdraw")
    api.create("bench-s")
    api.apply("bench-s", {"op": "set_board", "devkit": "esp32-s3-devkitc-1"})
    env = api.ok(api.post("/schematic", {"block": "npn_low_side", "project": "bench-s",
                                         "params": {"r_base": "1k", "r_pulldown": "10k"}}))
    assert env["result"]["svg"].lstrip().startswith("<") and env["result"]["wiring"]
    api.err(api.post("/schematic", {"params": {}}), 400, "invalid_args")
    plan = api.ok(api.post("/solder/plan", {"bom": "R1 1k\nQ1 2N2222A TO-92\nJ1 header", "project": "bench-s"}))
    steps = plan["result"]["steps"]
    stored = api.project("bench-s")["solder"]
    assert [s["id"] for s in stored["steps"]] == [s["id"] for s in steps]
    done = api.ok(api.post(f"/projects/bench-s/solder/{steps[0]['id']}", {"done": True}))
    assert done["action"] == "project.update" and done["result"]["project"]["solder"]["done"] == [steps[0]["id"]]
    api.ok(api.post(f"/projects/bench-s/solder/{steps[0]['id']}", {"done": False}))
    assert api.project("bench-s")["solder"]["done"] == []
    api.err(api.post("/projects/bench-s/solder/0000000000", {"done": True}), 400, "invalid_args")
    api.err(api.post(f"/projects/bench-s/solder/{steps[0]['id']}", {"done": "yes"}), 400, "invalid_args")
    layout = api.ok(api.get("/boards/esp32-s3-devkitc-1"))
    assert layout["action"] == "board.layout" and layout["sources"][0]["id"] == layout["result"]["source_id"]


def test_solder_plan_from_project_parts(api):
    api.create("bench-bom")
    api.apply("bench-bom", {"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "1 kΩ"},
                                                         {"ref": "D1", "kind": "led", "value": "red"}]})
    plan = api.ok(api.post("/solder/plan", {"project": "bench-bom"}))
    assert plan["result"]["parts_total"] == 2
    api.err(api.post("/solder/plan", {}), 400, "invalid_args")


# --------------------------------------------------------------------------------------------- ports, jobs

def test_ports_respect_the_hardware_switch(api, monkeypatch):
    calls = sup.mock_ports(monkeypatch, [("/dev/ttyACM0", 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    off = api.ok(api.get("/ports"))
    assert [p["device"] for p in off["result"]["ports"]] == ["sim://test-s3", "sim://test-c3"] and calls == []
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    on = api.ok(api.get("/ports"))
    assert [p["device"] for p in on["result"]["ports"]][0] == "/dev/ttyACM0"
    assert on["result"]["ports"][0]["kind"] == "usb_serial_jtag"


def sim_project(api, tmp_path, pid="bench-sim"):
    api.create(pid)
    fw = sup.write_firmware(tmp_path / f"fw-{pid}")
    api.apply(pid, {"op": "set_firmware", "dir": str(fw), "env": "s3"})
    return pid


def run_job(api, path, body, status=202):
    resp = api.post(path, body)
    env = resp.json()
    assert resp.status_code == status, env
    assert env["action"] == "job.get" and list(env["result"]) == ["job_id", "kind", "state", "progress", "started",
                                                                  "finished", "log_tail", "result"]
    return api.wait_job(env["result"]["job_id"])


def test_detect_build_flash_on_a_simulated_board(api, tmp_path, events):
    pid = sim_project(api, tmp_path)
    detected = run_job(api, "/board/detect", {"port": "sim://test-s3", "project": pid})
    assert detected["result"]["state"] == "done" and detected["simulated"] is True
    assert api.project(pid)["board"]["detected"]["mac"] == CONFIRM_MAC
    built = run_job(api, "/board/build", {"project": pid})
    assert built["result"]["state"] == "done" and built["result"]["result"]["simulated"] is True
    assert api.project(pid)["firmware"]["last_build"]["elf_sha256"] == sup.SHA_A
    # sim:// flashes without allow_flash (default false) but still wants the dialog's confirmation
    api.err(api.post("/board/flash", {"project": pid}), 409, "not_confirmed")
    wrong = {"port": "sim://test-s3", "mac": CONFIRM_MAC, "elf_sha256": "f" * 64}
    api.err(api.post("/board/flash", {"project": pid, "confirm": wrong}), 409, "not_confirmed")
    confirm = {"port": "sim://test-s3", "mac": CONFIRM_MAC, "elf_sha256": sup.SHA_A}
    flashed = run_job(api, "/board/flash", {"project": pid, "confirm": confirm})
    assert flashed["result"]["state"] == "done" and flashed["simulated"] is True
    assert flashed["result"]["result"]["simulated"] is True
    assert api.provider.flashed and api.provider.flashed[0][2] == "sim://test-s3"
    last = api.project(pid)["firmware"]["last_flash"]
    assert last["ok"] is True and last["mac"] == CONFIRM_MAC
    states = [(e["kind"], e["state"]) for e in events.of("job.updated")]
    for kind in ("detect", "build", "flash"):
        assert (kind, "running") in states and (kind, "done") in states


def test_job_inputs_are_checked_before_a_job_starts(api):
    api.err(api.post("/board/detect", {"port": "sim://test-s3", "before": "erase"}), 400, "invalid_args")
    api.err(api.post("/board/detect", {}), 400, "invalid_args")
    api.err(api.post("/board/detect", {"port": "sim://test-s3", "project": "nope"}), 404, "project_not_found")
    api.create("bench-j")
    api.err(api.post("/board/flash", {"project": "bench-j", "port": 5}), 400, "invalid_args")
    api.err(api.post("/board/flash", {"project": "bench-j"}), 409, "not_confirmed")  # never detected
    api.err(api.post("/board/flash", {"project": "bench-j", "port": "sim://test-s3"}), 409, "not_confirmed")
    api.err(api.post("/board/flash", {}), 400, "invalid_args")
    assert sup.route_module("jobs").table().list() == []


def test_build_needs_a_firmware_folder(api):
    api.create("bench-nofw")
    api.err(api.post("/board/build", {"project": "bench-nofw"}), 400, "invalid_args")
    api.err(api.post("/board/build", {"project": "nope"}), 404, "project_not_found")


def test_real_port_with_hardware_off_is_423_and_runs_nothing(api, tmp_path, fake_tools):  # noqa: F811
    pid = sim_project(api, tmp_path, "bench-real")
    confirm = {"port": "/dev/ttyUSB7", "mac": CONFIRM_MAC, "elf_sha256": "b" * 64}
    api.err(api.post("/board/flash", {"project": pid, "port": "/dev/ttyUSB7", "confirm": confirm}), 423, "sim_only")
    api.err(api.post("/board/detect", {"port": "/dev/ttyUSB7"}), 423, "sim_only")
    api.err(api.post("/serial/open", {"port": "/dev/ttyUSB7"}), 423, "sim_only")
    assert fake_tools.calls() == []
    assert sup.route_module("jobs").table().list() == []


def real_port_project(api, tmp_path, monkeypatch, pid="bench-hw"):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"allow_flash": True}))
    sim_project(api, tmp_path, pid)
    api.record(pid, {"op": "set_detected", "port": "/dev/ttyUSB7", "mac": CONFIRM_MAC, "chip": "ESP32-S3"},
               {"op": "set_build", "ok": True, "elf_sha256": "b" * 64, "elf": ".pio/build/s3/firmware.elf"})
    return pid


def test_flash_without_confirm_is_409(api, tmp_path, monkeypatch, fake_tools):  # noqa: F811
    pid = real_port_project(api, tmp_path, monkeypatch)
    body = api.err(api.post("/board/flash", {"project": pid}), 409, "not_confirmed")
    assert body["action"] == "board.flash"
    wrong = {"port": "/dev/ttyUSB7", "mac": "aa:bb:cc:dd:ee:00", "elf_sha256": "b" * 64}
    api.err(api.post("/board/flash", {"project": pid, "confirm": wrong}), 409, "not_confirmed")
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", "{}")
    good = {"port": "/dev/ttyUSB7", "mac": CONFIRM_MAC, "elf_sha256": "b" * 64}
    api.err(api.post("/board/flash", {"project": pid, "confirm": good}), 423, "flash_disabled")
    assert fake_tools.calls() == []


def test_confirmed_flash_hands_the_guard_to_board_flash(api, tmp_path, monkeypatch):
    pid = real_port_project(api, tmp_path, monkeypatch)
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")  # blocks agent flashes only; the Bench UI asks itself
    seen = {}

    def fake_flash(project_dir, env, port, *, expected_elf_sha256, guard, on_line=None, **kw):
        seen.update(dir=project_dir, env=env, port=port, sha=expected_elf_sha256, verdict=guard())
        seen["guard_kw"] = dict(guard.keywords)
        on_line("Writing at 0x00010000 [=====>     ] 52.3%")
        return contracts.envelope("board.flash", "Flashed.", {"ok": True, "port": port, "mac": None,
                                                              "elf_sha256": expected_elf_sha256})

    monkeypatch.setattr(api.core("board"), "flash", fake_flash)
    good = {"port": "/dev/ttyUSB7", "mac": CONFIRM_MAC, "elf_sha256": "b" * 64}
    job = run_job(api, "/board/flash", {"project": pid, "confirm": good})
    assert job["result"]["state"] == "done" and job["simulated"] is False
    assert seen["verdict"] is None and seen["port"] == "/dev/ttyUSB7" and seen["sha"] == "b" * 64
    kw = seen["guard_kw"]
    assert kw["via"] == "route" and kw["cron"] is False and kw["confirm"] == good and kw["settings"]["allow_flash"] is True
    assert job["result"]["log_tail"] == ["Writing at 0x00010000 [=====>     ] 52.3%"]
    assert api.project(pid)["firmware"]["last_flash"]["mac"] == CONFIRM_MAC  # from the detection


def test_confirmed_flash_to_a_missing_port_fails_in_the_job(api, tmp_path, monkeypatch, fake_tools):  # noqa: F811
    pid = real_port_project(api, tmp_path, monkeypatch)
    sup.mock_ports(monkeypatch, [])
    good = {"port": "/dev/ttyUSB7", "mac": CONFIRM_MAC, "elf_sha256": "b" * 64}
    job = run_job(api, "/board/flash", {"project": pid, "confirm": good})
    assert job["result"]["state"] == "failed" and job["result"]["result"]["error"]["code"] == "port_not_found"
    assert fake_tools.calls() == []  # nothing ran: the port does not exist
    assert api.project(pid)["firmware"]["last_flash"]["ok"] is False


def test_second_job_on_the_same_port_is_busy(api, tmp_path):
    import threading
    release = threading.Event()
    real_detect = api.provider.detect

    def slow_detect(port):
        release.wait(5)
        return real_detect(port)

    api.provider.detect = slow_detect
    first = api.post("/board/detect", {"port": "sim://test-s3"})
    assert first.status_code == 202
    api.err(api.post("/board/detect", {"port": "sim://test-s3"}), 423, "port_busy")
    release.set()
    assert api.wait_job(first.json()["result"]["job_id"])["result"]["state"] == "done"


def test_tool_copy_and_route_copy_share_broker_jobs_and_watcher(api):
    from circuit_bench.bench_core import jobs as tool_jobs
    from circuit_bench.bench_core import portwatch as tool_pw
    from circuit_bench.bench_core import serialport as tool_sp

    assert sup.route_module("jobs") is not tool_jobs  # two copies of the package ...
    assert sup.route_module("jobs").table() is tool_jobs.table()  # ... one job table
    assert sup.route_module("serialport").broker() is tool_sp.broker()
    assert sup.route_module("portwatch").watcher() is tool_pw.watcher()
    job = api.post("/board/detect", {"port": "sim://test-s3"}).json()["result"]
    assert tool_jobs.table().wait(job["job_id"], 5)["state"] == "done"
    tool_sp.open_port("sim://test-s3")
    assert bf.wait_for(lambda: len(api.get("/serial/tail", params={"port": "sim://test-s3"}).json()["result"]["lines"]) == 2)


def test_requests_keep_the_port_watcher_running(api, events, monkeypatch):
    pw = sup.route_module("portwatch").watcher()
    pw.interval = 0.02
    assert not pw.running
    api.get("/health")
    assert pw.active() and pw.running
    assert bf.wait_for(lambda: pw.polls >= 2)  # baseline taken from the route copy's board.list_ports()
    monkeypatch.setattr(api.provider, "ports", lambda: ["sim://test-s3", "sim://test-c3", "sim://plugged"])
    assert bf.wait_for(lambda: events.of("board.changed"))
    assert events.of("board.changed") == [{"port": "sim://plugged", "state": "linked", "simulated": True}]


# --------------------------------------------------------------------------------------------- crash, health, doctor

def test_crash_decode_with_project_and_log_ref(api, tmp_path):
    from test_crash_decode import fake_elf
    from test_crash_decode import log as crash_log

    pid = sim_project(api, tmp_path, "bench-crash")
    fw = Path(api.project(pid)["firmware"]["dir"])
    elf, _ = fake_elf(fw / ".pio" / "build" / "s3", scenario="xtensa_store_prohibited.a2l.json", project=fw)
    api.record(pid, {"op": "set_build", "ok": True, "elf": ".pio/build/s3/firmware.elf",
                     "elf_sha256": "c" * 64})
    text = crash_log("xtensa_store_prohibited.log")
    ref = sup.route_module("serialport").write_artifact("panic", text.splitlines())
    env = api.ok(api.post("/crash/decode", {"log_ref": ref, "project": pid}))
    assert env["result"]["frames"] and any(f.get("function") not in (None, "??") for f in env["result"]["frames"])
    panic = api.project(pid)["debug"]["last_panic"]
    assert panic["log_ref"] == ref and panic["reason"]
    plain = api.ok(api.post("/crash/decode", {"log": text, "elf": str(elf), "chip": "esp32s3"}))
    assert plain["result"]["reason"] == env["result"]["reason"]
    api.err(api.post("/crash/decode", {}), 400, "invalid_args")
    api.err(api.post("/crash/decode", {"log": "x", "log_ref": ref}), 400, "invalid_args")
    api.err(api.post("/crash/decode", {"log_ref": "../../etc/passwd"}), 400, "invalid_args")
    api.err(api.post("/crash/decode", {"log_ref": "panic-20990101-000000.log"}), 400, "invalid_args")


def test_health(api, fake_tools, monkeypatch):  # noqa: F811
    fake_tools.scenario({"--version": {"stdout": "PlatformIO Core, version 6.2.0\n"},
                         "version": {"stdout": "esptool v5.6.0\n"}})
    env = api.ok(api.get("/health"))
    res = env["result"]
    assert res["plugin"] == "circuit-bench" and res["version"] == "0.1.0"
    assert res["tools"]["pio"] == "6.2.0" and res["tools"]["esptool"] == "5.6.0"
    assert res["hardware_access"] is False and res["allow_flash"] is False and env["simulated"] is True
    assert res["epoch"] == sup.route_module("runtime").get("serial.epoch", str)
    assert "hardware access off" in env["summary"]
    assert set(res["dependencies"]) == {"schemdraw", "pyserial"}
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": "/nonexistent/pio"}))
    missing = api.ok(api.get("/health"))
    assert missing["result"]["tools"]["pio"] is None and "pio missing" in missing["summary"]


def test_doctor_without_module_is_503(api, monkeypatch):
    monkeypatch.setitem(sys.modules, f"{sup.CORE}.doctor", None)  # the import fails as in an install without doctor.py
    body = api.err(api.get("/doctor"), 503, "dependency_missing")
    assert body["action"] == "doctor.run"


def test_doctor_with_module(api):
    env = api.get("/doctor").json()
    assert env["action"] == "doctor.run" and contracts.validate_envelope(env) == []

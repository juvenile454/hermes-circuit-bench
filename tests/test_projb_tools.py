"""Tool handlers on bench_core: envelopes, project writes, approvals in the handler, size limit.

Nothing here reaches hardware: CIRCUIT_BENCH_HW=off (conftest) unless a test switches it on, the real serial port
list is replaced, board actions on real ports are replaced by tripwires, and sim:// is the TestProvider of tests/board_fixtures.py.
"""
import json
import os
import sys
import types
from pathlib import Path

import board_fixtures as bf
import pytest

from circuit_bench import hooks, schemas, tools
from circuit_bench.bench_core import board, contracts, project, runtime, serialport

SHA = "a" * 64
REAL = "/dev/ttyCB0"  # never exists; tripwires stop any board call on it
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crash"


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    import circuit_bench.bench_core as core

    def unmocked():
        raise AssertionError("test called the real serial port list")

    monkeypatch.setattr(board, "_comports", unmocked)
    monkeypatch.delattr(core, "sim", raising=False)
    monkeypatch.setitem(sys.modules, "circuit_bench.bench_core.sim", None)  # TestProvider plays sim://
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    yield
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


@pytest.fixture
def host():
    return tools.Host(hook_active=True)


@pytest.fixture
def sim():
    prov = bf.TestProvider()
    board.register_provider("sim://", prov)
    return prov


@pytest.fixture
def tripwires(monkeypatch):
    calls = []

    def trip(name):
        def f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} must not run")
        return f

    monkeypatch.setattr(board, "detect", trip("board.detect"))
    monkeypatch.setattr(board, "flash", trip("board.flash"))
    monkeypatch.setattr(serialport, "monitor", trip("serialport.monitor"))
    return calls


def settings(monkeypatch, **values):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps(values))


TASK = "t"  # the task id Hermes passes to the hook and the handler alike


def call(host, name, **args):
    out = tools.make_handlers(host)[name](args, task_id=TASK)
    assert isinstance(out, str)
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode("utf-8")) <= tools.MAX_BYTES
    return env


def mk(host, pid="laser-trigger", **extra):
    env = call(host, "bench_project", action="create", id=pid, title="Laser trigger", chip="esp32s3", variant="n16r8",
               devkit="esp32-s3-devkitc-1", **extra)
    assert env["ok"], env
    return env


def fw_dir(tmp_path):
    d = tmp_path / "fw"
    d.mkdir(exist_ok=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32\n", encoding="utf-8")
    return d


def ready_for_real_flash(tmp_path, pid="laser-trigger"):
    """Project with a detected real board and a successful build (written directly, as detect/build would)."""
    rev = project.get(pid)["result"]["rev"]
    env = project.update(pid, rev, [
        {"op": "set_detected", "port": REAL, "mac": "aa:bb:cc:dd:ee:ff", "chip": "ESP32-S3 (QFN56)"},
        {"op": "set_firmware", "dir": str(fw_dir(tmp_path)), "env": "s3"},
        {"op": "set_build", "ok": True, "elf_sha256": SHA, "elf": ".pio/build/s3/firmware.elf"}], by="ui", trusted=True)
    assert env["ok"], env
    return env["result"]["project"]


# --------------------------------------------------------------------------------------------- robustness

@pytest.mark.parametrize("name", schemas.NAMES)
@pytest.mark.parametrize("args", [None, [], "bench", 5, 2.5, True])
def test_non_object_arguments(host, name, args):
    env = json.loads(tools.make_handlers(host)[name](args))
    assert contracts.validate_envelope(env) == []
    assert env["error"]["code"] == "invalid_args"


@pytest.mark.parametrize("name", schemas.NAMES)
def test_unknown_action(host, name):
    env = call(host, name, action="explode")
    assert env["error"]["code"] == "invalid_args" and "explode" in env["error"]["message"]
    env = call(host, name)
    assert env["error"]["code"] == "invalid_args"


FUZZ = [None, True, -1, 2.5, "", "x", "y" * 3000, [], [{}], [1, "a"], {}, {"a": [1]}]


@pytest.mark.parametrize("schema", schemas.ALL, ids=lambda s: s["name"])
def test_fuzz_wrong_types_never_raise(host, schema, tmp_path, tripwires):
    mk(host, "fuzz-p")
    name = schema["name"]
    props = [p for p in schema["parameters"]["properties"] if p != "action"]
    n = 0
    for action in schema["parameters"]["properties"]["action"]["enum"]:
        if name == "bench_project" and action == "create":
            continue  # would create projects named after fuzz values; covered by its own tests
        for base in ({"action": action}, {"action": action, "project": "fuzz-p", "id": "fuzz-p"}):
            for prop in props:
                for value in FUZZ:
                    call(host, name, **{**base, prop: value})
                    n += 1
    assert n >= 2 * len(props) * len(FUZZ)
    assert tripwires == []


def test_unexpected_exception_is_contained_without_details(host, monkeypatch, caplog):
    from circuit_bench.bench_core import pins

    def boom(*a, **k):
        raise RuntimeError("secret-token-123")

    monkeypatch.setattr(pins, "check", boom)
    out = tools.make_handlers(host)["bench_pins"]({"action": "check", "chip": "esp32s3",
                                                     "assignments": [{"role": "A", "mode": "out", "pin": 4}]})
    env = json.loads(out)
    assert env["error"]["code"] == "tool_failed" and "RuntimeError" in env["error"]["message"]
    assert "secret-token-123" not in out
    assert "secret-token-123" not in caplog.text


def test_unserialisable_answer_still_returns_json(host, monkeypatch):
    from circuit_bench.bench_core import pins
    monkeypatch.setattr(pins, "info", lambda *a, **k: {"ok": True, "x": object(), "y": float("nan")})
    out = tools.make_handlers(host)["bench_pins"]({"action": "info", "chip": "esp32s3", "pin": 4})
    assert json.loads(out.replace("NaN", "null"))


def test_large_answers_are_cut_to_8_kb(host, monkeypatch):
    from circuit_bench.bench_core import pins
    big = contracts.envelope("pins.check", "big", {"pins": [{"role": f"R{i}", "text": "z" * 500} for i in range(200)]},
                             checks=[contracts.check(f"c{i}", "passed", "d" * 400) for i in range(50)],
                             warnings=[contracts.warning(f"w{i}", "info", "m" * 400) for i in range(50)])
    monkeypatch.setattr(pins, "check", lambda *a, **k: big)
    env = call(host, "bench_pins", action="check", chip="esp32s3", assignments=[{"role": "A", "mode": "out", "pin": 4}])
    assert env["result"]["truncated"] is True
    assert any(w["code"] == "result_truncated" for w in env["warnings"])


def test_fit_keeps_small_envelopes_untouched():
    env = contracts.envelope("pins.check", "ok", {"a": 1})
    assert tools.fit(env) is env


def test_fit_last_resort():
    env = contracts.envelope("pins.check", "s" * 20000, {"a": "b" * 20000},
                             sources=[{"id": f"s{i}", "title": "t" * 300, "url": "u" * 300, "retrieved": "x", "note": "n" * 900}
                                      for i in range(40)])
    out = tools.fit(env)
    assert len(json.dumps(out, ensure_ascii=False).encode()) <= tools.MAX_BYTES
    assert contracts.validate_envelope(out) == []


# --------------------------------------------------------------------------------------------- bench_project

def test_create_with_assignments_judges_pins(host):
    env = mk(host, assignments=[{"role": "LASER", "mode": "out", "pin": 14},
                                {"role": "BUTTON", "mode": "in_pullup", "pin": 35}])
    assert env["action"] == "project.create"
    res = env["result"]
    assert res["rev"] == 2 and "project" not in res
    verdicts = {a["role"]: (a["verdict"], a["rule_ids"]) for a in res["assignments"]}
    assert verdicts["LASER"] == ("ok", [])
    assert verdicts["BUTTON"] == ("blocked", ["s3.octal_psram"])
    assert any(w["code"] == "pin_blocked" and w["severity"] == "danger" for w in env["warnings"])
    assert any(s["id"] == "idf-v6.1-gpio-esp32s3" for s in env["sources"])


def test_create_twice_conflicts(host):
    mk(host)
    env = call(host, "bench_project", action="create", id="laser-trigger", chip="esp32s3")
    assert env["error"]["code"] == "project_conflict"


def test_create_wifi_off(host):
    env = mk(host, "wifi-off", wifi=False)
    assert env["result"]["options"]["wifi"] is False
    assert not any(a["key"] == "wifi" for a in env["assumptions"])


def test_get_is_a_compact_view(host, tmp_path):
    mk(host, assignments=[{"role": "LASER", "mode": "out", "pin": 14}])
    env = call(host, "bench_project", action="get", id="laser-trigger")
    p = env["result"]["project"]
    assert set(p) == {"id", "title", "rev", "simulated", "board", "options", "assignments", "parts", "calcs",
                      "circuits", "solder", "firmware", "last_panic", "notes"}
    assert p["assignments"] == [{"role": "LASER", "mode": "out", "pin": 14, "net": None, "verdict": "ok", "rule_ids": []}]
    assert call(host, "bench_project", action="get", id="nope")["error"]["code"] == "project_not_found"


def test_list(host):
    assert call(host, "bench_project", action="list")["result"]["projects"] == []
    mk(host)
    assert [p["id"] for p in call(host, "bench_project", action="list")["result"]["projects"]] == ["laser-trigger"]


def test_update_ops(host, tmp_path):
    mk(host, assignments=[{"role": "LASER", "mode": "out", "pin": 14}])
    env = call(host, "bench_project", action="assign", id="laser-trigger",
               assignments=[{"role": "BUTTON", "mode": "in_pullup", "pin": 2, "net": "BTN"}])
    assert env["result"]["changed"] == ["assignments"]
    assert [a["role"] for a in env["result"]["assignments"]] == ["BUTTON"]  # only the touched assignment
    env = call(host, "bench_project", action="assign", id="laser-trigger", role="VBAT", mode="adc", pin=1)
    assert env["ok"] and env["result"]["assignments"][0]["role"] == "VBAT"
    env = call(host, "bench_project", action="set_board", id="laser-trigger", wifi=False)
    assert env["result"]["options"]["wifi"] is False and len(env["result"]["assignments"]) == 3
    env = call(host, "bench_project", action="unassign", id="laser-trigger", role="VBAT")
    assert env["result"]["removed"] == ["VBAT"] and env["result"]["remaining_roles"] == ["LASER", "BUTTON"]
    env = call(host, "bench_project", action="note", id="laser-trigger", text="first try")
    assert env["result"]["notes"] == 1
    env = call(host, "bench_project", action="add_parts", id="laser-trigger",
               parts=[{"ref": "R1", "kind": "resistor", "value": "1k"}, {"ref": "Q1", "kind": "transistor", "value": "2N2222A"}])
    assert env["result"]["parts"] == 2
    env = call(host, "bench_project", action="remove_parts", id="laser-trigger", refs=["q1"])
    assert env["ok"] and env["result"]["parts"] == 1 and env["result"]["removed_parts"] == ["Q1"]
    assert [x["ref"] for x in project.get("laser-trigger")["result"]["project"]["parts"]] == ["R1"]
    d = fw_dir(tmp_path)
    env = call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(d), env="s3")
    assert env["result"]["firmware"] == {"dir": str(d.resolve()), "env": "s3"}
    p = project.get("laser-trigger")["result"]["project"]
    assert p["rev"] == 10 and all(a["updated_by"] == "agent" for a in p["assignments"])


def test_update_errors(host):
    mk(host)
    env = call(host, "bench_project", action="assign", id="laser-trigger", assignments=[{"role": "X", "mode": "fly", "pin": 4}])
    assert env["error"]["code"] == "invalid_args" and "mode" in env["error"]["message"]
    env = call(host, "bench_project", action="note", id="laser-trigger", text="x", rev=7)
    assert env["error"]["code"] == "project_conflict" and env["result"]["rev"] == 1
    assert call(host, "bench_project", action="set_board", id="laser-trigger")["error"]["code"] == "invalid_args"
    env = call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir="relative/dir", env="s3")
    assert env["error"]["code"] == "invalid_args"
    pkg = Path(tools.__file__).resolve().parent
    env = call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(pkg), env="s3")
    assert "plugin package" in env["error"]["message"]
    assert call(host, "bench_project", action="note", id="ghost", text="x")["error"]["code"] == "project_not_found"


def test_concurrent_ui_change_is_retried(host, monkeypatch):
    mk(host)
    real = project.update
    state = {"n": 0}

    def racing(pid, rev, ops, *, by, trusted=False):
        if state["n"] == 0:  # the UI writes between the agent's read and write
            state["n"] += 1
            assert real(pid, rev, [{"op": "note", "text": "from ui"}], by="ui")["ok"]
        return real(pid, rev, ops, by=by, trusted=trusted)

    monkeypatch.setattr(project, "update", racing)
    env = call(host, "bench_project", action="note", id="laser-trigger", text="from agent")
    assert env["ok"] and env["result"]["rev"] == 3


def test_demo_without_simulator(host):
    env = call(host, "bench_project", action="demo")
    assert env["action"] == "sim.demo" and env["error"]["code"] == "dependency_missing"


# --------------------------------------------------------------------------------------------- bench_pins

def test_pins_from_project(host):
    mk(host, assignments=[{"role": "LASER", "mode": "out", "pin": 14}, {"role": "BUTTON", "mode": "in_pullup", "pin": 35}])
    env = call(host, "bench_pins", action="check", project="laser-trigger")
    assert env["result"]["counts"]["blocked"] == 1 and env["result"]["variant"] == "n16r8"
    env = call(host, "bench_pins", action="suggest", project="laser-trigger", requests=[{"role": "BUTTON", "mode": "in_pullup"}])
    suggested = [s["gpio"] for s in env["result"]["requests"][0]["suggestions"]]
    assert suggested and 14 not in suggested and 35 not in suggested
    env = call(host, "bench_pins", action="info", project="laser-trigger", pin=35)
    assert env["ok"] and "GPIO35" in env["summary"]


def test_pins_without_project(host):
    env = call(host, "bench_pins", action="check", chip="esp32s3", variant="n16r8",
               assignments=[{"role": "BUTTON", "mode": "in_pullup", "pin": 35}])
    assert env["result"]["counts"]["blocked"] == 1
    assert {"key": "wifi", "value": "on", "reason": "not given; Wi-Fi on applies the stricter pin rules"} in env["assumptions"]
    env = call(host, "bench_pins", action="check", chip="esp32s3", wifi=False, assignments=[{"role": "A", "mode": "out", "pin": 4}])
    assert not any(a["key"] == "wifi" for a in env["assumptions"])
    assert call(host, "bench_pins", action="check", assignments=[{"role": "A", "mode": "out", "pin": 4}])["error"]["code"] == "invalid_args"
    assert call(host, "bench_pins", action="check", chip="esp32s3")["error"]["code"] == "invalid_args"
    assert call(host, "bench_pins", action="info", chip="esp32s3")["error"]["code"] == "invalid_args"
    assert call(host, "bench_pins", action="check", chip="esp99", assignments=[{"role": "A", "mode": "out", "pin": 4}])["ok"] is False


def test_pins_other_chip_does_not_inherit_the_variant(host):
    mk(host)
    env = call(host, "bench_pins", action="check", project="laser-trigger", chip="esp32c3",
               assignments=[{"role": "A", "mode": "out", "pin": 4}])
    assert env["ok"], env


# --------------------------------------------------------------------------------------------- bench_calc

def test_calc_without_project(host):
    env = call(host, "bench_calc", action="led", inputs={"v_supply": "3V3", "v_f": "2V", "i_f": "5mA"})
    assert env["ok"] and env["result"]["r_chosen"]["display"] == "270 Ω"
    env = call(host, "bench_calc", action="led", v_supply="3V3", v_f="2V", i_f="5mA")  # flat inputs tolerated
    assert env["ok"]
    assert call(host, "bench_calc", action="led", inputs="3V3")["error"]["code"] == "invalid_args"
    assert call(host, "bench_calc", action="led", inputs={"v_supply": "3V3"})["error"]["code"] == "invalid_args"


def test_calc_stored_in_project(host):
    mk(host)
    inputs = {"v_drive": "3V3", "r_base": "1k", "i_load": "20mA"}
    env = call(host, "bench_calc", action="npn", inputs=inputs, project="laser-trigger")
    assert env["result"]["project_update"]["calc_id"] == "npn-1"
    env = call(host, "bench_calc", action="npn", inputs=inputs, project="laser-trigger")
    assert env["result"]["project_update"]["calc_id"] == "npn-2"
    calcs = project.get("laser-trigger")["result"]["project"]["calcs"]
    assert [c["id"] for c in calcs] == ["npn-1", "npn-2"]
    assert calcs[0]["inputs"] == inputs and calcs[0]["type"] == "npn" and calcs[0]["sources"]
    env = call(host, "bench_calc", action="npn", inputs=inputs, project="ghost")
    assert env["error"]["code"] == "project_not_found"


# --------------------------------------------------------------------------------------------- bench_schematic

def test_schematic_without_project_writes_an_artifact(host):
    pytest.importorskip("schemdraw")
    env = call(host, "bench_schematic", action="render", block="led", params={"r_series": "270"}, gpio=4,
               devkit="esp32-s3-devkitc-1")
    assert env["ok"] and "svg" not in env["result"]
    path = Path(env["result"]["svg_path"])
    assert path.parent == serialport.artifacts_dir() and path.read_text(encoding="utf-8").lstrip().startswith("<")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert env["result"]["media"] == f"MEDIA:{path}"


def test_schematic_with_project_and_role(host, tmp_path):
    pytest.importorskip("schemdraw")
    mk(host, assignments=[{"role": "LASER", "mode": "out", "pin": 14}])
    out = tmp_path / "out"
    out.mkdir()
    env = call(host, "bench_schematic", action="render", block="npn_low_side", params={"r_base": "1k"},
               project="laser-trigger", role="LASER", out_dir=str(out))
    assert env["ok"], env
    assert env["result"]["project_update"]["circuit_id"] == "npn_low_side-gpio14"
    assert (project.artifacts_dir("laser-trigger") / "npn_low_side-gpio14.svg").is_file()
    assert Path(env["result"]["svg_path"]).parent == out
    circuits = project.get("laser-trigger")["result"]["project"]["circuits"]
    # the drawn net is stored with the circuit (role name, the assignment has no net)
    assert circuits == [{"id": "npn_low_side-gpio14", "block": "npn_low_side", "params": {"r_base": "1k", "net": "LASER"},
                         "svg": "artifacts/npn_low_side-gpio14.svg"}]
    env = call(host, "bench_schematic", action="render", block="npn_low_side", params={"r_base": "1k"},
               project="laser-trigger", role="LASER", out_dir=str(out))
    assert env["ok"] and Path(env["result"]["svg_path"]).name == "npn_low_side-gpio14-1.svg"  # never overwrites


def test_schematic_refusals(host, tmp_path):
    mk(host)
    pkg = Path(tools.__file__).resolve().parent
    for out_dir in ("relative", str(tmp_path / "missing"), str(pkg), str(pkg / "skills")):
        env = call(host, "bench_schematic", action="render", block="led", params={"r_series": "270"}, out_dir=out_dir)
        assert env["error"]["code"] == "invalid_args", out_dir
    env = call(host, "bench_schematic", action="render", block="led", params={"r_series": "270"}, project="laser-trigger",
               role="NOPE")
    assert env["error"]["code"] == "invalid_args"
    assert call(host, "bench_schematic", action="render", block="led", role="X")["error"]["code"] == "invalid_args"
    assert call(host, "bench_schematic", action="render", block="toaster")["ok"] is False
    assert call(host, "bench_schematic", action="render", block="led", params=[1])["error"]["code"] == "invalid_args"


# --------------------------------------------------------------------------------------------- bench_solder

BOM = "R1 1k 0805\nQ1 2N2222A TO-92\nC1 100uF elko\nLED1 red 3mm"


def test_solder_plan_and_steps_in_project(host):
    mk(host)
    env = call(host, "bench_solder", action="plan", bom=BOM, project="laser-trigger")
    assert env["ok"] and env["result"]["project_update"]["changed"] == ["parts", "solder"]
    p = project.get("laser-trigger")["result"]["project"]
    assert len(p["solder"]["steps"]) == 4 and [x["ref"] for x in p["parts"]] == ["R1", "Q1", "C1", "LED1"]
    first = p["solder"]["steps"][0]["id"]
    env = call(host, "bench_solder", action="step", project="laser-trigger", step_id=first)
    assert env["result"]["progress"] == {"done": 1, "total": 4}
    assert project.get("laser-trigger")["result"]["project"]["solder"]["done"] == [first]
    env = call(host, "bench_solder", action="step", project="laser-trigger", step_id=first, done=False)
    assert project.get("laser-trigger")["result"]["project"]["solder"]["done"] == []
    env = call(host, "bench_solder", action="plan", project="laser-trigger")  # from the stored parts
    assert env["ok"] and env["result"]["parts_total"] == 4
    assert call(host, "bench_solder", action="step", project="laser-trigger", step_id="0123456789")["ok"] is False


def test_solder_refusals(host):
    assert call(host, "bench_solder", action="step", step_id="x")["error"]["code"] == "invalid_args"
    assert call(host, "bench_solder", action="plan")["error"]["code"] == "invalid_args"
    assert call(host, "bench_solder", action="plan", bom=5)["error"]["code"] == "invalid_args"
    mk(host)
    assert call(host, "bench_solder", action="plan", project="laser-trigger")["error"]["code"] == "invalid_args"
    assert call(host, "bench_solder", action="step", project="laser-trigger", step_id="0123456789")["error"]["code"] == "invalid_args"


def test_big_bom_fits(host):
    rows = [{"ref": f"R{i}", "value": f"{i}k"} for i in range(1, 60)] + \
           [{"ref": f"C{i}", "value": "100uF elko"} for i in range(1, 30)] + [{"ref": f"X{i}", "value": "mystery"} for i in range(1, 20)]
    env = call(host, "bench_solder", action="plan", bom=rows)
    assert env["ok"]


# --------------------------------------------------------------------------------------------- bench_board (sim)

def test_ports_lists_sim(host, sim):
    env = call(host, "bench_board", action="ports")
    assert [p["device"] for p in env["result"]["ports"]] == ["sim://test-s3", "sim://test-c3"]


def test_sim_detect_build_flash_monitor_with_project(host, sim, tmp_path):
    mk(host)
    call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(fw_dir(tmp_path)), env="s3")
    env = call(host, "bench_board", action="detect", port="sim://test-s3", project="laser-trigger")
    assert env["ok"] and env["simulated"] and env["result"]["project_update"]["changed"] == ["board"]
    det = project.get("laser-trigger")["result"]["project"]["board"]["detected"]
    assert det["port"] == "sim://test-s3" and det["simulated"] is True
    env = call(host, "bench_board", action="build", project="laser-trigger")  # sim port from the detection
    assert env["ok"] and env["simulated"]
    assert project.get("laser-trigger")["result"]["project"]["firmware"]["last_build"]["elf_sha256"] == SHA
    env = call(host, "bench_board", action="flash", project="laser-trigger")  # no approval needed on sim://
    assert env["ok"] and env["simulated"] and len(sim.flashed) == 1
    last = project.get("laser-trigger")["result"]["project"]["firmware"]["last_flash"]
    assert last["ok"] is True and last["port"] == "sim://test-s3" and last["elf_sha256"] == SHA
    env = call(host, "bench_board", action="monitor", port="sim://test-s3", seconds=0.5)
    assert env["ok"] and env["simulated"] and env["result"]["lines"] == ["boot", "ready"]


def test_sim_flash_needs_a_build(host, sim):
    mk(host)
    call(host, "bench_board", action="detect", port="sim://test-s3", project="laser-trigger")
    env = call(host, "bench_board", action="flash", project="laser-trigger")
    assert env["error"]["code"] == "not_confirmed" and "build" in env["error"]["hint"]
    assert sim.flashed == []
    assert call(host, "bench_board", action="flash")["error"]["code"] == "not_confirmed"
    mk(host, "fresh")
    assert call(host, "bench_board", action="flash", project="fresh")["error"]["code"] == "not_confirmed"


def test_build_arguments(host, sim, tmp_path):
    mk(host)
    assert call(host, "bench_board", action="build", project="laser-trigger")["error"]["code"] == "invalid_args"
    d = fw_dir(tmp_path)
    call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(d), env="s3")
    other = tmp_path / "other"
    other.mkdir()
    env = call(host, "bench_board", action="build", project="laser-trigger", project_dir=str(other))
    assert env["error"]["code"] == "invalid_args"
    assert call(host, "bench_board", action="build", project="laser-trigger", env="c3")["error"]["code"] == "invalid_args"
    env = call(host, "bench_board", action="build", project_dir=str(d), env="s3", port="sim://test-s3")
    assert env["ok"] and env["simulated"]
    assert call(host, "bench_board", action="build", env="s3")["error"]["code"] == "invalid_args"


def test_cron_blocks_board_actions_even_on_sim(sim, tmp_path):
    cron_host = tools.Host(cron=lambda: True, hook_active=True)
    mk(cron_host)
    for action, extra in (("detect", {"port": "sim://test-s3"}), ("monitor", {"port": "sim://test-s3"})):
        env = call(cron_host, "bench_board", action=action, **extra)
        assert env["error"]["code"] == "unattended_blocked", action
    call(tools.Host(hook_active=True), "bench_board", action="detect", port="sim://test-s3", project="laser-trigger")
    call(tools.Host(hook_active=True), "bench_project", action="set_firmware", id="laser-trigger",
         firmware_dir=str(fw_dir(tmp_path)), env="s3")
    call(tools.Host(hook_active=True), "bench_board", action="build", project="laser-trigger")
    env = call(cron_host, "bench_board", action="flash", project="laser-trigger")
    assert env["error"]["code"] == "unattended_blocked" and sim.flashed == []


def test_cron_probe_failure_counts_as_cron():
    def broken():
        raise RuntimeError("no context")

    assert tools.Host(cron=broken).cron() is True
    assert tools.Host(cron=lambda: False).cron() is False
    assert tools.Host().cron() is False


def test_cron_env_marker(monkeypatch):
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    assert tools.Host(cron=lambda: False).cron() is True


# --------------------------------------------------------------------------------------------- bench_board (real ports)

@pytest.mark.parametrize("action", ["detect", "monitor", "flash"])
def test_real_ports_with_hardware_off(host, tripwires, tmp_path, action):
    mk(host)
    ready_for_real_flash(tmp_path)
    env = call(host, "bench_board", action=action, port=REAL, project="laser-trigger", seconds=1)
    assert env["error"]["code"] == "sim_only"
    assert tripwires == []


@pytest.mark.parametrize("action", ["detect", "monitor", "flash"])
def test_real_ports_refused_without_hook(bf_hw_on, monkeypatch, tripwires, tmp_path, action):
    settings(monkeypatch, allow_flash=True)
    nohook = tools.Host(hook_active=False)
    mk(nohook)
    ready_for_real_flash(tmp_path)
    env = call(nohook, "bench_board", action=action, port=REAL, project="laser-trigger", seconds=1)
    assert env["error"]["code"] == "not_confirmed" and "hook" in env["error"]["message"]
    assert tripwires == []


@pytest.fixture
def bf_hw_on(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")


def test_real_flash_refusals_in_the_handler(bf_hw_on, host, monkeypatch, tripwires, tmp_path):
    mk(host)
    env = call(host, "bench_board", action="flash", project="laser-trigger", port=REAL)
    assert env["error"]["code"] == "flash_disabled"
    settings(monkeypatch, allow_flash=True)
    env = call(host, "bench_board", action="flash", project="laser-trigger", port=REAL)
    assert env["error"]["code"] == "not_confirmed"  # no detection, no build
    ready_for_real_flash(tmp_path)
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    env = call(host, "bench_board", action="flash", project="laser-trigger")
    assert env["error"]["code"] == "unattended_blocked" and "Bench UI" in env["error"]["hint"]
    assert tripwires == []


def test_real_flash_passes_guard_and_hash(bf_hw_on, host, monkeypatch, tmp_path):
    settings(monkeypatch, allow_flash=True)
    mk(host)
    p = ready_for_real_flash(tmp_path)
    seen = {}

    def fake_flash(project_dir, env, port, *, expected_elf_sha256, guard, expected_images=None, devkit=None,
                   expected_board=None):
        seen.update(dir=project_dir, env=env, port=port, sha=expected_elf_sha256, verdict=guard(),
                    mac=(expected_board or {}).get("mac"))
        return contracts.envelope("board.flash", "flashed", {"ok": True, "port": port, "mac": "aa:bb:cc:dd:ee:ff",
                                                             "elf_sha256": expected_elf_sha256})

    monkeypatch.setattr(board, "flash", fake_flash)
    args = {"action": "flash", "project": "laser-trigger", "elf_sha256": SHA[:12]}
    assert hooks.decide(host, "bench_board", args, TASK)["action"] == "approve"  # Hermes asks; the user says yes
    env = call(host, "bench_board", **args)
    assert env["ok"] and seen == {"dir": p["firmware"]["dir"], "env": "s3", "port": REAL, "sha": SHA, "verdict": None,
                                  "mac": "aa:bb:cc:dd:ee:ff"}  # the detection goes along
    assert project.get("laser-trigger")["result"]["project"]["firmware"]["last_flash"]["port"] == REAL
    seen.clear()
    env = call(host, "bench_board", **args)  # one approval, one flash
    assert env["error"]["code"] == "not_confirmed" and seen == {}
    hooks.decide(host, "bench_board", args, TASK)
    host.hook_active = False
    env = call(host, "bench_board", **args)
    assert env["error"]["code"] == "not_confirmed" and "hook" in env["error"]["message"] and seen == {}


def _approved(host, sha=SHA):
    args = {"action": "flash", "project": "laser-trigger", "elf_sha256": sha}
    d = hooks.decide(host, "bench_board", args, TASK)
    assert d["action"] == "approve", d
    return args


def test_build_between_hook_and_handler_is_refused(bf_hw_on, host, monkeypatch, tmp_path):
    """TOCTOU: the user approved build A; a build B lands before the handler runs -> nothing is flashed."""
    settings(monkeypatch, allow_flash=True)
    mk(host)
    ready_for_real_flash(tmp_path)
    monkeypatch.setattr(board, "flash", lambda *a, **k: pytest.fail("board.flash ran"))
    args = _approved(host)
    other = "c" * 64
    rev = project.get("laser-trigger")["result"]["rev"]
    assert project.update("laser-trigger", rev, [{"op": "set_build", "ok": True, "elf_sha256": other}], by="ui",
                          trusted=True)["ok"]
    env = call(host, "bench_board", **args)
    assert env["error"]["code"] == "elf_mismatch"
    # the model passes the new hash, but the user approved the old one: still refused
    rev = project.get("laser-trigger")["result"]["rev"]
    project.update("laser-trigger", rev, [{"op": "set_build", "ok": True, "elf_sha256": SHA}], by="ui", trusted=True)
    args = _approved(host, SHA)
    rev = project.get("laser-trigger")["result"]["rev"]
    project.update("laser-trigger", rev, [{"op": "set_build", "ok": True, "elf_sha256": other}], by="ui", trusted=True)
    env = call(host, "bench_board", **{**args, "elf_sha256": other})
    assert env["error"]["code"] == "elf_mismatch" and "after the approval" in env["error"]["message"]


def test_redetect_between_hook_and_handler_is_refused(bf_hw_on, host, monkeypatch, tmp_path):
    settings(monkeypatch, allow_flash=True)
    mk(host)
    ready_for_real_flash(tmp_path)
    monkeypatch.setattr(board, "flash", lambda *a, **k: pytest.fail("board.flash ran"))
    args = _approved(host)
    rev = project.get("laser-trigger")["result"]["rev"]
    assert project.update("laser-trigger", rev, [{"op": "set_detected", "port": REAL, "mac": "aa:bb:cc:dd:ee:01",
                                                  "chip": "ESP32-S3 (QFN56)"}],  # same chip (flash guard)
                          by="ui", trusted=True)["ok"]
    # set_detected keeps the build; only the board changed
    assert project.get("laser-trigger")["result"]["project"]["firmware"]["last_build"]["elf_sha256"] == SHA
    env = call(host, "bench_board", **args)
    assert env["error"]["code"] == "not_confirmed" and "board changed" in env["error"]["message"]


def test_real_flash_needs_elf_sha256_and_a_hook_entry(bf_hw_on, host, monkeypatch, tmp_path):
    settings(monkeypatch, allow_flash=True)
    mk(host)
    ready_for_real_flash(tmp_path)
    monkeypatch.setattr(board, "flash", lambda *a, **k: pytest.fail("board.flash ran"))
    env = call(host, "bench_board", action="flash", project="laser-trigger")
    assert env["error"]["code"] == "not_confirmed" and "elf_sha256" in env["error"]["message"]
    env = call(host, "bench_board", action="flash", project="laser-trigger", elf_sha256=SHA)  # no hook call before
    assert env["error"]["code"] == "not_confirmed" and "approval hook" in env["error"]["message"]
    env = call(host, "bench_board", action="flash", project="laser-trigger", elf_sha256="not-hex-at-all")
    assert env["error"]["code"] == "invalid_args"
    env = call(host, "bench_board", action="flash", project="laser-trigger", elf_sha256="c" * 12)
    assert env["error"]["code"] == "elf_mismatch"


def test_detect_on_real_port_records_and_warns_on_chip_mismatch(bf_hw_on, host, monkeypatch):
    mk(host)
    result = {"port": REAL, "mac": "aa:bb:cc:dd:ee:01", "chip": "ESP32-C3 (QFN32)", "chip_id": "esp32c3",
              "description": "x", "features": ["Wi-Fi"], "flash_size": "4MB", "variant_suggestion": None,
              "at": "2026-11-06T10:00:00Z", "simulated": False, "log_tail": ["..."]}
    monkeypatch.setattr(board, "detect", lambda port, **kw: contracts.envelope("board.detect", "detected", dict(result)))
    assert hooks.decide(host, "bench_board", {"action": "detect", "port": REAL}, TASK)["action"] == "approve"
    env = call(host, "bench_board", action="detect", port=REAL, project="laser-trigger")
    assert any(w["code"] == "chip_mismatch" for w in env["warnings"])
    det = project.get("laser-trigger")["result"]["project"]["board"]["detected"]
    assert det["mac"] == "aa:bb:cc:dd:ee:01" and det["simulated"] is False


def test_offline_build_and_decode_with_fake_pio(host, tmp_path, monkeypatch):
    """A real (non-sim) project: build through the fake pio, the ELF hash lands in the project; crash.decode takes the
    ELF of that stored build (no pio call)."""
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for name in ("esptool", "pio"):
        (fake / name).symlink_to(bf.FAKES_BIN / name)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    bf.FakeTools(fake).scenario("board-pio-build-ok.json")
    mk(host)
    d = fw_dir(tmp_path)
    (d / "src").mkdir()
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(d), env="s3")
    assert hooks.decide(host, "bench_board", {"action": "build", "project": "laser-trigger"}, TASK)["action"] == "approve"
    env = call(host, "bench_board", action="build", project="laser-trigger")
    assert env["ok"] and env["simulated"] is False, env
    build = project.get("laser-trigger")["result"]["project"]["firmware"]["last_build"]
    assert build["ok"] is True and build["elf_sha256"] == env["result"]["elf_sha256"] and build["ram_pct"] == 5.6
    env = call(host, "bench_crash", action="decode", log=_log(), project="laser-trigger")
    assert env["ok"] and not any(w["code"] == "elf_lookup_failed" for w in env["warnings"]), env


def test_board_argument_errors(host):
    assert call(host, "bench_board", action="detect")["error"]["code"] == "invalid_args"
    assert call(host, "bench_board", action="monitor")["error"]["code"] == "invalid_args"
    assert call(host, "bench_board", action="monitor", port="sim://x", seconds="ten")["error"]["code"] == "invalid_args"
    assert call(host, "bench_board", action="detect", port="sim://x", project="ghost")["error"]["code"] == "project_not_found"


# --------------------------------------------------------------------------------------------- bench_crash

def _log(name="arduino_timestamps.log"):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_crash_decode_text(host):
    env = call(host, "bench_crash", action="decode", log=_log(), chip="esp32s3")
    assert env["ok"] and env["result"]["reason"] and "StoreProhibited" in env["summary"]
    assert call(host, "bench_crash", action="decode")["error"]["code"] == "invalid_args"
    assert call(host, "bench_crash", action="decode", log=["x"])["error"]["code"] == "invalid_args"


def test_crash_decode_log_ref_and_project(host, tmp_path):
    mk(host)
    call(host, "bench_project", action="set_firmware", id="laser-trigger", firmware_dir=str(fw_dir(tmp_path)), env="s3")
    ref = serialport.write_artifact("panic", _log().splitlines())
    env = call(host, "bench_crash", action="decode", log_ref=ref, project="laser-trigger")
    assert env["ok"], env
    assert any(w["code"] == "elf_lookup_failed" for w in env["warnings"])  # no build is stored: the ELF is not looked up through pio
    panic = project.get("laser-trigger")["result"]["project"]["debug"]["last_panic"]
    assert panic["kind"] and panic["log_ref"] == ref
    env = call(host, "bench_crash", action="decode", log_ref="panic-20260101-000000.log")
    assert env["ok"] is False
    env = call(host, "bench_crash", action="decode", log_ref="../../etc/passwd")
    assert env["ok"] is False


def test_crash_sim_project_without_simulator(host, monkeypatch):
    mk(host)
    pdir = project.path("laser-trigger")
    data = json.loads((pdir / "project.json").read_text(encoding="utf-8"))
    data["simulated"] = True
    (pdir / "project.json").write_text(json.dumps(data), encoding="utf-8")
    os.chmod(pdir / "project.json", 0o600)
    env = call(host, "bench_crash", action="decode", log=_log(), project="laser-trigger")
    assert any(w["code"] == "sim_missing" for w in env["warnings"])

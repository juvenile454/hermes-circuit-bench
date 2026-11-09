"""desktop-src/fixtures/*.json against real route answers (the fixture contract).

Every fixture is compared with the answer of the matching route: recursive key structure of the envelope and its
result (lists: the union of the element keys). Fixtures stay untouched (the desktop UI builds against them); the known
differences are documented in ``EXCEPTIONS`` and must match exactly, so a new difference fails the test.

Diff notation: ``-path`` key only in the fixture, ``+path`` key only in the real answer, ``~path`` object/list/scalar
mismatch, ``?path`` one side is null (structure not comparable).

Script mode (writes the real answers, never into desktop-src/ unless that folder is given explicitly)::

    .venv/bin/python tests/test_api_fixtures.py --regen "$TMPDIR/cb-fixtures"
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:  # script mode
    sys.path.insert(0, str(TESTS))
if str(TESTS.parent) not in sys.path:
    sys.path.insert(0, str(TESTS.parent))

import board_fixtures as bf  # noqa: E402
import test_api_support as sup  # noqa: E402

FIXTURES = TESTS.parent / "desktop-src" / "fixtures"
MAC = "aa:bb:cc:dd:ee:ff"

# Known, intended differences between fixture and real answer (fixture name -> diff entries; all must occur).
EXCEPTIONS: dict[str, list[str]] = {
    # none: the fixtures were regenerated from real answers
}
# Differences that depend on the environment (allowed, not required): no Hermes distribution in the dev venv.
OPTIONAL: dict[str, set[str]] = {
    "health": {"?result.hermes"},
    # the fixture is the simulated chain: a simulated build has no ELF (elf_match null) and the sim boot log names
    # no reset reason after the panic (null); the synthetic route test has both. The UI shows both forms.
    "crash.decode": {"?result.elf_match", "?result.reset_reason"},
}
# Maps whose keys are data, not structure (not compared).
FREE_FORM: dict[str, set[str]] = {"crash.decode": {"result.registers"}}


# --------------------------------------------------------------------------------------------- key diff

def _merge(items: list) -> Any:
    dicts = [x for x in items if isinstance(x, dict)]
    if dicts and len(dicts) == len(items):
        merged: dict = {}
        for d in dicts:
            for k, v in d.items():
                if k not in merged or merged[k] is None:
                    merged[k] = v
        return merged
    return next((x for x in items if x is not None), None)


def key_diff(fix: Any, real: Any, path: str = "", skip: frozenset[str] | set[str] = frozenset()) -> list[str]:
    if path in skip:
        return []
    if fix is None or real is None:
        return [] if fix is real else [f"?{path}"]
    if isinstance(fix, dict) and isinstance(real, dict):
        out = []
        for k in fix:
            p = f"{path}.{k}" if path else k
            out += key_diff(fix[k], real[k], p, skip) if k in real else [f"-{p}"]
        out += [f"+{path}.{k}" if path else f"+{k}" for k in real if k not in fix]
        return out
    if isinstance(fix, list) and isinstance(real, list):
        if not fix or not real:
            return []
        return key_diff(_merge(fix), _merge(real), f"{path}[]", skip)
    kinds = tuple(dict if isinstance(x, dict) else list if isinstance(x, list) else object for x in (fix, real))
    return [] if kinds[0] is kinds[1] else [f"~{path}"]


# --------------------------------------------------------------------------------------------- generators

def diff_of(name: str, env: dict) -> list[str]:
    return key_diff(_fixture(name), env, skip=FREE_FORM.get(name, set()))


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _build_demo_project(api: sup.Api, tmp: Path) -> str:
    """The fixture project replayed through POST /projects and PATCH ops (proves every client field is writable);
    the results (detect, build, flash, panic) are recorded server-side like the jobs do."""
    p = _fixture("project.laser-trigger")["result"]["project"]
    b = p["board"]
    api.ok(api.post("/projects", {"id": p["id"], "title": p["title"], "chip": b["chip"], "variant": b["variant"],
                                  "devkit": b["devkit"], "simulated": p["simulated"]}))
    fw = sup.write_firmware(tmp / "laser-trigger-fw", env=p["firmware"]["env"])
    ops: list[dict] = [{"op": "set_board", "wifi": p["options"]["wifi"]}]
    ops += [{"op": "assign", **{k: a[k] for k in ("role", "mode", "pin", "net")}} for a in p["assignments"]]
    ops += [{"op": "add_parts", "parts": p["parts"]}]
    ops += [{"op": "add_calc", "calc": c} for c in p["calcs"]]
    ops += [{"op": "add_circuit", "circuit": c} for c in p["circuits"]]
    ops += [{"op": "set_solder_plan", "steps": p["solder"]["steps"]}]
    ops += [{"op": "solder_done", "step_id": s, "done": True} for s in p["solder"]["done"]]
    ops += [{"op": "set_firmware", "dir": str(fw), "env": p["firmware"]["env"]}]
    ops += [{"op": "note", "text": n["text"]} for n in p["notes"]]
    api.apply(p["id"], *ops)
    api.record(p["id"], {"op": "set_detected", **b["detected"]}, {"op": "set_build", **p["firmware"]["last_build"]},
               {"op": "set_flash", **p["firmware"]["last_flash"]}, {"op": "set_debug", "last_panic": p["debug"]["last_panic"]})
    return p["id"]


# The module demo project. Grows with the catalog (the fixtures are regenerated when modules are added); every
# module named here must be in circuit_bench/data/modules/.
MODULES_DEMO = {
    "id": "modules-demo", "title": "Weather station (modules demo)", "chip": "esp32s3", "variant": "n16r8",
    "devkit": "esp32-s3-devkitc-1",
    "assign": [{"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"},
               {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "SCL0"}],
    "modules": [  # DS3231 and MPU-6050 (AD0 low) share 0x68: the address conflict the desktop shows
        {"module": "bme280", "conn": {"SDI": "SDA0", "SCK": "SCL0", "SDO": "GND", "VDD": "3V3", "GND": "GND"}},
        {"module": "ds3231", "conn": {"SDA": "SDA0", "SCL": "SCL0", "VCC": "3V3", "GND": "GND"}},
        {"module": "mpu6050", "conn": {"SDA": "SDA0", "SCL": "SCL0", "AD0": "GND", "VDD": "3V3", "GND": "GND"}},
    ],
    "parts": [  # shared I²C pull-ups and one decoupling capacitor (satisfy mod.required_parts)
        {"ref": "R1", "kind": "resistor", "value": "4k7", "conn": {"1": "SDA0", "2": "3V3"}},
        {"ref": "R2", "kind": "resistor", "value": "4k7", "conn": {"1": "SCL0", "2": "3V3"}},
        {"ref": "C1", "kind": "capacitor", "value": "100nF", "conn": {"1": "3V3", "2": "GND"}},
    ],
    # a user-stated 3V3 budget of a battery build (synthetic demo value, limit_source "user"): the rail meter has a scale
    "ops": [{"op": "set_rails", "rail_limits": {"3V3": 0.05}}],
}
MODULE_INFO_FIXTURES = ("bme280", "ds3231", "mpu6050")  # modules.info.<id> fixtures (desktop catalog dialog)

# the stress project for the desktop shots: SCK and MOSI on one net (danger
# mod_net_shared_signals), a 3V3 rail limit (filled meter), a mux segment, no required parts (≥ 13 findings,
# so the check cuts and lists result.modules.counts.hidden).
_I2C0 = {"SDA": "SDA0", "SCL": "SCL0"}
MODULES_STRESS = {
    "id": "modules-stress", "title": "Module stress (shots)", "chip": "esp32s3", "variant": "n16r8",
    "devkit": "esp32-s3-devkitc-1",
    "assign": [{"role": "SDA", "mode": "i2c_sda", "pin": 8, "net": "SDA0"},
               {"role": "SCL", "mode": "i2c_scl", "pin": 9, "net": "SCL0"},
               {"role": "SCK", "mode": "spi_sck", "pin": 12, "net": "SPI0"},
               {"role": "MOSI", "mode": "spi_mosi", "pin": 11, "net": "SPI0"}],
    "modules": [
        {"module": "tca9548a", "conn": {**_I2C0, "VCC": "3V3", "GND": "GND", "A0": "GND", "A1": "GND", "A2": "GND",
                                        "SD0": "SDA1", "SC0": "SCL1"}},
        {"module": "bme280", "conn": {"SDI": "SDA1", "SCK": "SCL1", "SDO": "GND", "VDD": "3V3", "GND": "GND"}},
        {"module": "bme280", "conn": {"SDI": "SDA1", "SCK": "SCL1", "SDO": "GND", "VDD": "3V3", "GND": "GND"}},
        {"module": "max7219", "conn": {"DIN": "SPI0", "CLK": "SPI0", "V+": "3V3", "GND": "GND"}},
    ],
    "ops": [{"op": "set_rails", "rail_limits": {"3V3": 0.4}}],
}


def _build_modules_project(api: sup.Api, d: dict) -> str:
    api.ok(api.post("/projects", {"id": d["id"], "title": d["title"], "chip": d["chip"], "variant": d["variant"],
                                  "devkit": d["devkit"]}))
    api.apply(d["id"], *[{"op": "assign", **a} for a in d["assign"]], *[{"op": "add_module", **m} for m in d["modules"]],
              *([{"op": "add_parts", "parts": d["parts"]}] if d.get("parts") else []), *d.get("ops", []))
    return d["id"]


def _build_modules_demo(api: sup.Api) -> str:
    return _build_modules_project(api, MODULES_DEMO)


class DemoProvider(bf.TestProvider):
    """sim://esp32s3-n16r8 with the fixture's serial lines."""

    __test__ = False

    def ports(self):
        return [{"device": "sim://esp32s3-n16r8", "description": "Simulated ESP32-S3 N16R8"}]


def generate(api: sup.Api, mp: pytest.MonkeyPatch, tmp: Path) -> dict[str, dict]:
    """Real answers for every fixture (keys = fixture names)."""
    out: dict[str, dict] = {}
    serial_lines = [*_fixture("serial.lines")["result"]["lines"]]
    provider = DemoProvider(lines=[m["text"] for m in serial_lines])
    sup.route_module("board").register_provider("sim://", provider)
    sim = "sim://esp32s3-n16r8"

    # system
    tools_bin = tmp / "fakebin"
    tools_bin.mkdir(exist_ok=True)
    for name in ("esptool", "pio"):
        if not (tools_bin / name).exists():
            (tools_bin / name).symlink_to(bf.FAKES_BIN / name)
    scenario = json.loads((bf.SCENARIOS / "board-pio-build-ok.json").read_text(encoding="utf-8"))
    scenario["run"]["sleep"] = 1.0  # long enough to see the job running
    scenario.update({"--version": {"stdout": "PlatformIO Core, version 6.2.0\n"}, "version": {"stdout": "esptool v5.6.0\n"}})
    (tools_bin / "cb-fake-scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    mp.setenv("PATH", f"{tools_bin}{os.pathsep}{os.environ['PATH']}")
    out["health"] = api.get("/health").json()
    out["doctor"] = api.get("/doctor").json()

    # projects and board data
    pid = _build_demo_project(api, tmp)
    out["project.laser-trigger"] = api.get(f"/projects/{pid}").json()
    out["projects.list"] = api.get("/projects").json()
    # every board layout (ESP32-DevKitC V4, ESP32-C3-DevKitM-1 next to the S3-DevKitC-1)
    for board_id in sorted(p.stem for p in (TESTS.parent / "circuit_bench" / "data" / "boards").glob("*.json")):
        out[f"board.{board_id}"] = api.get(f"/boards/{board_id}").json()

    # pins
    pc = _fixture("pins.check")["result"]
    out["pins.check"] = api.post("/pins/check", {
        "chip": pc["chip"], "variant": pc["variant"], "wifi": pc["wifi"], "devkit": pc["devkit"],
        "assignments": [{"role": x["role"], "mode": x["mode"], "pin": x["pin"]} for x in pc["pins"]]}).json()
    ps = _fixture("pins.suggest")["result"]
    out["pins.suggest"] = api.post("/pins/suggest", {
        "chip": ps["chip"], "variant": ps["variant"], "wifi": ps["wifi"], "devkit": ps["devkit"], "taken": ps["taken"],
        "requests": [{"role": r["role"], "mode": r["mode"], "pin": r["requested"]} for r in ps["requests"]]}).json()
    pi = _fixture("pins.info")["result"]
    out["pins.info"] = api.get("/pins/info", params={"chip": pi["chip"], "pin": str(pi["gpio"]), "variant": pi["variant"],
                                                     "devkit": pi["devkit"]}).json()

    # modules: catalog, module info, the demo project and its check, calculator metadata
    out["modules.list"] = api.get("/modules?limit=200").json()  # the whole catalog: the fixture backend pages itself
    for mid in MODULE_INFO_FIXTURES:
        out[f"modules.info.{mid}"] = api.get(f"/modules/{mid}").json()
    mpid = _build_modules_demo(api)
    out["project.modules-demo"] = api.get(f"/projects/{mpid}").json()
    out["pins.check.modules-demo"] = api.post("/pins/check", {"project": mpid}).json()
    spid = _build_modules_project(api, MODULES_STRESS)
    out["project.modules-stress"] = api.get(f"/projects/{spid}").json()
    out["pins.check.modules-stress"] = api.post("/pins/check", {"project": spid}).json()
    out["calc.meta"] = api.get("/calc").json()

    # calculators, schematic, solder
    calc_inputs = {
        "led": {"v_supply": "3.3V", "v_f": "2V", "i_f": "10mA"},
        "npn": {"v_drive": "3.3V", "r_base": "1k", "i_load": "13mA", "v_be": "0.7V", "r_pulldown": "10k",
                "part": "2N2222A", "load": "laser"},
        "divider": {"v_in_max": "4.2V", "r1": "100k", "r2": "100k"},
        "i2c_pullup": {"v_dd": "3.3V", "c_bus": "100pF", "mode": "standard"},
        # 500 mA = minimum supply current of an ESP32-S3-WROOM-1 (datasheet v1.8, Table 6-2)
        "mosfet": {"i_load": "2A", "v_supply": "12V", "gate_v": "3.3V", "part": "AO3400A"},
        "ldo": {"v_in": "5V", "v_out": "3.3V", "i_load": "500mA", "part": "AMS1117-3.3"},
    }
    for kind, params in calc_inputs.items():
        out[f"calc.{kind}"] = api.post(f"/calc/{kind}", params).json()
    circuit = _fixture("project.laser-trigger")["result"]["project"]["circuits"][0]
    out["schematic.npn"] = api.post("/schematic", {"block": circuit["block"], "params": circuit["params"],
                                                   "devkit": "esp32-s3-devkitc-1", "gpio": 14}).json()
    # the LED block and a module part (WIRE shots draw them instead of the npn answer)
    out["schematic.led"] = api.post("/schematic", {"block": "led", "params": {"r_series": "150", "active": "high"},
                                                   "devkit": "esp32-s3-devkitc-1", "gpio": 5}).json()
    out["schematic.module"] = api.post("/schematic", {"block": "module", "params": {"part": "U1"},
                                                      "project": mpid}).json()
    parts = _fixture("project.laser-trigger")["result"]["project"]["parts"]
    out["solder.plan"] = api.post("/solder/plan", {"bom": parts}).json()

    # ports (hardware on with one mocked USB-Serial/JTAG board, plus the sim board)
    mp.setenv("CIRCUIT_BENCH_HW", "on")
    sup.mock_ports(mp, [("/dev/ttyACM0", 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    out["ports"] = api.get("/ports").json()
    mp.setenv("CIRCUIT_BENCH_HW", "off")

    # build running/done: the real board.build path with the fake pio (1 s build); flash done on the sim board
    build_pid = "fixture-build"
    api.ok(api.post("/projects", {"id": build_pid, "title": "Build", "chip": "esp32s3", "variant": "n16r8"}))
    api.apply(build_pid, {"op": "set_firmware", "dir": str(sup.write_firmware(tmp / "build-fw")), "env": "s3"})
    started = api.post("/board/build", {"project": build_pid}).json()["result"]
    running = api.get(f"/jobs/{started['job_id']}").json()
    for _ in range(500):
        if running["result"]["state"] == "running":
            break
        running = api.get(f"/jobs/{started['job_id']}").json()
    out["job.build.running"] = running
    out["job.build.done"] = api.wait_job(started["job_id"])
    jobs_pid = "fixture-jobs"
    api.ok(api.post("/projects", {"id": jobs_pid, "title": "Jobs", "chip": "esp32s3", "variant": "n16r8",
                                  "simulated": True}))
    api.apply(jobs_pid, {"op": "set_firmware", "dir": str(sup.write_firmware(tmp / "jobs-fw")), "env": "s3"})
    for path, body in (("/board/detect", {"port": sim, "project": jobs_pid}), ("/board/build", {"project": jobs_pid})):
        api.wait_job(api.post(path, body).json()["result"]["job_id"])
    confirm = {"port": sim, "mac": MAC, "elf_sha256": bf.SHA_A}
    flash = api.post("/board/flash", {"project": jobs_pid, "confirm": confirm}).json()["result"]
    out["job.flash.done"] = api.wait_job(flash["job_id"])

    # serial tail with a panic
    api.ok(api.post("/serial/open", {"port": sim}))
    assert bf.wait_for(lambda: api.get("/serial/tail", params={"port": sim}).json()["result"]["panic"], timeout=10)
    out["serial.lines"] = api.get("/serial/tail", params={"port": sim, "after": "0"}).json()
    api.ok(api.post("/serial/close", {"port": sim}))

    # crash decode with a (fake) ELF and the fake addr2line
    from test_crash_decode import fake_elf
    from test_crash_decode import log as crash_log
    elf, _ = fake_elf(tmp / "crash-fw" / ".pio" / "build" / "s3", scenario="xtensa_store_prohibited.a2l.json",
                      project=tmp / "crash-fw")
    out["crash.decode"] = api.post("/crash/decode", {"log": crash_log("xtensa_store_prohibited.log"), "elf": str(elf),
                                                     "chip": "esp32s3"}).json()
    return out


# --------------------------------------------------------------------------------------------- tests

def test_fixtures_against_real_answers(monkeypatch, tmp_path):
    with sup.api_session(monkeypatch) as api:
        generated = generate(api, monkeypatch, tmp_path)
    # every fixture has a generator (doctor only when bench_core.doctor exists)
    names = sorted(p.stem for p in FIXTURES.glob("*.json"))
    # sim.demo comes from the real simulated chain (scripts/gen_demo_fixtures.py, tests/test_demo_fixtures.py)
    # flash.check.* are generated and compared in tests/test_h_ui_flash_fixtures.py
    assert [n for n in names if n not in generated and n not in ("doctor", "sim.demo")
            and not n.startswith("flash.check.")] == []
    # every real answer is a valid envelope of the fixture's action
    contracts = sup.route_module("contracts")
    for name, env in generated.items():
        assert contracts.validate_envelope(env) == [], name
        assert env["ok"] is True, (name, env.get("error"))
        assert env["action"] == _fixture(name)["action"], name
    # same key structure, apart from the documented differences
    found = {}
    for name, env in generated.items():
        diff = [d for d in diff_of(name, env) if d not in OPTIONAL.get(name, set())]
        if diff:
            found[name] = sorted(diff)
    assert found == {k: sorted(v) for k, v in EXCEPTIONS.items() if k in generated}
    assert generated["job.build.running"]["result"]["state"] == "running"
    assert generated["job.build.done"]["result"]["state"] == generated["job.flash.done"]["result"]["state"] == "done"


def test_fixture_backend_names_the_real_blocks():
    """POST /schematic without a block names the real blocks in the fixture backend too."""
    from circuit_bench.bench_core import schematic
    text = (TESTS.parent / "desktop-src" / "lib" / "fixtures.js").read_text(encoding="utf-8")
    m = re.search(r"FIXTURE_BLOCKS = \[([^\]]*)\]", text)
    assert m and re.findall(r"'([a-z0-9_]+)'", m.group(1)) == [b["block"] for b in schematic.blocks()]


def test_key_diff():
    assert key_diff({"a": 1, "b": {"c": [{"d": 1}]}}, {"a": 2, "b": {"c": [{"d": 3, "e": 4}]}, "x": 0}) == \
        ["+b.c[].e", "+x"]
    assert key_diff({"a": {"b": 1}}, {"a": None}) == ["?a"]
    assert key_diff({"a": [1]}, {"a": {"b": 1}}) == ["~a"]
    assert key_diff({"a": []}, {"a": [{"z": 1}]}) == []
    assert key_diff({"a": 1, "b": 2}, {"b": 2}) == ["-a"]


# --------------------------------------------------------------------------------------------- script mode

def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "--regen":
        print(__doc__)
        return 2
    target = Path(argv[1]).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="cb-fixtures-") as t, pytest.MonkeyPatch.context() as mp:
        tmp = Path(t)
        for d in ("home", "hhome", "data"):
            (tmp / d).mkdir()
        for key, value in {"HOME": tmp / "home", "HERMES_HOME": tmp / "hhome", "CIRCUIT_BENCH_DATA_DIR": tmp / "data",
                           "CIRCUIT_BENCH_SETTINGS_JSON": "{}", "CIRCUIT_BENCH_HW": "off",
                           "CIRCUIT_BENCH_DEV_GUARD": "1"}.items():
            mp.setenv(key, str(value))
        mp.setenv("PATH", f"{bf.FAKES_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
        with contextlib.ExitStack() as stack:
            api = stack.enter_context(sup.api_session(mp))
            answers = generate(api, mp, tmp)
    target.mkdir(parents=True, exist_ok=True)
    for name, env in sorted(answers.items()):
        (target / f"{name}.json").write_text(json.dumps(env, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        diff = diff_of(name, env) if (FIXTURES / f"{name}.json").is_file() else ["(no fixture)"]
        print(f"{name}: {'same keys' if not diff else ' '.join(diff)}")
    print(f"wrote {len(answers)} answers to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

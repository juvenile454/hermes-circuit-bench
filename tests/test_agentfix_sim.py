"""The simulated board only emulates the demo firmware; foreign firmware is not replayed as if it
ran, monitor answers say the lines are synthetic, and a simulated flash does not claim a verified upload."""
from __future__ import annotations

import functools
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import board, contracts, guard, serialport, sim

EXAMPLE = sim.EXAMPLES_DIR / "laser-trigger"
FOREIGN = """#include <Arduino.h>
static const int PIN_LASER = 14;
void setup() { pinMode(PIN_LASER, OUTPUT); digitalWrite(PIN_LASER, LOW); Serial.begin(115200);
  Serial.println("probe-laser-trigger ready"); }
void loop() {}
"""


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    yield
    from circuit_bench.bench_core import runtime
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


def _approve(port=sim.PORT):
    return functools.partial(guard.check_flash, via="tool", settings=None, project=None, port=port, cron=False)


def _ok(env):
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"] is True, env
    return env


@pytest.fixture
def demo_fw(tmp_path) -> Path:
    dest = tmp_path / "demo-fw"
    shutil.copytree(EXAMPLE, dest)
    return dest


@pytest.fixture
def foreign_fw(tmp_path) -> Path:
    dest = tmp_path / "own-fw"
    shutil.copytree(EXAMPLE, dest)
    (dest / "src" / "main.cpp").write_text(FOREIGN, encoding="utf-8")
    return dest


def _flash(fw: Path) -> dict:
    built = _ok(board.build(fw, "s3", port=sim.PORT))
    demo = sim.demo_crash(fw) is not None
    assert ("sim_not_demo_firmware" in {w["code"] for w in built["warnings"]}) is not demo
    sha = built["result"]["elf_sha256"]
    return _ok(board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha, guard=_approve()))


def _monitor() -> dict:
    return _ok(serialport.monitor(sim.PORT, 0.6, reset=True))


@pytest.mark.parametrize("text", [FOREIGN, "int main() {}\n", "// DEMO_CRASH is mentioned only in a comment\nvoid setup(){}\n"])
def test_foreign_firmware_is_not_the_demo(tmp_path, text):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text(text, encoding="utf-8")
    assert sim.demo_crash(tmp_path) is None


@pytest.mark.parametrize(("old", "new", "expected"), [
    (None, None, True),
    ("#define DEMO_CRASH 1", "#define DEMO_CRASH 0", False),
    ("#define DEMO_CRASH 1\n", "", False),  # define removed: `#if !DEMO_CRASH` holds, as before
    (("#if !DEMO_CRASH\n  sensor_frame = frame_storage;  // the fix: the sensor frame gets its memory before the "
      "first sample\n#endif\n"), "  sensor_frame = frame_storage;\n", False),  # the scripted fix of the agent-fix scenario
])
def test_demo_firmware_and_its_fixes_stay_recognised(demo_fw, old, new, expected):
    if old is not None:
        main = demo_fw / "src" / "main.cpp"
        text = main.read_text(encoding="utf-8")
        assert old in text
        main.write_text(text.replace(old, new, 1), encoding="utf-8")
    assert sim.demo_crash(demo_fw) is expected


def test_foreign_firmware_flash_and_monitor_say_it_is_not_emulated(foreign_fw):
    env = _flash(foreign_fw)
    assert sim.board_state()["firmware"] == "unknown"
    warn = {w["code"]: w for w in env["warnings"]}["sim_not_demo_firmware"]
    assert warn["severity"] == "caution" and "bench_project demo" in warn["message"]
    assert "not output of your code" in warn["message"]
    mon = _monitor()
    lines = mon["result"]["lines"]
    assert lines == list(sim._log("boot.log"))  # ROM boot only, never the demo firmware's lines
    assert not any("[laser-trigger]" in t for t in lines)
    assert mon["result"]["lines_source"] == "rom_boot_only"
    assert "sim_not_demo_firmware" in {w["code"] for w in mon["warnings"]}
    assert {a["key"]: a for a in mon["assumptions"]}["lines"]["value"] == "synthetic"


def test_flash_verified_is_not_claimed_for_a_simulated_upload(demo_fw):
    env = _flash(demo_fw)
    checks = {c["id"]: c for c in env["checks"]}
    assert checks["board.flash.elf_hash"]["status"] == "passed"
    assert checks["board.flash.verified"]["status"] == "not_checked"
    assert checks["board.flash.verified"]["detail"] == "simulated: nothing was written"
    assert "sim_not_demo_firmware" not in {w["code"] for w in env["warnings"]}


def test_demo_path_panic_then_fix_then_boot_ok(demo_fw):
    _flash(demo_fw)
    mon = _monitor()
    assert mon["result"]["panics"] and mon["result"]["lines_source"] == "demo_firmware"
    assumptions = {a["key"]: a for a in mon["assumptions"]}
    assert assumptions["lines"]["value"] == "synthetic"
    assert "demo firmware" in assumptions["lines_source"]["reason"]
    assert "sim_not_demo_firmware" not in {w["code"] for w in mon["warnings"]}
    main = demo_fw / "src" / "main.cpp"
    main.write_text(main.read_text(encoding="utf-8").replace("#define DEMO_CRASH 1", "#define DEMO_CRASH 0"),
                    encoding="utf-8")
    _flash(demo_fw)
    mon = _monitor()
    assert "[laser-trigger] boot ok" in mon["result"]["lines"] and not mon["result"]["panics"]
    assert mon["result"]["lines_source"] == "demo_firmware"


def test_monitor_before_any_flash_names_rom_boot_only():
    mon = _monitor()
    assert mon["result"]["lines_source"] == "rom_boot_only"
    assert "nothing was flashed" in {a["key"]: a for a in mon["assumptions"]}["lines_source"]["reason"]


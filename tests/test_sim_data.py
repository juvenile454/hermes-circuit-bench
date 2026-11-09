"""Sim data and example firmware agree (decode.json lines vs. main.cpp, panic.log vs. decode.json, pins)."""
from __future__ import annotations

import json
import re

from circuit_bench.bench_core import crash, sim

EXAMPLE = sim.EXAMPLES_DIR / "laser-trigger"
MAIN = (EXAMPLE / "src" / "main.cpp").read_text(encoding="utf-8").splitlines()
A2L = re.compile(r"^(?P<func>[A-Za-z_][\w:]*)\((?P<args>[^)]*)\) at (?P<file>\S+):(?P<line>\d+)$")


def _decode_table() -> dict[int, dict]:
    raw = json.loads((sim.SIM_DIR / "decode.json").read_text(encoding="utf-8"))["addresses"]
    out = {}
    for addr, answer in raw.items():
        m = A2L.match(answer)
        assert m, answer
        out[int(addr, 16)] = {**m.groupdict(), "line": int(m["line"])}
    return out


def _body(func: str) -> range:
    """Line numbers (1-based) from the definition of ``func`` in main.cpp to its closing brace."""
    start = next(i for i, t in enumerate(MAIN) if re.match(rf"^(?:__attribute__\S*\s+)?\w[\w\s\*]*\b{func}\(", t))
    depth = 0
    for i in range(start, len(MAIN)):
        depth += MAIN[i].count("{") - MAIN[i].count("}")
        if depth == 0 and "}" in MAIN[i]:
            return range(start + 1, i + 2)
    raise AssertionError(f"no end of {func}")


def _panic() -> dict:
    return crash.parse("\n".join(sim._play({"firmware": "panic", "elf_sha256": "c" * 64})))


def test_decode_lines_lie_in_the_named_functions_of_main_cpp():
    table = _decode_table()
    project_lines = {a: e for a, e in table.items() if e["file"] == "{project}/src/main.cpp"}
    assert len(project_lines) >= 3
    for addr, e in project_lines.items():
        assert e["line"] in _body(e["func"]), (hex(addr), e, MAIN[e["line"] - 1])
    fw = [e for e in table.values() if e["file"].startswith("{framework}/")]
    assert [(e["func"], e["file"]) for e in fw] == [("loopTask", "{framework}/cores/esp32/main.cpp")]


def test_decode_lines_are_the_null_write_and_its_callers():
    p = _panic()
    table = _decode_table()
    frames = [table[int(b["pc"], 16)] for b in p["backtrace"]]
    assert [f["func"] for f in frames] == ["write_sensor_buffer", "sample_sensor", "setup", "loopTask"]
    assert re.search(r"\bbuf\[FRAME_VBAT\] = ", MAIN[frames[0]["line"] - 1])  # the write through buf (NULL)
    for callee, caller in zip(frames[:2], frames[1:3], strict=True):  # each caller line calls the frame above it
        assert f"{callee['func']}(" in MAIN[caller["line"] - 1], (caller, MAIN[caller["line"] - 1])
    assert frames[0]["args"] == "unsigned char*, unsigned int"
    assert "uint8_t *buf, uint32_t millivolts" in MAIN[frames[0]["line"] - 2]


def test_panic_log_is_consistent_with_the_registers():
    p = _panic()
    table = _decode_table()
    regs = p["registers"]
    assert p["reason"] == "StoreProhibited" and p["core"] == 1 and p["arch"] == "xtensa"
    assert regs["EXCCAUSE"] == "0x0000001d" and regs["EXCVADDR"] == "0x0000000c"  # FRAME_VBAT = 12 bytes from NULL
    assert "FRAME_VBAT = 12" in "\n".join(MAIN)
    bt = [int(b["pc"], 16) for b in p["backtrace"]]
    pc, a0 = int(regs["PC"], 16), int(regs["A0"], 16)
    assert bt[0] == pc - 3  # IDF prints every backtrace PC minus 3 (esp_cpu_process_stack_pc)
    assert a0 == 0x80000000 | ((bt[1] + 3) & 0x3FFFFFFF)  # call8 return address with the window bits
    assert int(regs["A2"], 16) == 0  # buf
    assert all(a in table for a in [pc, *bt])
    assert p["elf_sha256"] == "c" * 16


def test_logs_match_the_firmware_strings():
    text = "\n".join(MAIN)
    panic = sim._log("panic.log")
    fixed = sim._log("fixed.log")
    assert panic[0] == "[laser-trigger] boot, laser off" and f'"{panic[0]}"' in text
    assert "[laser-trigger] boot ok" in fixed and '"[laser-trigger] boot ok"' in text
    assert not any("Guru Meditation" in t for t in fixed)
    assert all(t.startswith("[laser-trigger] ") for t in fixed)
    assert sim._log("boot.log")[0].startswith("ESP-ROM:esp32s3")


def test_sim_json_data_is_synthetic():
    detect = json.loads((sim.SIM_DIR / "detect.json").read_text(encoding="utf-8"))
    assert detect["mac"] == "aa:bb:cc:dd:ee:ff"
    macs = set()
    for path in sim.SIM_DIR.iterdir():
        macs |= set(re.findall(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b", path.read_text(encoding="utf-8")))
    assert macs == {"aa:bb:cc:dd:ee:ff"}
    build = json.loads((sim.SIM_DIR / "build.json").read_text(encoding="utf-8"))
    assert build["ram_pct"] == round(100 * build["ram_used"] / build["ram_total"], 1)
    assert build["flash_pct"] == round(100 * build["flash_used"] / build["flash_total"], 1)
    assert sorted(p.name for p in sim.SIM_DIR.iterdir()) == ["boot.log", "build.json", "decode.json", "detect.json",
                                                              "fixed.log", "panic.log"]


def test_example_platformio_ini_is_pinned():
    ini = (EXAMPLE / "platformio.ini").read_text(encoding="utf-8")
    for line in ("[env:s3]", "platform = espressif32@6.9.0", "board = esp32-s3-devkitc-1", "framework = arduino",
                 "monitor_speed = 115200", "build_flags = -DARDUINO_USB_CDC_ON_BOOT=1"):
        assert re.search(rf"^{re.escape(line)}$", ini, re.MULTILINE), line
    assert not re.search(r"upload_port|upload_flags|erase", ini)


def test_example_pins_match_the_demo_recipe():
    recipe = json.loads((sim.DEMO_DIR / "laser-trigger.project.json").read_text(encoding="utf-8"))
    consts = dict(re.findall(r"static const uint8_t (\w+)_PIN = (\d+);", "\n".join(MAIN)))
    roles = {"LASER": "LASER", "BUTTON": "BUTTON", "SDA": "SDA", "SCL": "SCL", "VBAT": "VBAT"}
    assert {a["role"]: a["pin"] for a in recipe["assignments"]} == {r: int(consts[c]) for r, c in roles.items()}
    text = "\n".join(MAIN)
    assert "pinMode(BUTTON_PIN, INPUT_PULLUP)" in text and "pinMode(LASER_PIN, OUTPUT)" in text
    assert "Wire.begin(SDA_PIN, SCL_PIN)" in text and "analogReadMilliVolts(VBAT_PIN)" in text
    assert re.search(r"^#define DEMO_CRASH 1$", text, re.MULTILINE)
    assert sim.demo_crash(EXAMPLE) is True


def test_example_carries_the_laser_safety_notes():
    readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    assert "Laser safety" in readme and "Fix with Hermes" in readme and "DEMO_CRASH" in readme
    assert "LASER SAFETY" in "\n".join(MAIN[:10])
    assert "no mains" in readme.lower() or "low voltage" in readme.lower()

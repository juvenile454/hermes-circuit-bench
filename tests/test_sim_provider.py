"""The simulated board sim://esp32s3-n16r8 (provider protocol of board.py, hardware switch, line source)."""
from __future__ import annotations

import functools
import json
import os
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import board, clitools, contracts, guard, serialport, sim

EXAMPLE = sim.EXAMPLES_DIR / "laser-trigger"
FAKES_BIN = Path(__file__).resolve().parent / "fakes" / "bin"
SCENARIOS = Path(__file__).resolve().parent / "fakes" / "scenarios"


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    yield
    from circuit_bench.bench_core import runtime
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


@pytest.fixture
def fw(tmp_path) -> Path:
    dest = tmp_path / "fw"
    shutil.copytree(EXAMPLE, dest)
    return dest


def _ok(env):
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"] is True, env
    assert env["simulated"] is True, env
    return env


def _approve(port=sim.PORT):
    return functools.partial(guard.check_flash, via="tool", settings=None, project=None, port=port, cron=False)


def _set_crash(fw: Path, value: str) -> None:
    main = fw / "src" / "main.cpp"
    main.write_text(main.read_text(encoding="utf-8").replace("#define DEMO_CRASH 1", f"#define DEMO_CRASH {value}"),
                    encoding="utf-8")


def test_board_lists_the_sim_port_lazily_with_hardware_off():
    assert os.environ["CIRCUIT_BENCH_HW"] == "off"
    ports = board.list_ports()
    assert [p["device"] for p in ports] == [sim.PORT]
    assert ports[0]["simulated"] is True and ports[0]["kind"] == "sim" and ports[0]["vid"] is None
    env = _ok(board.ports())
    assert f"{sim.PORT} (simulated)" in env["summary"]
    assert isinstance(board.provider_for(sim.PORT), sim.SimBoard)


def test_sim_never_answers_for_real_ports(fw):
    assert board.provider_for("/dev/ttyACM0") is None
    for env in (board.detect("/dev/ttyACM0"),
                board.flash(fw, "s3", "/dev/ttyACM0", expected_elf_sha256="a" * 64, guard=_approve("/dev/ttyACM0"))):
        assert env["ok"] is False and env["error"]["code"] == "sim_only" and env["simulated"] is False
    with pytest.raises(contracts.BenchError) as e:
        serialport.open_port("/dev/ttyACM0")
    assert e.value.code == "sim_only"
    assert sim.board_state() == {"firmware": None}  # nothing reached the simulated board


def test_unknown_sim_port_is_not_found(fw):
    env = board.detect("sim://esp32c3-other")
    assert env["ok"] is False and env["error"]["code"] == "port_not_found" and env["simulated"] is True
    env = board.flash(fw, "s3", "sim://esp32c3-other", expected_elf_sha256=sim.source_sha256(fw),
                      guard=_approve("sim://esp32c3-other"))
    assert env["ok"] is False and env["error"]["code"] == "port_not_found"


def test_detect_is_simulated_with_placeholder_mac():
    env = _ok(board.detect(sim.PORT))
    r = env["result"]
    assert r["simulated"] is True and r["port"] == sim.PORT and r["mac"] == "aa:bb:cc:dd:ee:ff"
    assert r["variant_suggestion"] == "n16r8" and r["flash_size"] == "16MB" and r["chip"].startswith("ESP32-S3")
    assert {"port", "mac", "chip", "description", "features", "flash_size", "variant_suggestion", "at", "simulated"} <= set(r)
    assert all("{port}" not in line for line in r["log_tail"]) and any(sim.PORT in line for line in r["log_tail"])
    assert "(simulated)" in env["summary"]


def test_build_is_simulated_and_hashes_the_sources(fw, monkeypatch):
    def no_tools(*a, **kw):
        raise AssertionError("a simulated build must not run a tool")
    monkeypatch.setattr(clitools, "run", no_tools)
    env = _ok(board.build(fw, "s3", port=sim.PORT))
    r = env["result"]
    assert r["toolchain"] == "simulated" and r["simulated"] is True
    assert r["elf_sha256"] == sim.source_sha256(fw) and len(r["elf_sha256"]) == 64
    assert r["elf"] == ".pio/build/s3/firmware.elf" and r["elf_path"] == str(fw.resolve() / r["elf"])
    assert r["ram_pct"] == 5.9 and r["flash_pct"] == 8.5
    assert {c["id"]: c["status"] for c in env["checks"]} == {"board.build": "passed", "sim.build.compile": "skipped"}
    assert any(a["key"] == "elf_sha256" for a in env["assumptions"])
    _set_crash(fw, "0")
    assert _ok(board.build(fw, "s3", port=sim.PORT))["result"]["elf_sha256"] != r["elf_sha256"]


def test_build_checks_project_and_env(tmp_path, fw):
    env = board.build(tmp_path, "s3", port=sim.PORT)
    assert env["ok"] is False and env["error"]["code"] == "invalid_args" and env["simulated"] is True
    env = board.build(fw, "c3", port=sim.PORT)
    assert env["ok"] is False and "[env:c3]" in env["error"]["message"]
    (fw / "src" / "main.cpp").unlink()
    env = board.build(fw, "s3", port=sim.PORT)
    assert env["ok"] is False and env["error"]["code"] == "tool_failed"


def test_product_build_uses_real_pio_when_present(fw, tmp_path, monkeypatch):
    """Without the development guard (product) a sim build runs pio (here the fake pio) and keeps simulated: true."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pio").symlink_to(FAKES_BIN / "pio")
    shutil.copy(SCENARIOS / "board-pio-flash-ok.json", bin_dir / "cb-fake-scenario.json")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("CIRCUIT_BENCH_DEV_GUARD")
    from test_fix1_sim_packages import fake_core  # platform and every needed package installed (no download)
    fake_core(tmp_path / "pio-core")
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(tmp_path / "pio-core"))
    env = _ok(board.build(fw, "s3", port=sim.PORT))
    r = env["result"]
    elf = fw.resolve() / ".pio" / "build" / "s3" / "firmware.elf"
    assert r["toolchain"] == "pio" and r["elf_sha256"] == board.sha256_file(elf)
    assert "(real build, simulated board)" in env["summary"]
    assert {c["id"]: c["status"] for c in env["checks"]}["sim.build.compile"] == "passed"
    flashed = _ok(board.flash(fw, "s3", sim.PORT, expected_elf_sha256=r["elf_sha256"], guard=_approve()))
    assert flashed["result"]["elf_sha256"] == r["elf_sha256"]
    assert sim.board_state()["firmware"] == "panic"
    calls = [json.loads(x)["argv"][:1] for x in (bin_dir / "cb-fake-argv.log").read_text().splitlines()]
    assert ["run"] in calls and all("upload" not in c for c in calls)


def test_flash_switches_panic_and_fixed_by_demo_crash(fw):
    sha = _ok(board.build(fw, "s3", port=sim.PORT))["result"]["elf_sha256"]
    env = _ok(board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha, guard=_approve()))
    r = env["result"]
    assert r["port"] == sim.PORT and r["mac"] == "aa:bb:cc:dd:ee:ff" and r["verified"] is False  # a simulated flash is not verified
    assert any("(100 %)" in line for line in r["log_tail"])
    state = sim.board_state()
    assert state["firmware"] == "panic" and state["elf_sha256"] == sha and state["env"] == "s3"
    _set_crash(fw, "0")
    stale = board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha, guard=_approve())
    assert stale["ok"] is False and stale["error"]["code"] == "elf_mismatch"  # source changed after the build
    sha2 = _ok(board.build(fw, "s3", port=sim.PORT))["result"]["elf_sha256"]
    _ok(board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha2, guard=_approve()))
    assert sim.board_state()["firmware"] == "fixed"


def test_flash_needs_the_approval_check(fw):
    sha = sim.source_sha256(fw)
    env = board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha, guard=None)
    assert env["ok"] is False and env["error"]["code"] == "not_confirmed"
    assert sim.board_state() == {"firmware": None}


@pytest.mark.parametrize(("text", "expected"), [
    ("#define DEMO_CRASH 1\n", True), ("#define DEMO_CRASH 0\n", False), ("  #  define DEMO_CRASH  true\n", True),
    ("#define DEMO_CRASH false\n", False), ("int main() {}\n", None), ("#define DEMO_CRASH\n", True),  # None: not the demo
    ("// #define DEMO_CRASH 1\n#define DEMO_CRASH 0\n", False),
])
def test_demo_crash_parsing(tmp_path, text, expected):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text(text, encoding="utf-8")
    assert sim.demo_crash(tmp_path) is expected


def test_demo_crash_without_source(tmp_path):
    assert sim.demo_crash(tmp_path) is None


def test_source_hash_covers_ini_and_sources_only(fw):
    before = sim.source_sha256(fw)
    (fw / ".pio" / "build").mkdir(parents=True)
    (fw / ".pio" / "build" / "x.o").write_text("object", encoding="utf-8")
    (fw / "README.md").write_text("changed", encoding="utf-8")
    assert sim.source_sha256(fw) == before
    (fw / "include").mkdir()
    (fw / "include" / "cfg.h").write_text("#pragma once\n", encoding="utf-8")
    assert sim.source_sha256(fw) != before


def _state(firmware, sha="b" * 64):
    return {"firmware": firmware, "elf_sha256": sha}


def test_line_source_plays_a_bounded_panic_loop():
    boot = list(sim._log("boot.log"))
    lines = list(sim._play(_state("panic", "0123456789abcdef" + "0" * 48)))
    assert lines[:len(boot)] == boot
    assert sum(1 for t in lines if t.startswith("Guru Meditation Error")) == sim.PANIC_LOOPS
    assert lines.count("Rebooting...") == sim.PANIC_LOOPS and lines[-1] == "Rebooting..."
    assert "ELF file SHA256: 0123456789abcdef" in lines and not any("{" in t for t in lines)


def test_line_source_fixed_and_blank():
    fixed = list(sim._play(_state("fixed")))
    assert "[laser-trigger] boot ok" in fixed and not any("Guru Meditation" in t for t in fixed)
    assert fixed[-1] == list(sim._log("fixed.log"))[-1]
    assert list(sim._play({"firmware": None})) == list(sim._log("boot.log"))
    assert list(sim._play(_state("unknown"))) == list(sim._log("boot.log"))


def test_line_source_pauses_between_lines(monkeypatch):
    slept = []
    monkeypatch.setattr(sim, "TIME_SCALE", 1.0)
    monkeypatch.setattr(sim.time, "sleep", slept.append)
    lines = list(sim._play(_state("fixed")))
    assert len([s for s in slept if s == sim.LINE_DELAY_S]) == len(lines)
    assert sim.APP_START_S in slept and max(slept) <= 1.0  # the broker checks its stop flag between lines


def test_line_source_checks_the_port():
    with pytest.raises(contracts.BenchError) as e:
        sim.SimBoard().line_source("sim://nope")
    assert e.value.code == "port_not_found"


def test_monitor_on_the_sim_port_catches_the_panic(fw):
    sha = _ok(board.build(fw, "s3", port=sim.PORT))["result"]["elf_sha256"]
    _ok(board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha, guard=_approve()))
    env = _ok(serialport.monitor(sim.PORT, 0.5))
    r = env["result"]
    assert r["simulated"] is True and len(r["panics"]) == sim.PANIC_LOOPS
    assert r["panics"][0]["summary"] == "StoreProhibited · core 1"
    block = serialport.artifact_path(r["panics"][0]["log_ref"]).read_text(encoding="utf-8").splitlines()
    assert block[0].startswith("Guru Meditation Error") and block[-1] == "Rebooting..."
    assert f"ELF file SHA256: {sha[:16]}" in block
    assert "[laser-trigger] boot, laser off" in r["lines"]


def test_crash_runner_answers_like_addr2line(fw):
    run = sim.crash_runner(fw)
    assert run.simulated is True
    res = run(["xtensa-esp32s3-elf-addr2line", "-pfiaC", "-e", str(fw / ".pio/build/s3/firmware.elf"),
               "0x420019e1", "0x42003dc6", "0x40000000"], timeout=30, tail=200)
    assert res["rc"] == 0 and res["timed_out"] is False
    out = res["out_tail"]
    assert out[0] == f"0x420019e1: write_sensor_buffer(unsigned char*, unsigned int) at {fw}/src/main.cpp:44"
    assert out[1].startswith("0x42003dc6: loopTask(void*) at ") and out[1].endswith(
        "/.platformio/packages/framework-arduinoespressif32/cores/esp32/main.cpp:42")
    assert out[2] == "0x40000000: ?? ??:0"
    bad = run(["addr2line", "0x1"], timeout=30, tail=200)
    assert bad["rc"] == 2


def test_crash_runner_project_from_elf_or_relative(tmp_path):
    elf = tmp_path / "proj" / ".pio" / "build" / "s3" / "firmware.elf"
    res = sim.crash_runner()(["a2l", "-pfiaC", "-e", str(elf), "0x42001a01"], timeout=1, tail=10)
    assert res["out_tail"] == [f"0x42001a01: sample_sensor() at {tmp_path / 'proj'}/src/main.cpp:49"]
    res = sim.crash_runner()(["a2l", "-pfiaC", "-e", "firmware.elf", "0x42001a01"], timeout=1, tail=10)
    assert res["out_tail"] == ["0x42001a01: sample_sensor() at src/main.cpp:49"]


def test_sim_decode_is_simulated_and_points_to_main_cpp(fw):
    log = "\n".join(sim._play(_state("panic"))) + "\n"
    env = _ok(sim.decode(log, elf=fw / ".pio/build/s3/firmware.elf", project_dir=fw))
    r = env["result"]
    assert (r["reason"], r["core"], r["arch"]) == ("StoreProhibited", 1, "xtensa")
    assert [(f["function"].split("(")[0], f["file"], f["line"]) for f in r["frames"][:3]] == [
        ("write_sensor_buffer", "src/main.cpp", 44), ("sample_sensor", "src/main.cpp", 49), ("setup", "src/main.cpp", 74)]
    assert r["frames"][3]["file"] == "~/.platformio/packages/framework-arduinoespressif32/cores/esp32/main.cpp"
    assert env["summary"] == ("StoreProhibited on core 1 in write_sensor_buffer (src/main.cpp:44): write through a NULL "
                              "pointer at offset 12 bytes.")
    assert {"id": "crash.addr2line", "status": "passed", "detail": "4 of 4 frames resolved"} in env["checks"]
    assert r["elf_match"] is None  # a simulated build has no ELF to compare: skipped, never a fake "passed"
    assert any(a["key"] == "addr2line" and a["value"] == "simulated" for a in env["assumptions"])
    assert len(json.dumps(env)) <= contracts.MAX_RESULT_BYTES


def test_a_sim_build_that_would_start_pio_asks_first_and_is_refused_in_cron(fw, monkeypatch):
    """The real provider: once pio and every package are there (forced here), hook and handler treat the sim build
    like any build that runs the project's scripts; without them it stays simulated and nobody is asked."""
    from circuit_bench import hooks, tools
    started = []
    monkeypatch.setattr(sim, "_real_build_ready", lambda pdir, env: (True, []))
    monkeypatch.setattr(sim.SimBoard, "_real_build", lambda self, pdir, env, crash: started.append(env))
    args = {"action": "build", "project_dir": str(fw), "env": "s3", "port": sim.PORT}
    chat, cron = tools.Host(hook_active=True), tools.Host(cron=lambda: True, hook_active=True)
    asked = hooks.decide(chat, "bench_board", args)
    assert asked["action"] == "approve" and asked["message"].endswith("the build is a real offline build.")
    assert asked["rule_key"] == hooks.build_rule_key(str(fw.resolve()), "s3")
    assert hooks.decide(cron, "bench_board", args)["action"] == "block"
    assert tools.run_tool("bench_board", args, cron)["error"]["code"] == "unattended_blocked"
    assert tools.run_tool("bench_board", args, tools.Host(hook_active=False))["error"]["code"] == "not_confirmed"
    assert started == []
    monkeypatch.setattr(sim, "_real_build_ready", lambda pdir, env: (False, ["tool-scons"]))
    assert hooks.decide(chat, "bench_board", args) is None
    env = tools.run_tool("bench_board", args, cron)
    assert env["ok"] is True and env["simulated"] is True and started == []

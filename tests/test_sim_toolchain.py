"""Sim data with the real toolchain (marker toolchain, CB_TOOLCHAIN_TESTS=1).

Builds a copy of data/examples/laser-trigger offline with the user's PlatformIO (espressif32@6.9.0, no upload, no
serial port, build output in tmp_path) and checks the synthetic sim data against the real ELF:
- every decode.json answer equals the real ``xtensa-esp32s3-elf-addr2line -pfiaC`` output;
- the PC and backtrace of panic.log are the real store and call instructions (objdump);
- the sim chain of scripts/sim_probe.py with real builds: the panic log carries the real ELF hash, crash.decode
  matches it (elf_match true), the fixed firmware boots.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pwd
import re
import shutil
from pathlib import Path

import pytest

from circuit_bench import hooks, tools
from circuit_bench.bench_core import clitools, contracts, crash, sim

pytestmark = pytest.mark.toolchain

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PIO_CORE = Path(os.environ.get("CB_PIO_CORE_DIR") or REAL_HOME / ".platformio")
PIO = Path(os.environ.get("CB_PIO") or REAL_HOME / ".local" / "bin" / "pio")
TC = PIO_CORE / "packages" / "toolchain-xtensa-esp32s3" / "bin"
# the framework folder of the platform the example pins (several versions may sit side by side)
FRAMEWORK = Path(sim._framework_dir(core=PIO_CORE))
PROBE = Path(__file__).resolve().parent.parent / "scripts" / "sim_probe.py"
_INSN = re.compile(r"^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$")
_FUNC = re.compile(r"^([0-9a-f]+) <(.+)>:$")


def _pio_env(build_dir: Path) -> dict[str, str]:
    return {"PLATFORMIO_CORE_DIR": str(PIO_CORE), "PLATFORMIO_BUILD_DIR": str(build_dir),
            "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "No", "PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL": "3650"}


def _need_toolchain() -> None:
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1":
        pytest.skip("set CB_TOOLCHAIN_TESTS=1 (run: CB_TOOLCHAIN_TESTS=1 pytest -m toolchain)")
    missing = [str(p) for p in (PIO, TC / "xtensa-esp32s3-elf-addr2line", TC / "xtensa-esp32s3-elf-objdump",
                                PIO_CORE / "platforms" / "espressif32") if not p.exists()]
    if missing:
        pytest.skip(f"toolchain test needs: {', '.join(missing)}")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, Path]:
    _need_toolchain()
    root = tmp_path_factory.mktemp("sim-fw")
    project = root / "firmware"
    shutil.copytree(sim.EXAMPLES_DIR / "laser-trigger", project)
    res = clitools.run([str(PIO), "run", "-d", str(project), "-e", "s3", "-t", "checkprogsize", "-t", "buildprog"],
                       timeout=900, env_extra=_pio_env(root / "build"), tail=60)
    assert res["rc"] == 0 and not res["timed_out"], "\n".join(res["out_tail"])
    elf = root / "build" / "s3" / "firmware.elf"
    assert elf.is_file()
    return {"project": project, "elf": elf}


def _disassembly(elf: Path) -> dict[str, list[tuple[int, str, str]]]:
    res = clitools.run([str(TC / "xtensa-esp32s3-elf-objdump"), "-d", "-C", "--no-show-raw-insn", str(elf)],
                       timeout=120, hardware=False, tail=1_000_000)
    assert res["rc"] == 0
    funcs: dict[str, list[tuple[int, str, str]]] = {}
    current: list[tuple[int, str, str]] | None = None
    for line in res["out_tail"]:
        if m := _FUNC.match(line.strip()):
            current = funcs.setdefault(m[2], [])
        elif current is not None and (m := _INSN.match(line)):
            current.append((int(m[1], 16), m[2], m[3]))
    return funcs


def _panic() -> dict:
    return crash.parse("\n".join(sim._play({"firmware": "panic", "elf_sha256": "d" * 64})))


def test_decode_json_equals_real_addr2line(built):
    table = json.loads((sim.SIM_DIR / "decode.json").read_text(encoding="utf-8"))["addresses"]
    addrs = list(table)
    res = clitools.run([str(TC / "xtensa-esp32s3-elf-addr2line"), "-pfiaC", "-e", str(built["elf"]), *addrs],
                       timeout=60, hardware=False, tail=200)
    assert res["rc"] == 0, res
    expected = [f"0x{int(a, 16):08x}: " + table[a].replace("{project}", str(built["project"]))
                .replace("{framework}", str(FRAMEWORK)) for a in addrs]
    assert res["out_tail"] == expected


def test_panic_log_points_to_the_real_instructions(built):
    funcs = _disassembly(built["elf"])
    write = funcs["write_sensor_buffer(unsigned char*, unsigned int)"]
    store = [a for a, op, args in write if op == "s8i" and args.replace(" ", "").endswith(",a2,12")]
    calls = {name: [a for a, op, args in funcs[name] if op == "call8" and f"<{callee}>" in args]
             for name, callee in (("sample_sensor()", "write_sensor_buffer(unsigned char*, unsigned int)"),
                                  ("setup()", "sample_sensor()"), ("loopTask(void*)", "setup()"))}
    p = _panic()
    pc = int(p["registers"]["PC"], 16)
    bt = [int(b["pc"], 16) for b in p["backtrace"]]
    assert store == [pc]  # buf[FRAME_VBAT] = ... with buf (a2) == NULL
    assert bt == [pc - 3, calls["sample_sensor()"][0], calls["setup()"][0], calls["loopTask(void*)"][0]]


def test_sim_chain_with_real_builds(built, tmp_path, monkeypatch):
    """scripts/sim_probe.py's chain with real offline builds of the demo project's firmware copy."""
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(PIO)}))
    for key, value in _pio_env(tmp_path / "build").items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("cb_sim_probe", PROBE)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    lines: list[str] = []
    try:
        res = probe.chain(lines.append, timeout=900.0)
    finally:
        from circuit_bench.bench_core import runtime
        b = runtime.peek("broker")
        if b is not None:
            b.shutdown()
    builds = [s for s in res["steps"] if s["step"] == "board.build"]
    assert len(builds) == 2 and all("(real build, simulated board)" in s["summary"] for s in builds)
    assert all(s["simulated"] is True for s in res["steps"])
    dec = res["decode"]
    assert dec["result"]["elf_match"] is True  # panic.log carries the real ELF hash of the flashed build
    assert {"id": "crash.elf_match", "status": "passed", "detail": "ELF SHA256 prefix in the log matches the build"} \
        in dec["checks"]
    fw = res["project"]["firmware"]
    assert fw["last_flash"]["elf_sha256"] == fw["last_build"]["elf_sha256"]
    (rec,) = sim._builds().values()  # the last real build of firmware/ (env s3)
    assert rec["kind"] == "pio" and rec["crash"] is False and rec["sha"] == fw["last_build"]["elf_sha256"]
    assert Path(rec["elf"]).is_relative_to(tmp_path / "build")  # build output only in PLATFORMIO_BUILD_DIR
    top = dec["result"]["frames"][0]
    assert (top["function"], top["file"], top["line"]) == ("write_sensor_buffer(unsigned char*, unsigned int)",
                                                           "src/main.cpp", 44)
    assert "     serial: [laser-trigger] boot ok" in lines
    assert not (sim.EXAMPLES_DIR / "laser-trigger" / ".pio").exists()
    assert not (Path(fw["dir"]) / ".pio").exists()


def test_sim_build_runs_a_project_script_only_after_approval(tmp_path, monkeypatch):
    """A sim:// build that starts the real offline pio runs the project's ``extra_scripts``: in cron it is refused (the
    marker file is never written), with the hook it is asked first, and only the build after the approval runs it."""
    _need_toolchain()
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(PIO)}))
    for key, value in _pio_env(tmp_path / "build").items():
        monkeypatch.setenv(key, value)
    fw = tmp_path / "fw"
    shutil.copytree(sim.EXAMPLES_DIR / "laser-trigger", fw)
    marker = tmp_path / "marker.txt"
    (fw / "marker.py").write_text(f'Import("env")\nopen({str(marker)!r}, "w").write("ran")\n', encoding="utf-8")
    ini = fw / "platformio.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + "extra_scripts = pre:marker.py\n", encoding="utf-8")
    args = {"action": "build", "project_dir": str(fw), "env": "s3", "port": sim.PORT}

    def run(host):
        env = json.loads(tools.make_handlers(host)["bench_board"](args, task_id="t"))
        assert contracts.validate_envelope(env) == [], env
        return env

    cron = tools.Host(cron=lambda: True, hook_active=True)
    assert hooks.decide(cron, "bench_board", args)["action"] == "block"
    assert run(cron)["error"]["code"] == "unattended_blocked"
    assert not marker.exists()
    host = tools.Host(hook_active=True)
    decision = hooks.decide(host, "bench_board", args, "t")
    assert decision["action"] == "approve" and decision["rule_key"] == hooks.build_rule_key(str(fw.resolve()), "s3")
    assert not marker.exists()  # asking runs nothing
    env = run(host)
    assert env["ok"] and env["simulated"] is True, env
    assert marker.read_text(encoding="utf-8") == "ran"

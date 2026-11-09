"""Crash decoding with the real toolchain (marker toolchain, CB_TOOLCHAIN_TESTS=1).

Copies the example firmware data/examples/laser-trigger (write_sensor_buffer writes through a NULL pointer with
DEMO_CRASH 1) into tmp_path, builds it offline with the user's PlatformIO for ESP32-S3 (its own env s3) and ESP32-C3
(an extra env c3 in the copy only; no upload, no serial port), builds panic logs from the real instruction addresses
(objdump) and decodes them with the real addr2line. Expected lines come from main.cpp itself, not from constants.
"""
from __future__ import annotations

import hashlib
import os
import pwd
import re
import shutil
from pathlib import Path

import pytest

from circuit_bench.bench_core import clitools, crash

pytestmark = pytest.mark.toolchain

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PIO_CORE = Path(os.environ.get("CB_PIO_CORE_DIR") or REAL_HOME / ".platformio")
PIO = Path(os.environ.get("CB_PIO") or REAL_HOME / ".local" / "bin" / "pio")
EXAMPLE = Path(__file__).resolve().parent.parent / "circuit_bench" / "data" / "examples" / "laser-trigger"
TOOLCHAIN = {"s3": ("toolchain-xtensa-esp32s3", "xtensa-esp32s3-elf"), "c3": ("toolchain-riscv32-esp", "riscv32-esp-elf")}
C3_ENV = """
[env:c3]
platform = espressif32@6.9.0
board = esp32-c3-devkitm-1
framework = arduino
"""
_INSN = re.compile(r"^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$")
_FUNC = re.compile(r"^([0-9a-f]+) <(.+)>:$")


def tool(env: str, name: str) -> Path:
    pkg, prefix = TOOLCHAIN[env]
    return PIO_CORE / "packages" / pkg / "bin" / f"{prefix}-{name}"


@pytest.fixture(scope="module")
def firmware(tmp_path_factory) -> dict[str, Path]:
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1":
        pytest.skip("set CB_TOOLCHAIN_TESTS=1 (run: CB_TOOLCHAIN_TESTS=1 pytest -m toolchain)")
    missing = [str(p) for p in (PIO, EXAMPLE / "src" / "main.cpp", tool("s3", "gcc"), tool("c3", "gcc"),
                                PIO_CORE / "platforms" / "espressif32") if not p.exists()]
    if missing:
        pytest.skip(f"toolchain test needs: {', '.join(missing)}")
    root = tmp_path_factory.mktemp("crash-fw")
    project = root / "firmware"
    shutil.copytree(EXAMPLE, project)
    ini = project / "platformio.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + C3_ENV, encoding="utf-8")
    env = {"PLATFORMIO_CORE_DIR": str(PIO_CORE), "PLATFORMIO_BUILD_DIR": str(root / "build"),
           "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "No", "PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL": "3650"}
    res = clitools.run([str(PIO), "run", "-d", str(project), "-e", "s3", "-e", "c3", "-t", "checkprogsize",
                        "-t", "buildprog"], timeout=900, env_extra=env, tail=60)
    assert res["rc"] == 0 and not res["timed_out"], "\n".join(res["out_tail"])
    elfs = {e: root / "build" / e / "firmware.elf" for e in ("s3", "c3")}
    for elf in elfs.values():
        assert elf.is_file()
    return {"project": project, **elfs}


def disassembly(env: str, elf: Path) -> dict[str, list[tuple[int, str, str]]]:
    """{demangled function name without arguments: [(address, mnemonic, operands)]} from objdump -d."""
    res = clitools.run([str(tool(env, "objdump")), "-d", "-C", "--no-show-raw-insn", str(elf)], timeout=120,
                       hardware=False, tail=1_000_000)
    assert res["rc"] == 0
    funcs: dict[str, list[tuple[int, str, str]]] = {}
    current: list[tuple[int, str, str]] | None = None
    for line in res["out_tail"]:
        if m := _FUNC.match(line.strip()):
            current = funcs.setdefault(m[2].split("(", 1)[0], [])
        elif current is not None and (m := _INSN.match(line)):
            current.append((int(m[1], 16), m[2], m[3]))
    return funcs


def calls_to(code: list[tuple[int, str, str]], callee: str, ops: tuple[str, ...]) -> list[int]:
    return [a for a, op, args in code if op in ops and re.search(rf"<{re.escape(callee)}\(", args)]


def after(code: list[tuple[int, str, str]], addr: int) -> int:
    """Address of the instruction after ``addr`` (the return address of a call)."""
    addrs = [a for a, _, _ in code]
    return addrs[addrs.index(addr) + 1]


def source_line(pattern: str, start_at: str | None = None) -> int:
    """1-based line in the example's main.cpp matching ``pattern`` (after the line matching ``start_at``)."""
    lines = (EXAMPLE / "src" / "main.cpp").read_text(encoding="utf-8").splitlines()
    first = next(i for i, t in enumerate(lines) if re.search(start_at, t)) if start_at else 0
    return next(i + 1 for i in range(first, len(lines)) if re.search(pattern, lines[i]))


WRITE = source_line(r"\bbuf\[FRAME_VBAT\] = ")              # the store through buf (NULL with DEMO_CRASH 1)
CALL_WRITE = source_line(r"\bwrite_sensor_buffer\(sensor_frame")  # in sample_sensor()
CALL_SAMPLE = source_line(r"^\s*sample_sensor\(\);", r"^void setup\(\)")  # in setup()


def sha(elf: Path) -> str:
    return hashlib.sha256(elf.read_bytes()).hexdigest()


def test_example_case_xtensa_s3(firmware):
    elf, project = firmware["s3"], firmware["project"]
    code = disassembly("s3", elf)
    (crash_pc,) = [a for a, op, args in code["write_sensor_buffer"] if op == "s8i"]  # buf[12] = ...
    (caller,) = calls_to(code["sample_sensor"], "write_sensor_buffer", ("call8",))  # backtrace PC = return addr - 3
    outer = calls_to(code["setup"], "sample_sensor", ("call8",))[0]
    log = (
        "[laser-trigger] boot, laser off\n"
        "Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled.\n\n"
        "Core  1 register dump:\n"
        f"PC      : 0x{crash_pc:08x}  PS      : 0x00060030  A0      : 0x{0x80000000 | (caller + 3) & 0x3FFFFFFF:08x}"
        "  A1      : 0x3fcebf40\n"
        "A14     : 0x00000000  A15     : 0x00000000  SAR     : 0x00000000  EXCCAUSE: 0x0000001d\n"
        "EXCVADDR: 0x0000000c  LBEG    : 0x400570e8  LEND    : 0x400570f3  LCOUNT  : 0x00000000\n\n\n"
        f"Backtrace: 0x{crash_pc - 3:08x}:0x3fcebf40 0x{caller:08x}:0x3fcebf60 0x{outer:08x}:0x3fcebf80\n\n\n\n\n"
        f"ELF file SHA256: {sha(elf)[:16]}\n\nRebooting...\n"
    )
    env = crash.decode(log, elf=elf, cc_path=str(tool("s3", "gcc")), project_dir=project)
    assert env["ok"] is True, env
    frames = env["result"]["frames"]
    assert frames[0]["function"] == "write_sensor_buffer(unsigned char*, unsigned int)"
    assert (frames[0]["file"], frames[0]["line"], frames[0]["inlined"]) == ("src/main.cpp", WRITE, False)
    assert (frames[1]["function"], frames[1]["file"], frames[1]["line"]) == ("sample_sensor()", "src/main.cpp", CALL_WRITE)
    assert (frames[2]["function"], frames[2]["file"], frames[2]["line"]) == ("setup()", "src/main.cpp", CALL_SAMPLE)
    assert env["result"]["elf_match"] is True
    assert env["summary"] == (f"StoreProhibited on core 1 in write_sensor_buffer (src/main.cpp:{WRITE}): write through "
                              "a NULL pointer at offset 12 bytes.")
    assert env["checks"][1] == {"id": "crash.addr2line", "status": "passed", "detail": "3 of 3 frames resolved"}

    wrong = crash.decode(log.replace(sha(elf)[:16], "0123abcd0123abcd"), elf=elf, chip="esp32s3",
                         addr2line=str(tool("s3", "addr2line")), project_dir=project)
    assert wrong["result"]["elf_match"] is False
    assert "elf_mismatch" in [w["code"] for w in wrong["warnings"]]


def test_riscv_c3_mepc_ra_and_stack_scan(firmware, monkeypatch):
    elf, project = firmware["c3"], firmware["project"]
    code = disassembly("c3", elf)
    (mepc,) = [a for a, op, args in code["write_sensor_buffer"] if op == "sb"]  # sb a1, 12(a0)
    # sample_sensor() ends with a tail call (j write_sensor_buffer), so ra returns into setup()
    assert calls_to(code["sample_sensor"], "write_sensor_buffer", ("j", "c.j"))
    ra = after(code["setup"], calls_to(code["setup"], "sample_sensor", ("jal", "c.jal"))[0])
    in_loop_task = after(code["loopTask"], calls_to(code["loopTask"], "setup", ("jal", "c.jal"))[0])
    log = (
        "Guru Meditation Error: Core  0 panic'ed (Store access fault). Exception was unhandled.\n\n"
        "Core  0 register dump:\n"
        f"MEPC    : 0x{mepc:08x}  RA      : 0x{ra:08x}  SP      : 0x3fc8f2f0  GP      : 0x3fc8a600\n"
        "MSTATUS : 0x00001881  MTVEC   : 0x40380001  MCAUSE  : 0x00000007  MTVAL   : 0x0000000c\n"
        "MHARTID : 0x00000000\n\n"
        "Stack memory:\n"
        f"3fc8f2f0: 0xa5a5a5a5 0x3fc8f350 0x{in_loop_task:08x} 0x00000000 0x00000000 0x00000000 0x00000000 0x00000000\n\n"
        f"ELF file SHA256: {sha(elf)[:16]}\n\nRebooting...\n"
    )
    # no chip, no cc_path: the RISC-V dump picks riscv32-esp-elf-addr2line from PLATFORMIO_CORE_DIR (fakes off PATH)
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if "fakes" not in p))
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(PIO_CORE))
    assert crash.find_addr2line("esp32c3") == str(tool("c3", "addr2line"))
    env = crash.decode(log, elf=elf, project_dir=project)
    assert env["ok"] is True, env
    res = env["result"]
    assert res["arch"] == "riscv"
    f0, f1 = res["frames"][0], res["frames"][1]
    assert (f0["source"], f0["function"], f0["file"], f0["line"]) == (
        "mepc", "write_sensor_buffer(unsigned char*, unsigned long)", "src/main.cpp", WRITE)
    assert (f1["source"], f1["function"], f1["file"]) == ("ra", "setup()", "src/main.cpp")
    assert f1["line"] in (CALL_SAMPLE, CALL_SAMPLE + 1)  # return address: the call is on CALL_SAMPLE
    scan = [f for f in res["frames"] if f["source"] == "stack_scan"]
    assert [f["function"] for f in scan] == ["loopTask(void*)"]
    codes = [w["code"] for w in env["warnings"]]
    assert "stack_scan_heuristic" in codes and "ra_return_address" in codes
    assert [i["code"] for i in res["interpretation"]] == ["access_fault", "null_pointer"]
    assert {i["source_id"] for i in res["interpretation"]} == {"idf-v6.1-fatal-errors-esp32c3"}
    assert res["elf_match"] is True
    assert env["summary"] == (f"Store access fault on core 0 in write_sensor_buffer (src/main.cpp:{WRITE}): write "
                              "through a NULL pointer at offset 12 bytes.")

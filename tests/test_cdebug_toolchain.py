"""Crash decoding with the real toolchain (marker toolchain, CB_TOOLCHAIN_TESTS=1): decode S2 / C6 / ESP32 panics.

The ELFs are built elsewhere (e.g. the offline seed builds of tests/cflash_fixtures.py) and never copied into the repo; their paths
come from ``CB_CDEBUG_ELF_<CHIP>`` (e.g. ``CB_CDEBUG_ELF_ESP32S2=/…/firmware.elf``). Panic logs are synthesized from
the real addresses of ``setup()`` and ``loop()`` (``<prefix>-nm``) and decoded with the real addr2line, found the way
crash.decode finds it: through the build's ``cc_path`` and through the PlatformIO packages (6.9.0 per-chip
``toolchain-xtensa-<chip>``, 8.0.0 unified ``toolchain-xtensa-esp-elf``, kept ``toolchain-…@<version>``).
Missing ELF or toolchain -> skip with the reason.
"""
from __future__ import annotations

import os
import pwd
import re
from pathlib import Path

import pytest

from circuit_bench.bench_core import chips, clitools, crash
from test_crash_decode import FAKES_BIN

pytestmark = pytest.mark.toolchain

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PIO_CORE = Path(os.environ.get("CB_PIO_CORE_DIR") or REAL_HOME / ".platformio")
FE = crash.FE_SOURCE_PREFIX


def _elf(chip: str) -> Path:
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1":
        pytest.skip("set CB_TOOLCHAIN_TESTS=1 (run: CB_TOOLCHAIN_TESTS=1 pytest -m toolchain)")
    var = f"CB_CDEBUG_ELF_{chip.upper()}"
    path = os.environ.get(var)
    if not path:
        pytest.skip(f"{var} not set (path of a firmware.elf built for {chips.title(chip)})")
    if not Path(path).is_file():
        pytest.skip(f"{var}: {path} not found")
    return Path(path)


def _tools(prefix: str, name: str) -> list[Path]:
    packages = PIO_CORE / "packages"
    return sorted(p for p in packages.glob(f"toolchain-*/bin/{prefix}-{name}") if p.is_file())


@pytest.fixture
def real_path(monkeypatch):
    """PATH without the fakes; PlatformIO packages from the real core dir."""
    keep = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p).resolve() != FAKES_BIN]
    monkeypatch.setenv("PATH", os.pathsep.join(keep))
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(PIO_CORE))


def _symbols(chip: str, elf: Path) -> dict[str, int]:
    nm = _tools(chips.toolchain_prefix(chip), "nm")
    if not nm:
        pytest.skip(f"no {chips.toolchain_prefix(chip)}-nm under {PIO_CORE}/packages")
    res = clitools.run([str(nm[0]), "-C", str(elf)], timeout=60, tail=200_000)
    assert res["rc"] == 0, res["out_tail"][-5:]
    out: dict[str, int] = {}
    for line in res["out_tail"]:
        m = re.match(r"^([0-9a-f]+) [Tt] (setup|loop)\(\)$", line.strip())
        if m:
            out[m[2]] = int(m[1], 16)
    if set(out) != {"setup", "loop"}:
        pytest.skip(f"{elf}: setup()/loop() not found (an Arduino sketch is expected)")
    return out


def _xtensa_log(sym: dict[str, int]) -> str:
    pc, ret = sym["setup"] + 6, sym["loop"] + 6
    return ("Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.\n\n"
            "Core  0 register dump:\n"
            f"PC      : 0x{pc:08x}  PS      : 0x00060130  A0      : 0x{0x80000000 | (ret & 0x3fffffff):08x}  "
            "A1      : 0x3ffc5e40\n"
            "A2      : 0x00000000  A3      : 0x00000000  A4      : 0x00000000  A5      : 0x00000000\n"
            "SAR     : 0x00000004  EXCCAUSE: 0x0000001c\n"
            "EXCVADDR: 0x00000008  LBEG    : 0x00000000  LEND    : 0x00000000  LCOUNT  : 0x00000000\n\n\n"
            f"Backtrace: 0x{pc:08x}:0x3ffc5e40 0x{ret:08x}:0x3ffc5e60\n\n\nRebooting...\n")


def _riscv_log(sym: dict[str, int]) -> str:
    mepc, ra = sym["setup"] + 4, sym["loop"] + 4
    return ("Guru Meditation Error: Core  0 panic'ed (Store access fault). Exception was unhandled.\n\n"
            "Core  0 register dump:\n"
            f"MEPC    : 0x{mepc:08x}  RA      : 0x{ra:08x}  SP      : 0x4080f2d0  GP      : 0x4080a6f4\n"
            "MSTATUS : 0x00001881  MTVEC   : 0x40800001  MCAUSE  : 0x00000007  MTVAL   : 0x00000010\n"
            "MHARTID : 0x00000000\n\n\nRebooting...\n")


def _check(env: dict, chip: str) -> None:
    assert env["ok"] is True, env.get("error")
    res = env["result"]
    assert res["arch"] == chips.arch(chip)
    assert [f["function"] for f in res["frames"]][:2] == ["setup()", "loop()"], res["frames"]
    assert all(f["file"] and f["file"].endswith("main.cpp") and isinstance(f["line"], int) for f in res["frames"][:2])
    for f, name in zip(res["frames"][:2], ("setup", "loop"), strict=True):  # the line is the function's line
        src = Path(f["file"]).expanduser()
        if src.is_file():
            assert f"void {name}()" in src.read_text(encoding="utf-8").splitlines()[f["line"] - 1]
    assert {i["source_id"] for i in res["interpretation"]} == {crash.fe_pages()[chip]}
    assert "chip_mismatch" not in [w["code"] for w in env["warnings"]]
    assert {"id": "crash.addr2line", "status": "passed", "detail": "2 of 2 frames resolved"} in env["checks"]


@pytest.mark.parametrize("chip", ["esp32s2", "esp32c6", "esp32"])
def test_real_decode_by_package_lookup(chip, real_path):
    elf = _elf(chip)
    tool = crash.find_addr2line(chip)
    if tool is None:
        pytest.skip(f"no {chips.toolchain_prefix(chip)}-addr2line under {PIO_CORE}/packages")
    assert Path(tool).name == f"{chips.toolchain_prefix(chip)}-addr2line"  # no unified fallback needed
    log = _xtensa_log(_symbols(chip, elf)) if chips.arch(chip) == "xtensa" else _riscv_log(_symbols(chip, elf))
    _check(crash.decode(log, elf=str(elf), chip=chip), chip)


@pytest.mark.parametrize("chip", ["esp32s2", "esp32c6"])
def test_real_decode_with_each_installed_toolchain(chip, real_path):
    """Every installed package with the chip's prefix (6.9.0 and 8.0.0 schemes) decodes through cc_path."""
    elf = _elf(chip)
    prefix = chips.toolchain_prefix(chip)
    gccs = _tools(prefix, "gcc")
    if not gccs:
        pytest.skip(f"no {prefix}-gcc under {PIO_CORE}/packages")
    sym = _symbols(chip, elf)
    log = _xtensa_log(sym) if chips.arch(chip) == "xtensa" else _riscv_log(sym)
    for gcc in gccs:
        assert crash.find_addr2line(chip, str(gcc)) == str(gcc.with_name(f"{prefix}-addr2line"))
        env = crash.decode(log, elf=str(elf), chip=chip, cc_path=str(gcc))
        _check(env, chip)


def test_real_wrong_chip_is_a_warning(real_path):
    elf = _elf("esp32c6")
    env = crash.decode(_riscv_log(_symbols("esp32c6", elf)), elf=str(elf), chip="esp32s2")
    assert env["ok"] is True
    assert "chip_mismatch" in [w["code"] for w in env["warnings"]]

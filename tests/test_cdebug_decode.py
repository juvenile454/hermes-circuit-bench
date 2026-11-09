"""crash.decode for ESP32-S2 (Xtensa) and ESP32-C6 (RISC-V) through the chip register.

Synthetic panics after the patterns of the Fatal Errors examples (register dump, ``Backtrace:`` PC:SP pairs on Xtensa,
MEPC/RA on RISC-V), decoded with the fake addr2line of the chip's prefix (tests/fakes/bin). A wrong chip in the project
gives a ``chip_mismatch`` warning, never a silent result.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from circuit_bench.bench_core import chips, crash
from test_crash_decode import FAKES_BIN, assert_sourced, calls, fake_elf, sha_line

FE = crash.FE_SOURCE_PREFIX

# ESP32-S2, single core: LoadProhibited through a NULL struct pointer (EXCVADDR 0x8), backtrace of three frames.
S2_LOG = """\
Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.

Core  0 register dump:
PC      : 0x40081a2b  PS      : 0x00060130  A0      : 0x80081c4d  A1      : 0x3ffc5e40
A2      : 0x00000000  A3      : 0x3ffc5e7c  A4      : 0x00000001  A5      : 0x3ffc2b10
A6      : 0x00000000  A7      : 0x00000001  A8      : 0x00000000  A9      : 0x3ffc5e20
A10     : 0x00000000  A11     : 0x3ffc5e7c  A12     : 0x00000000  A13     : 0x3ffc2b0c
A14     : 0x00000000  A15     : 0x00000000  SAR     : 0x00000004  EXCCAUSE: 0x0000001c
EXCVADDR: 0x00000008  LBEG    : 0x00000000  LEND    : 0x00000000  LCOUNT  : 0x00000000


Backtrace: 0x40081a2b:0x3ffc5e40 0x40081c4a:0x3ffc5e60 0x40085f1e:0x3ffc5e80




ELF file SHA256: {sha}

Rebooting...
"""
S2_ADDRS = {
    "0x40081a2b": "read_sensor(sensor_t const*) at {project}/src/main.cpp:14",
    "0x40081c4a": "loop() at {project}/src/main.cpp:31",
    "0x40085f1e": "loopTask(void*) at {home}/.platformio/packages/framework-arduinoespressif32/cores/esp32/main.cpp:74",
}
# ESP32-C6: Store access fault through a NULL struct pointer (MTVAL 0x10), MEPC/RA without a backtrace.
C6_LOG = """\
Guru Meditation Error: Core  0 panic'ed (Store access fault). Exception was unhandled.

Core  0 register dump:
MEPC    : 0x42000a3c  RA      : 0x42000a5e  SP      : 0x4080f2d0  GP      : 0x4080a6f4
TP      : 0x4080a2ac  T0      : 0x4001a17e  T1      : 0x0000000f  T2      : 0x00000000
S0/FP   : 0x00000000  S1      : 0x00000000  A0      : 0x00000000  A1      : 0x00000001
A2      : 0x00000064  A3      : 0x00000004  A4      : 0x00000001  A5      : 0x00000000
A6      : 0x00000000  A7      : 0x00000000  S2      : 0x00000000  S3      : 0x00000000
S4      : 0x00000000  S5      : 0x00000000  S6      : 0x00000000  S7      : 0x00000000
S8      : 0x00000000  S9      : 0x00000000  S10     : 0x00000000  S11     : 0x00000000
T3      : 0x00000000  T4      : 0x00000000  T5      : 0x00000000  T6      : 0x00000000
MSTATUS : 0x00001881  MTVEC   : 0x40800001  MCAUSE  : 0x00000007  MTVAL   : 0x00000010
MHARTID : 0x00000000



ELF file SHA256: {sha}

Rebooting...
"""
C6_ADDRS = {
    "0x42000a3c": "store_sample(frame_t*) at {project}/src/main.cpp:9",
    "0x42000a5e": "loop() at {project}/src/main.cpp:22",
}


@pytest.fixture
def project(tmp_path) -> Path:
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    return p


def _addrs(table: dict[str, str], project: Path) -> dict[str, str]:
    return {k: v.replace("{project}", str(project)).replace("{home}", os.environ["HOME"]) for k, v in table.items()}


def s2_case(project: Path, sub: str = "s2", arch: str = "xtensa"):
    elf, argv_log = fake_elf(project / ".pio" / "build" / sub, arch=arch, addresses=_addrs(S2_ADDRS, project))
    return elf, argv_log, S2_LOG.replace("{sha}", sha_line(elf))


def c6_case(project: Path, sub: str = "c6", arch: str = "riscv"):
    elf, argv_log = fake_elf(project / ".pio" / "build" / sub, arch=arch, addresses=_addrs(C6_ADDRS, project))
    return elf, argv_log, C6_LOG.replace("{sha}", sha_line(elf))


def codes(env: dict) -> list[str]:
    return [w["code"] for w in env["warnings"]]


def mismatch(env: dict) -> str:
    (w,) = [w for w in env["warnings"] if w["code"] == "chip_mismatch"]
    assert w["severity"] == "caution"
    return w["message"]


def tool_dir(root: Path, package: str, *names: str, target: str = "xtensa-esp32s3-elf-addr2line") -> Path:
    """packages/<package>/bin/<name> as symlinks to the fake addr2line (the audit hook resolves them to tests/fakes)."""
    bin_dir = root / "packages" / package / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        (bin_dir / n).symlink_to(FAKES_BIN / target)
    return bin_dir


# --- register ---------------------------------------------------------------------------------------------------
def test_public_names_are_derived_from_the_register():
    assert crash.CHIPS == {c: chips.arch(c) for c in chips.ids()}
    assert crash.TOOLCHAIN_PREFIX == {c: chips.toolchain_prefix(c) for c in chips.ids()}
    assert crash._ARCH_PREFIXES == {"xtensa": chips.xtensa_prefixes(), "riscv": chips.riscv_prefixes()}
    assert {"esp32s2", "esp32c6"} <= set(crash.CHIPS)
    assert crash.normalize_chip("ESP32-S2") == "esp32s2"
    assert crash.normalize_chip("esp32_c6") == "esp32c6"
    with pytest.raises(crash.BenchError) as e:
        crash.normalize_chip("esp32h2")
    assert e.value.code == "unknown_chip" and chips.ids_text() in e.value.hint


def test_fatal_errors_page_per_chip():
    pages = crash.fe_pages()
    assert set(pages) == set(chips.ids())
    assert pages["esp32s2"] == f"{FE}-esp32s2" and pages["esp32c6"] == f"{FE}-esp32c6"
    assert pages["esp32s3"] == FE  # the unsuffixed page is the ESP32-S3 page (as before)
    for chip, sid in pages.items():
        assert crash._fe_source(chips.arch(chip), chip) == sid
        assert crash._fe_source(None, chip) == sid
    # RISC-V is no longer C3 automatically: only without a chip the first RISC-V page of the register is cited
    assert crash._fe_source("riscv", "esp32c6") == f"{FE}-esp32c6"
    assert crash._fe_source("riscv", None) == f"{FE}-esp32c3"
    # crash output of the other architecture: the page that has those sections
    assert crash._fe_source("riscv", "esp32s2") == f"{FE}-esp32c3"
    assert crash._fe_source("xtensa", "esp32c6") == FE
    # a section the chip's page does not have (.. only:: SOC_MEMPROT_SUPPORTED)
    assert crash._fe_source("riscv", "esp32c6", "SOC_MEMPROT_SUPPORTED") == f"{FE}-esp32c3"
    assert crash._fe_source("xtensa", "esp32", "SOC_MEMPROT_SUPPORTED") == FE
    assert crash._fe_source("xtensa", "esp32s2", "SOC_MEMPROT_SUPPORTED") == f"{FE}-esp32s2"


def test_cc_prefix_names_a_chip_only_when_unique():
    assert crash._chip_for_prefix("xtensa-esp32s2-elf") == "esp32s2"
    assert crash._chip_for_prefix("riscv32-esp-elf") is None  # C3 and C6 share it
    assert crash._chip_for_prefix(crash.UNIFIED_XTENSA_PREFIX) is None


# --- S2 / C6 decode with the fake addr2line of the right prefix ---------------------------------------------------
def test_s2_load_prohibited_backtrace(project):
    elf, argv_log, text = s2_case(project)
    env = crash.decode(text, elf=elf, chip="esp32s2", project_dir=project)
    assert env["ok"] is True, env
    assert_sourced(env)
    res = env["result"]
    assert (res["kind"], res["reason"], res["arch"], res["core"]) == ("cpu_exception", "LoadProhibited", "xtensa", 0)
    assert res["registers"]["EXCVADDR"] == "0x00000008"
    assert [(f["source"], f["function"], f["file"], f["line"]) for f in res["frames"]] == [
        ("backtrace", "read_sensor(sensor_t const*)", "src/main.cpp", 14),
        ("backtrace", "loop()", "src/main.cpp", 31),
        ("backtrace", "loopTask(void*)", "~/.platformio/packages/framework-arduinoespressif32/cores/esp32/main.cpp", 74)]
    assert [i["code"] for i in res["interpretation"]] == ["load_prohibited", "null_pointer"]
    assert {i["source_id"] for i in res["interpretation"]} == {f"{FE}-esp32s2"}
    assert res["elf_match"] is True
    assert env["summary"] == ("LoadProhibited on core 0 in read_sensor (src/main.cpp:14): read through a NULL pointer "
                              "at offset 8 bytes.")
    (call,) = calls(argv_log)
    assert call[0] == "xtensa-esp32s2-elf-addr2line"
    assert call[1:4] == ["-pfiaC", "-e", str(elf)] and call[4:] == ["0x40081a2b", "0x40081c4a", "0x40085f1e"]
    assert "chip_mismatch" not in codes(env)
    assert not [a for a in env["assumptions"] if a["key"] in ("toolchain", "chip")]


def test_c6_store_access_fault_mepc_ra(project):
    elf, argv_log, text = c6_case(project)
    env = crash.decode(text, elf=elf, chip="ESP32-C6", project_dir=project)
    assert env["ok"] is True, env
    assert_sourced(env)
    res = env["result"]
    assert (res["kind"], res["reason"], res["arch"]) == ("cpu_exception", "Store access fault", "riscv")
    assert [(f["source"], f["function"], f["line"]) for f in res["frames"]] == [
        ("mepc", "store_sample(frame_t*)", 9), ("ra", "loop()", 22)]
    assert [i["code"] for i in res["interpretation"]] == ["access_fault", "null_pointer"]
    assert res["interpretation"][1]["text"] == "MTVAL 0x00000010: write through a NULL pointer at offset 16 bytes."
    assert {i["source_id"] for i in res["interpretation"]} == {f"{FE}-esp32c6"}
    assert f"{FE}-esp32c3" not in [s["id"] for s in env["sources"]]
    assert res["elf_match"] is True
    assert "ra_return_address" in codes(env) and "chip_mismatch" not in codes(env)
    (call,) = calls(argv_log)
    assert call[0] == "riscv32-esp-elf-addr2line" and call[4:] == ["0x42000a3c", "0x42000a5e"]


def test_c6_through_the_project_tool_path(project):
    """cc_path riscv32-esp-elf-gcc (shared by C3 and C6) does not turn a C6 project into a C3."""
    elf, argv_log, text = c6_case(project)
    tc = tool_dir(project / "pio", "toolchain-riscv32-esp", "riscv32-esp-elf-addr2line")
    (tc / "riscv32-esp-elf-gcc").write_text("#!/bin/sh\n")
    env = crash.decode(text, elf=elf, chip="esp32c6", cc_path=str(tc / "riscv32-esp-elf-gcc"), project_dir=project)
    assert {i["source_id"] for i in env["result"]["interpretation"]} == {f"{FE}-esp32c6"}
    assert "chip_mismatch" not in codes(env)
    assert calls(argv_log)[0][0] == "riscv32-esp-elf-addr2line"
    # without a chip the shared prefix names no chip: the RISC-V text of the register's first RISC-V page
    env = crash.decode(text, elf=elf, cc_path=str(tc / "riscv32-esp-elf-gcc"), project_dir=project)
    assert {i["source_id"] for i in env["result"]["interpretation"]} == {f"{FE}-esp32c3"}
    assert env["result"]["frames"][0]["function"] == "store_sample(frame_t*)"


# --- wrong chip in the project: a warning, not a silent result ----------------------------------------------------
def test_wrong_chip_by_architecture(project):
    elf, _, text = s2_case(project)
    env = crash.decode(text, elf=elf, chip="esp32c6", project_dir=project)
    assert env["ok"] is True
    assert mismatch(env) == "The crash output is from a xtensa chip, but esp32c6 is riscv: check the chip setting."
    assert {i["source_id"] for i in env["result"]["interpretation"]} == {FE}  # an Xtensa page, not the C6 page
    elf, _, text = c6_case(project)
    env = crash.decode(text, elf=elf, chip="esp32s2", project_dir=project)
    assert mismatch(env).startswith("The crash output is from a riscv chip, but esp32s2 is xtensa")
    assert {i["source_id"] for i in env["result"]["interpretation"]} == {f"{FE}-esp32c3"}
    assert_sourced(env)


def test_wrong_chip_by_compiler_prefix(project):
    elf, argv_log, text = s2_case(project)
    tc = tool_dir(project / "pio", "toolchain-xtensa-esp32s2", "xtensa-esp32s2-elf-addr2line")
    (tc / "xtensa-esp32s2-elf-gcc").write_text("#!/bin/sh\n")
    env = crash.decode(text, elf=elf, chip="esp32s3", cc_path=str(tc / "xtensa-esp32s2-elf-gcc"), project_dir=project)
    msg = mismatch(env)
    assert "built with xtensa-esp32s2-elf-gcc (toolchain of ESP32-S2), but esp32s3 uses xtensa-esp32s3-elf" in msg
    w = [w for w in env["warnings"] if w["code"] == "chip_mismatch"][0]
    assert set(w["source_ids"]) == {"idf-v6.1-toolchain-esp32s2", "idf-v6.1-toolchain-esp32s3"}
    assert calls(argv_log)[0][0] == "xtensa-esp32s2-elf-addr2line"  # the build's own toolchain decodes
    assert_sourced(env)


def test_wrong_chip_by_elf_header(project):
    elf, _, _ = c6_case(project)  # RISC-V ELF
    brownout = "Brownout detector was triggered\n\nets Jul 29 2019 12:21:46\n"
    env = crash.decode(brownout, elf=elf, chip="esp32s2", project_dir=project)
    assert mismatch(env) == "The ELF is built for riscv, but esp32s2 is xtensa: check the chip setting."
    assert [i["source_id"] for i in env["result"]["interpretation"]] == [f"{FE}-esp32s2"]
    assert_sourced(env)


def test_wrong_chip_by_reset_reason():
    log = "rst:0x10 (LP_WDT_SYS),boot:0xc (SPI_FAST_FLASH_BOOT)\n"
    env = crash.decode(log, chip="esp32c3")
    assert env["ok"] is True
    assert mismatch(env) == ("The reset reason LP_WDT_SYS (0x10) is the RTC watchdog reset name of ESP32-C6; "
                             "ESP32-C3 prints RTCWDT_RTC_RST: check the chip setting.")
    w = [w for w in env["warnings"] if w["code"] == "chip_mismatch"][0]
    assert w["source_ids"] == [f"{FE}-esp32c3", f"{FE}-esp32c6"]
    assert_sourced(env)
    env = crash.decode("rst:0x10 (RTCWDT_RTC_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)\n", chip="esp32s2")
    assert "RTCWDT_RTC_RESET (0x10) is the RTC watchdog reset name of ESP32; ESP32-S2 prints RTCWDT_RTC_RST" in mismatch(env)


# --- reset reasons per chip (Fatal Errors substitution IDF_TARGET_RTCWDT_RTC_RESET) -----------------------------
@pytest.mark.parametrize(("chip", "name"), [("esp32c6", "LP_WDT_SYS"), ("esp32s2", "RTCWDT_RTC_RST"),
                                           ("esp32", "RTCWDT_RTC_RESET")])
def test_rtc_watchdog_reset_per_chip(chip, name):
    env = crash.decode(f"rst:0x10 ({name}),boot:0xc (SPI_FAST_FLASH_BOOT)\n", chip=chip)
    assert env["ok"] is True
    assert [i["code"] for i in env["result"]["interpretation"]] == ["rtc_wdt_reset"]
    assert env["result"]["interpretation"][0]["source_id"] == crash.fe_pages()[chip]
    assert env["summary"].endswith(f"reset reason {name} (0x10): RTC watchdog reset.")
    assert "chip_mismatch" not in codes(env)


def test_reset_name_names_the_chip_only_when_unique():
    env = crash.decode("rst:0x10 (LP_WDT_SYS),boot:0xc (SPI_FAST_FLASH_BOOT)\n")
    assert [(a["key"], a["value"]) for a in env["assumptions"]] == [("chip", "esp32c6")]
    assert env["result"]["interpretation"][0]["source_id"] == f"{FE}-esp32c6"
    assert_sourced(env)
    # RTCWDT_RTC_RST: ESP32-S2, -S3 and -C3 -> no chip, the default page as before
    env = crash.decode("rst:0x10 (RTCWDT_RTC_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)\n")
    assert env["assumptions"] == []
    assert env["result"]["interpretation"][0]["source_id"] == FE
    # ... unless the crash output narrows it to one architecture (RISC-V: ESP32-C3 only)
    _, _, text = c6_case(Path(os.environ["HOME"]) / "p")
    env = crash.decode(text + "rst:0x10 (RTCWDT_RTC_RST),boot:0xc (SPI_FAST_FLASH_BOOT)\n")
    assert ("chip", "esp32c3") in [(a["key"], a["value"]) for a in env["assumptions"]]


# --- toolchain lookup: 6.9.0 per-chip packages, 8.0.0 unified packages, kept @versions -------------------------
def test_find_addr2line_fakes_on_path():
    assert crash.find_addr2line("esp32s2") == str(FAKES_BIN / "xtensa-esp32s2-elf-addr2line")
    assert crash.find_addr2line("esp32c6") == str(FAKES_BIN / "riscv32-esp-elf-addr2line")


def test_find_addr2line_package_schemes(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    old = tmp_path / "core-6.9.0"
    s2_old = tool_dir(old, "toolchain-xtensa-esp32s2", "xtensa-esp32s2-elf-addr2line")
    rv_old = tool_dir(old, "toolchain-riscv32-esp", "riscv32-esp-elf-addr2line")
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(old))
    assert crash.find_addr2line("esp32s2") == str(s2_old / "xtensa-esp32s2-elf-addr2line")
    assert crash.find_addr2line("esp32c6") == str(rv_old / "riscv32-esp-elf-addr2line")
    assert crash.find_addr2line("esp32s3") is None

    new = tmp_path / "core-8.0.0"  # 8.0.0 installed, 6.9.0 kept: what installing both versions leaves in ~/.platformio
    x_new = tool_dir(new, "toolchain-xtensa-esp-elf", "xtensa-esp32-elf-addr2line", "xtensa-esp32s2-elf-addr2line",
                     "xtensa-esp32s3-elf-addr2line", "xtensa-esp-elf-addr2line")
    tool_dir(new, "toolchain-xtensa-esp32s2", "xtensa-esp32s2-elf-addr2line")
    rv_kept = tool_dir(new, "toolchain-riscv32-esp@8.4.0+2021r2-patch5", "riscv32-esp-elf-addr2line")
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(new))
    for chip in ("esp32", "esp32s2", "esp32s3"):
        assert crash.find_addr2line(chip) == str(x_new / f"{chips.toolchain_prefix(chip)}-addr2line")
    assert crash.find_addr2line("esp32c6") == str(rv_kept / "riscv32-esp-elf-addr2line")  # only the kept version
    rv_new = tool_dir(new, "toolchain-riscv32-esp", "riscv32-esp-elf-addr2line")
    assert crash.find_addr2line("esp32c6") == str(rv_new / "riscv32-esp-elf-addr2line")  # active before @version
    assert crash.find_addr2line("esp32c3") == str(rv_new / "riscv32-esp-elf-addr2line")


def test_unified_xtensa_addr2line_is_a_fallback_and_an_assumption(project, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable))  # python3 for the fake's shebang, no addr2line
    core = tmp_path / "core-unified"
    tc = tool_dir(core, "toolchain-xtensa-esp-elf", "xtensa-esp-elf-addr2line")
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(core))
    assert crash.find_addr2line("esp32s2") == str(tc / "xtensa-esp-elf-addr2line")
    assert crash.find_addr2line("esp32") == str(tc / "xtensa-esp-elf-addr2line")
    assert crash.find_addr2line("esp32c6") is None  # RISC-V never takes the Xtensa tool
    elf, argv_log, text = s2_case(project)
    env = crash.decode(text, elf=elf, chip="esp32s2", project_dir=project)
    assert env["checks"][1] == {"id": "crash.addr2line", "status": "passed", "detail": "3 of 3 frames resolved"}
    (a,) = [a for a in env["assumptions"] if a["key"] == "toolchain"]
    assert a["value"] == "xtensa-esp-elf-addr2line" and "no xtensa-esp32s2-elf-addr2line found" in a["reason"]
    assert calls(argv_log)[0][0] == "xtensa-esp-elf-addr2line"
    assert "pio-esp32-8.0.0-platform-json" in [s["id"] for s in env["sources"]]
    # without a chip the arch search also ends with the unified tool
    env = crash.decode(text, elf=elf, project_dir=project)
    assert [a["value"] for a in env["assumptions"] if a["key"] == "toolchain"] == ["xtensa-esp-elf-addr2line"]
    # a C6 crash with only the Xtensa toolchain: tool_missing, no Xtensa addr2line on a RISC-V ELF
    elf6, _, text6 = c6_case(project)
    env = crash.decode(text6, elf=elf6, chip="esp32c6", project_dir=project)
    assert "tool_missing" in codes(env)


# --- sections a chip's page does not have ------------------------------------------------------------------------
def test_c6_page_has_no_memory_protection_section():
    log = ("Guru Meditation Error: Core  0 panic'ed (Memory protection fault). Exception was unhandled.\n\n"
           "Core  0 register dump:\nMEPC    : 0x42000a3c  RA      : 0x42000a5e  SP      : 0x4080f2d0  GP      : 0x4080a6f4\n"
           "MSTATUS : 0x00001881  MTVEC   : 0x40800001  MCAUSE  : 0x00000001  MTVAL   : 0x42000a3c\n")
    env = crash.decode(log, chip="esp32c6")
    (interp,) = [i for i in env["result"]["interpretation"] if i["code"] == "memory_protection_fault"]
    assert interp["source_id"] == f"{FE}-esp32c3"
    (w,) = [w for w in env["warnings"] if w["code"] == "doc_section_other_chip"]
    assert w["severity"] == "info" and "ESP32-C6" in w["message"] and "ESP32-C3" in w["message"]
    assert w["source_ids"] == [f"{FE}-esp32c6", f"{FE}-esp32c3", "idf-v6.1-soccaps-esp32c6"]
    assert_sourced(env)
    env = crash.decode(log, chip="esp32c3")
    assert "doc_section_other_chip" not in codes(env)
    assert {i["source_id"] for i in env["result"]["interpretation"]} == {f"{FE}-esp32c3"}


def test_no_chip_id_literals_in_the_decoder():
    """The chip list comes from the register: no quoted chip id in crash.py."""
    import re
    src = (Path(crash.__file__)).read_text(encoding="utf-8")
    quoted = set(re.findall(r"[\"']([a-z0-9]+)[\"']", src))
    assert quoted & set(chips.ids()) == set()

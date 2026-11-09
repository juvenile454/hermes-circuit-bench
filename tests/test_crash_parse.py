"""Crash parser: every panic format from the ESP-IDF v6.1 docs (synthetic logs in tests/fixtures/crash/)."""
from __future__ import annotations

from pathlib import Path

import pytest

from circuit_bench.bench_core import crash
from circuit_bench.bench_core.contracts import BenchError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crash"


def log(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "kind", "reason", "core", "arch", "frames", "end"), [
    ("xtensa_store_prohibited.log", "cpu_exception", "StoreProhibited", 1, "xtensa", 3, None),
    ("xtensa_load_prohibited_corrupted.log", "cpu_exception", "LoadProhibited", 0, "xtensa", 2, "corrupted"),
    ("xtensa_instr_fetch_prohibited.log", "cpu_exception", "InstrFetchProhibited", 0, "xtensa", 3, None),
    ("xtensa_abort.log", "abort", "abort() was called", 0, None, 8, None),
    ("xtensa_assert.log", "assert", "assert failed", None, None, 6, None),
    ("heap_corrupt.log", "heap", "CORRUPT HEAP", 0, None, 4, None),
    ("stack_smashing.log", "abort", "Stack smashing protect failure", 0, None, 12, None),
    ("brownout.log", "brownout", "Brownout detector was triggered", None, None, 0, None),
    ("brownout_partial.log", "brownout", "Brownout detector was triggered", None, None, 0, None),
    ("task_wdt.log", "task_wdt", "Task watchdog got triggered", None, None, 4, None),
    ("int_wdt.log", "int_wdt", "Interrupt wdt timeout on CPU1", 1, "xtensa", 3, None),
    ("stack_canary.log", "stack_overflow", "Stack canary watchpoint triggered", 0, "xtensa", 3, "continues"),
    ("stack_overflow_hook.log", "stack_overflow", "Stack overflow", None, None, 6, "corrupted"),
    ("esp_error_check.log", "assert", "ESP_ERROR_CHECK failed: ESP_ERR_TIMEOUT", None, None, 4, None),
    ("ubsan.log", "abort", "Undefined behavior: out_of_bounds", None, None, 6, None),
    ("riscv_store_access_fault.log", "cpu_exception", "Store access fault", 0, "riscv", 0, None),
    ("riscv_eh_frame.log", "cpu_exception", "Load access fault", 0, "riscv", 6, None),
    ("riscv_breakpoint.log", "cpu_exception", "Breakpoint", 0, "riscv", 0, None),
    ("riscv_stack_protection.log", "stack_overflow", "Stack protection fault", 0, "riscv", 0, None),
    ("riscv_abort.log", "abort", "abort() was called", 0, "riscv", 0, None),
])
def test_parse_doc_formats(name, kind, reason, core, arch, frames, end):
    p = crash.parse(log(name))
    assert p["found"] is True
    assert (p["kind"], p["reason"], p["core"], p["arch"]) == (kind, reason, core, arch)
    assert len(p["backtrace"]) == frames
    assert p["backtrace_end"] == end
    assert p["kind"] in crash.KINDS


def test_xtensa_register_dump_and_backtrace_pairs():
    p = crash.parse(log("xtensa_store_prohibited.log"))
    regs = p["registers"]
    assert regs["PC"] == "0x42001d6a"
    assert regs["EXCCAUSE"] == "0x0000001d"
    assert regs["EXCVADDR"] == "0x0000000c"
    assert regs["A0"] == "0x82001d8d"
    assert len(regs) == 24
    assert p["backtrace"][0] == {"pc": "0x42001d67", "sp": "0x3fcebf40"}
    assert [b["pc"] for b in p["backtrace"]] == ["0x42001d67", "0x42001d8a", "0x42003a5e"]
    assert p["header"].startswith("Guru Meditation Error: Core  1 panic'ed (StoreProhibited)")
    assert p["rebooting"] is True


def test_corrupted_marker_and_pairs_before_it():
    p = crash.parse(log("xtensa_load_prohibited_corrupted.log"))
    assert [b["pc"] for b in p["backtrace"]] == ["0x400e14ea", "0x400d0802"]
    assert p["backtrace_end"] == "corrupted"


def test_riscv_register_dump_and_stack_memory():
    p = crash.parse(log("riscv_store_access_fault.log"))
    regs = p["registers"]
    assert (regs["MEPC"], regs["RA"], regs["MCAUSE"], regs["MTVAL"]) == ("0x42006686", "0x42006692", "0x00000007",
                                                                         "0x00000000")
    assert regs["S0/FP"] == "0x00000000"
    assert regs["MHARTID"] == "0x00000000"
    assert len(p["stack_words"]) == 24
    assert p["stack_words"][3] == "0x42006692"


def test_riscv_stack_memory_of_the_idf_monitor_example():
    p = crash.parse(log("riscv_abort.log"))
    assert p["abort"] == {"pc": "0x42067cd5", "core": 0}
    assert len(p["stack_words"]) == 16  # '.....' ends the dump
    assert p["registers"]["MHARTID"] == "0x00000000"  # after a blank line, still the same dump


def test_reset_reason_line_rtcwdt():
    p = crash.parse(log("rtc_wdt_reset.log"))
    assert p["found"] is True
    assert p["kind"] == "unknown"
    assert p["reset_reason"] == {"code": "0x10", "name": "RTCWDT_RTC_RST", "when": "no_crash"}


def test_reset_reason_after_crash_wins_over_boot_before():
    p = crash.parse(log("xtensa_store_prohibited.log"))
    assert p["reset_reason"] == {"code": "0xc", "name": "RTC_SW_CPU_RST", "when": "after_crash"}
    p = crash.parse(log("riscv_store_access_fault.log"))
    assert p["reset_reason"] == {"code": "0x1", "name": "POWERON", "when": "before_crash"}


def test_abort_assert_and_esp_error_check_details():
    assert crash.parse(log("xtensa_abort.log"))["abort"] == {"pc": "0x40007c69", "core": 0}
    a = crash.parse(log("xtensa_assert.log"))["assert"]
    assert a == {"func": "read_sensor", "file": "main.c", "line": 42, "expr": "len <= sizeof(buf)", "style": "idf"}
    heap = crash.parse(log("heap_corrupt.log"))
    assert heap["heap"] == "Bad tail at 0x3ffe270a. Expected 0xbaad5678 got 0xbaac5678"
    assert heap["assert"]["style"] == "newlib"
    assert heap["assert"]["func"] == "multi_heap_free"
    assert heap["assert"]["line"] == 201
    e = crash.parse(log("esp_error_check.log"))["esp_error_check"]
    assert e == {"code": "0x107", "name": "ESP_ERR_TIMEOUT", "pc": "0x400d1fdf", "file": "/Users/user/esp/example/main/main.c",
                 "line": 20, "func": "app_main", "expr": "sdmmc_card_init(host, &card)"}


def test_assert_without_function_name():
    p = crash.parse("assert failed: \b main.c:7 (x)\n\nBacktrace: 0x40375b4a:0x3fc98a20\n")
    assert p["assert"]["func"] is None
    assert p["assert"]["line"] == 7


def test_watchdog_and_stack_overflow_details():
    t = crash.parse(log("task_wdt.log"))["task_wdt"]
    assert t == {"tasks": [{"name": "IDLE0", "cpu": "CPU 0"}], "running": [{"cpu": 0, "task": "main"},
                                                                           {"cpu": 1, "task": "IDLE1"}]}
    doc_line = ("Task watchdog got triggered. The following tasks/users did not reset the watchdog in time: - IDLE0 (CPU 0), "
                "Tasks currently running: CPU 0: main, CPU 1: IDLE1")
    t2 = crash.parse(doc_line)["task_wdt"]
    assert t2 == t
    canary = crash.parse(log("stack_canary.log"))
    assert canary["stack_overflow_task"] == "sensor_task"
    assert canary["debug_reason"] == "Stack canary watchpoint triggered (sensor_task)"
    assert crash.parse(log("stack_overflow_hook.log"))["stack_overflow_task"] == "sensor_task"
    assert crash.parse(log("ubsan.log"))["ubsan"] == "out_of_bounds"


def test_int_wdt_takes_the_first_register_dump():
    p = crash.parse(log("int_wdt.log"))
    assert p["registers"]["PC"] == "0x4037a6b2"
    assert p["backtrace"][0]["pc"] == "0x4037a6af"
    assert len(p["backtrace"]) == 3


def test_elf_sha256_lines_unverified_format():
    p = crash.parse(log("xtensa_store_prohibited.log"))
    assert (p["elf_sha256"], p["elf_sha256_line"]) == ("3f9a5c0d2", "panic")
    p = crash.parse(log("riscv_store_access_fault.log"))  # boot line and panic line: the panic line wins
    assert (p["elf_sha256"], p["elf_sha256_line"]) == ("7c1d0e9a4", "panic")
    boot_only = log("riscv_store_access_fault.log").replace("ELF file SHA256: 7c1d0e9a4\n", "")
    p = crash.parse(boot_only)
    assert (p["elf_sha256"], p["elf_sha256_line"]) == ("7c1d0e9a4b2f8a31", "boot")


def test_ansi_colours_and_monitor_timestamps_are_ignored():
    plain = crash.parse(log("xtensa_store_prohibited.log"))
    stamped = crash.parse(log("arduino_timestamps.log"))
    for key in ("kind", "reason", "core", "registers", "backtrace", "elf_sha256", "reset_reason"):
        assert stamped[key] == plain[key], key
    assert "\x1b[" in log("task_wdt.log")


def test_two_crashes_decode_the_first():
    p = crash.parse(log("two_crashes.log"))
    assert p["blocks"] == 2
    assert p["reason"] == "LoadProhibited"
    assert p["reset_reason"]["name"] == "RTC_SW_CPU_RST"


def test_header_lost_reason_from_cause_register():
    p = crash.parse(log("riscv_header_lost.log"))
    assert (p["kind"], p["reason"], p["reason_inferred"], p["arch"]) == ("cpu_exception", "Load access fault", True, "riscv")
    x = crash.parse("EXCVADDR: 0x00000000  LBEG    : 0x400570e8\nPC      : 0x42001d6a  EXCCAUSE: 0x0000001c\n")
    assert (x["reason"], x["reason_inferred"], x["arch"]) == ("LoadProhibited", True, "xtensa")


def test_no_crash_and_bad_input():
    p = crash.parse(log("no_crash.log"))
    assert p["found"] is False
    assert p["kind"] == "unknown"
    assert crash.parse(b"Brownout detector was triggered\n")["kind"] == "brownout"
    with pytest.raises(BenchError) as e:
        crash.parse(123)  # type: ignore[arg-type]
    assert e.value.code == "invalid_args"
    with pytest.raises(BenchError):
        crash.parse("x" * (crash.MAX_LOG_CHARS + 1))


def test_cause_tables_follow_the_panic_handler():
    assert crash.XTENSA_EXCCAUSE[0x1c] == "LoadProhibited"
    assert crash.XTENSA_EXCCAUSE[0x1d] == "StoreProhibited"
    assert crash.XTENSA_EXCCAUSE[0x14] == "InstrFetchProhibited"
    assert crash.XTENSA_EXCCAUSE[6] == "IntegerDivideByZero"
    assert crash.RISCV_MCAUSE[5] == "Load access fault"
    assert crash.RISCV_MCAUSE[7] == "Store access fault"
    assert crash.RISCV_MCAUSE[3] == "Breakpoint"


def test_parse_addr2line_output_with_inline_chain():
    out = [
        "0x400f360d: do_something_to_crash at /p/main/./hello_world_main.c:57",
        " (inlined by) inner_dont_crash at /p/main/./hello_world_main.c:52",
        "0x400dbf56: still_dont_crash at /p/main/./hello_world_main.c:47",
        "0x40007c69: ets_write_char in ROM",
        "0x00000000: ?? ??:0",
        "0x400db99c: app_main at main.c:56 (discriminator 1)",
    ]
    groups = crash.parse_addr2line(out)
    assert [g[0] for g in groups] == [0x400f360d, 0x400dbf56, 0x40007C69, 0, 0x400DB99C]
    assert [c["function"] for c in groups[0][1]] == ["do_something_to_crash", "inner_dont_crash"]
    assert groups[0][1][1]["line"] == 52
    assert groups[2][1][0] == {"function": "ets_write_char", "file": None, "line": None}
    assert groups[3][1][0] == {"function": None, "file": None, "line": None}
    assert groups[4][1][0] == {"function": "app_main", "file": "main.c", "line": 56}


def test_normalize_chip():
    assert crash.normalize_chip("ESP32-S3") == "esp32s3"
    assert crash.normalize_chip("esp32_c3") == "esp32c3"
    assert crash.normalize_chip(None) is None
    with pytest.raises(BenchError) as e:
        crash.normalize_chip("esp8266")
    assert e.value.code == "unknown_chip"

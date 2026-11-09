"""Crash decoder summary edges: a pasted backtrace without its panic header, and the elf_missing hint."""
from __future__ import annotations

from pathlib import Path

from circuit_bench.bench_core import crash

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crash"
BACKTRACE = "Backtrace: 0x42001d67:0x3fc9e2a0 0x42001d8a:0x3fc9e2c0 0x42003a5e:0x3fc9e2e0\n"
RESET = "rst:0x10 (RTCWDT_RTC_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)\n"


def test_backtrace_line_alone_gets_its_own_summary():
    env = crash.decode(BACKTRACE, chip="esp32s3")
    assert env["ok"] is True
    assert len(env["result"]["frames"]) == 3
    assert env["summary"].startswith("Backtrace without a crash header: 3 frames decoded")
    assert env["summary"] == ("Backtrace without a crash header: 3 frames decoded; paste the log from the "
                              "'Guru Meditation Error' (or 'abort()') line for the cause.")


def test_backtrace_without_header_keeps_the_reset_reason():
    env = crash.decode(RESET + BACKTRACE, chip="esp32s3")
    assert env["summary"] == ("Backtrace without a crash header: 3 frames decoded; paste the log from the "
                              "'Guru Meditation Error' (or 'abort()') line for the cause; reset reason "
                              "RTCWDT_RTC_RST (0x10): RTC watchdog reset.")


def test_single_frame_backtrace_reads_naturally():
    env = crash.decode("Backtrace: 0x42001d67:0x3fc9e2a0\n", chip="esp32s3")
    assert env["summary"].startswith("Backtrace without a crash header: 1 frame decoded;")


def test_reset_without_frames_is_unchanged():
    text = (FIXTURES / "rtc_wdt_reset.log").read_text(encoding="utf-8")
    env = crash.decode(text)
    assert env["summary"] == "No crash report in the log; reset reason RTCWDT_RTC_RST (0x10): RTC watchdog reset."


def test_elf_missing_names_project_and_elf(tmp_path):
    env = crash.decode((FIXTURES / "xtensa_store_prohibited.log").read_text(encoding="utf-8"), chip="esp32s3")
    (w,) = [w for w in env["warnings"] if w["code"] == "elf_missing"]
    assert w["message"] == ("No ELF file given: frames show addresses only. Pass project (its last build gives the "
                            "ELF), or elf with the firmware.elf of the build that crashed.")
    env = crash.decode((FIXTURES / "xtensa_store_prohibited.log").read_text(encoding="utf-8"),
                       elf=tmp_path / "nope.elf")
    (w,) = [w for w in env["warnings"] if w["code"] == "elf_missing"]
    assert w["message"].startswith("ELF file not found: nope.elf: frames show addresses only. Pass project")

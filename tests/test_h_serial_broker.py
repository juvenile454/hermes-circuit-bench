"""The broker finds every crash kind of the decoder; repeats of one signature in a
read phase share the first block's artifact and carry ``repeat``."""
from __future__ import annotations

import types
from pathlib import Path

import board_fixtures as bf
import pytest
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, crash, serialport

ROOT = Path(__file__).resolve().parent.parent
CRASH_DIR = ROOT / "tests" / "fixtures" / "crash"
REAL_DIR = ROOT / "tests" / "fixtures" / "real"
PORT = "sim://test-s3"
SLOW_S = 15.0  # ceiling for event waits under parallel test processes (wait_for returns as soon as it holds)
# appended to every replayed log: the ROM banner closes an open block, the marker line proves that every panic message
# of the log was published (the reader publishes a block's panic before it emits the next line)
SENTINEL = ["ESP-ROM:esp32s3-20210327", "cb-test: end of log"]

# Fixtures without a block in the broker (reason in the value); for every other fixture the broker opens a block
# exactly at the lines crash.is_event_line matches.
NO_BLOCK = {
    "no_crash": "a normal boot: no crash line at all",
    "rtc_wdt_reset": "only the reset reason of the next boot (rst:0x10 RTCWDT_RTC_RST), no crash output",
    "riscv_header_lost": "the header line was lost: only a register dump, which the decoder still reads as a trace "
                         "but which is no event that starts a block",
}


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _replay(lines: list[str]) -> list[dict]:
    """Play ``lines`` through a provider port and return every message up to the end of the log."""
    board.register_provider("sim://", bf.TestProvider(lines=[*lines, *SENTINEL]))
    msgs: list[dict] = []
    serialport.subscribe(PORT, msgs.append)
    serialport.open_port(PORT)
    assert bf.wait_for(lambda: any(m.get("text") == SENTINEL[-1] for m in msgs), timeout=SLOW_S)
    return msgs


def _panics(msgs: list[dict]) -> list[dict]:
    return [m for m in msgs if m["t"] == "panic"]


def _panic_files() -> list[str]:
    return sorted(p.name for p in serialport.artifacts_dir().iterdir() if p.name.startswith("panic-"))


def _event(text: str) -> bool:
    return crash.is_event_line(crash.clean_line(text))


# ------------------------------------------------------------------------------------------------ A7a

def test_public_aliases_are_the_decoder_functions():
    assert crash.is_event_line is crash._is_event and crash.clean_line is crash._clean


@pytest.mark.parametrize("path", sorted(CRASH_DIR.glob("*.log")), ids=lambda p: p.stem)
def test_broker_opens_a_block_exactly_at_decoder_events(path):
    lines = _lines(path)
    msgs = _replay(lines)
    panics = _panics(msgs)
    events = [i + 1 for i, text in enumerate(lines) if _event(text)]  # seq of each event line (seq starts at 1)
    if path.stem in NO_BLOCK:
        assert panics == [] and events == [], NO_BLOCK[path.stem]
        if path.stem == "riscv_header_lost":
            assert crash.parse("\n".join(lines))["found"] is True  # the decoder reads it, the stream cannot announce it
        return
    assert panics, f"{path.stem}: no block although the decoder sees events at {events}"
    ranges = []
    for pnc in panics:
        assert pnc["log_ref"] and "repeat" not in pnc, pnc  # the fixtures hold no repeated crash
        start = pnc["seq"]
        assert _event(lines[start - 1]), f"{path.stem}: block starts at a non-event line {lines[start - 1]!r}"
        n = len(serialport.artifact_path(pnc["log_ref"]).read_text(encoding="utf-8").splitlines())
        ranges.append((start, start + n - 1))
    for seq in events:  # every event line opens a block or belongs to the block of an earlier event
        assert any(a <= seq <= b for a, b in ranges), f"{path.stem}: event line {seq} {lines[seq - 1]!r} outside a block"


@pytest.mark.parametrize(("stem", "summary"), [
    ("esp_error_check", "ESP_ERROR_CHECK failed (ESP_ERR_TIMEOUT)"),
    ("xtensa_assert", "assert failed in read_sensor (main.c:42)"),
    ("stack_overflow_hook", "stack overflow in task sensor_task"),
    ("ubsan", "UBSan: out_of_bounds"),
    ("heap_corrupt", "CORRUPT HEAP: Bad tail at 0x3ffe270a"),
    ("stack_smashing", "Stack smashing protect failure"),
    ("stack_canary", "Stack canary watchpoint (sensor_task) · core 0"),
    ("brownout_partial", "Brownout detector triggered"),
    ("task_wdt", "Task watchdog triggered"),
    ("xtensa_store_prohibited", "StoreProhibited · core 1"),
])
def test_one_panic_with_a_telling_summary(stem, summary):
    (pnc,) = _panics(_replay(_lines(CRASH_DIR / f"{stem}.log")))
    assert pnc["summary"] == summary


@pytest.mark.parametrize(("line", "summary"), [
    ('assertion "head != NULL" failed: file "/x/heap/multi_heap_poisoning.c", line 201, function: multi_heap_free',
     "assert failed in multi_heap_free (multi_heap_poisoning.c:201)"),
    ('assertion "n > 0" failed: file "main.c", line 7', "assert failed (main.c:7)"),
    ("ESP_ERROR_CHECK failed: esp_err_t 0x103", "ESP_ERROR_CHECK failed (0x103)"),
    ("E (1234) task_wdt: Task watchdog got triggered. The following tasks did not reset the watchdog in time:",
     "Task watchdog triggered"),  # older IDF without "tasks/users": only PANIC_START knows it
    ("abort() was called at PC 0x400dca43 on core 0", "abort() · core 0"),
])
def test_summary_of_single_lines(line, summary):
    assert serialport.panic_summary(line) == summary


# ------------------------------------------------------------------------------------------------ A7b

def test_real_reboot_loop_gives_two_messages_and_one_artifact():
    lines = _lines(REAL_DIR / "esp32s3-reboot-loop.log")
    panics = _panics(_replay(lines))
    assert len(panics) == 2 and len(_panic_files()) == 1
    first, second = panics
    assert "repeat" not in first and second["repeat"] == 2
    assert second["log_ref"] == first["log_ref"] == _panic_files()[0]
    assert second["seq"] > first["seq"] and second["summary"] == first["summary"] == "StoreProhibited · core 1"
    stored = serialport.artifact_path(first["log_ref"]).read_text(encoding="utf-8").splitlines()
    assert stored[0].startswith("Guru Meditation Error") and stored[-1] == "Rebooting..."
    # the polling fallback names the newest panic with the first block's log_ref
    last = serialport.tail(PORT)["panic"]
    assert last["seq"] == second["seq"] and last["log_ref"] == first["log_ref"]


def test_third_repeat_counts_on():
    block = _lines(CRASH_DIR / "xtensa_store_prohibited.log")
    panics = _panics(_replay([*block, "rst:0xc (RTC_SW_CPU_RST),boot:0x8"] * 3))
    assert [p.get("repeat") for p in panics] == [None, 2, 3] and len(_panic_files()) == 1
    assert len({p["log_ref"] for p in panics}) == 1


def test_other_backtrace_gives_a_new_artifact():
    block = _lines(CRASH_DIR / "xtensa_store_prohibited.log")
    i = next(i for i, t in enumerate(block) if t.startswith("Backtrace:"))
    other = [*block[:i], "Backtrace: 0x42001111:0x3fcebf40 0x42002222:0x3fcebf60", *block[i + 1:]]
    panics = _panics(_replay([*block, *other]))
    assert len(panics) == 2 and not any("repeat" in p for p in panics)
    assert panics[0]["log_ref"] != panics[1]["log_ref"] and len(_panic_files()) == 2


def test_other_header_gives_a_new_artifact():
    block = _lines(CRASH_DIR / "xtensa_store_prohibited.log")
    other = [t.replace("Core  1 panic'ed", "Core  0 panic'ed") for t in block]
    assert other != block
    panics = _panics(_replay([*block, *other]))
    assert len(panics) == 2 and not any("repeat" in p for p in panics) and len(_panic_files()) == 2


def test_signature_ignores_registers_time_stamps_and_log_times():
    """Header plus first Backtrace line, cleaned: register values, Arduino time stamps and IDF log times differ between
    two boots of one reboot loop (fixtures/real), the crash is the same."""
    a = ["12:00:00.001 -> Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled.",
         "A2      : 0x00000001  A3      : 0x00000019", "Backtrace: 0x420019e1:0x3fcebc50 0x42001a01:0x3fcebc70"]
    b = ["12:00:09.512 -> Guru Meditation Error: Core  1 panic'ed (StoreProhibited). Exception was unhandled.",
         "A2      : 0x00000002  A3      : 0x00000018", "\x1b[0;31mBacktrace: 0x420019e1:0x3fcebc50 0x42001a01:0x3fcebc70"]
    assert serialport.panic_signature(a) == serialport.panic_signature(b)
    wdt = ["E (10325) task_wdt: Task watchdog got triggered. The following tasks/users did not reset the watchdog in time:",
           "E (10325) task_wdt:  - IDLE0 (CPU 0)", "", "E (10325) task_wdt: Tasks currently running:",
           "E (10325) task_wdt: CPU 0: main", "E (10325) task_wdt: CPU 1: IDLE1"]
    later = [t.replace("10325", "15325") for t in wdt]
    assert serialport.panic_signature(wdt) == serialport.panic_signature(later)  # no backtrace: the next 3 lines
    assert serialport.panic_signature(wdt) != serialport.panic_signature([*wdt[:4], "E (10325) task_wdt: CPU 0: other"])


def test_same_panic_after_pause_gives_a_new_artifact():
    """A flash (or detect) pauses the port: the board runs new firmware, the Desktop compares the time stamp of log_ref
    with last_flash.at, so the next panic must get its own artifact."""
    msgs = _replay(_lines(CRASH_DIR / "xtensa_store_prohibited.log"))
    assert len(_panics(msgs)) == 1
    msgs.clear()
    with serialport.pause(PORT):
        pass
    assert bf.wait_for(lambda: any(m.get("text") == SENTINEL[-1] for m in msgs), timeout=SLOW_S)
    (again,) = _panics(msgs)
    assert "repeat" not in again and len(_panic_files()) == 2


def test_same_panic_after_close_and_open_gives_a_new_artifact():
    msgs = _replay(_lines(CRASH_DIR / "xtensa_store_prohibited.log"))
    first = _panics(msgs)[0]
    serialport.close_port(PORT)
    msgs.clear()
    serialport.open_port(PORT)
    assert bf.wait_for(lambda: any(m.get("text") == SENTINEL[-1] for m in msgs), timeout=SLOW_S)
    (again,) = _panics(msgs)
    assert "repeat" not in again and again["log_ref"] != first["log_ref"] and len(_panic_files()) == 2


def test_reconnect_resets_the_signature():
    """A RESET re-enumerates a native USB port (seen in the hardware test): the reconnect starts a new read phase."""
    b = serialport.broker()
    p = b._get("sim://test-reconnect")
    p.want_open = False
    with p.data:
        p.panic_sig = ("sig",)
        p.panic_sig_ref, p.panic_sig_count = "panic-20261107-120000.log", 2
    handle = types.SimpleNamespace(close=lambda: None)
    assert b._reconnect(p, serialport._Run(), handle) is None
    assert p.panic_sig is None and p.panic_sig_ref is None and p.panic_sig_count == 0


def test_reboot_loop_over_a_pty(hw_on, pty_port):
    """The real reader (pyserial on a pty) with the real reboot loop."""
    msgs: list[dict] = []
    serialport.subscribe(pty_port.name, msgs.append)
    serialport.open_port(pty_port.name, 115200)
    pty_port.write(*_lines(REAL_DIR / "esp32s3-reboot-loop.log"), *SENTINEL)
    assert bf.wait_for(lambda: any(m.get("text") == SENTINEL[-1] for m in msgs), timeout=SLOW_S)
    panics = _panics(msgs)
    assert [p.get("repeat") for p in panics] == [None, 2] and len(_panic_files()) == 1
    assert panics[1]["log_ref"] == panics[0]["log_ref"] == _panic_files()[0]
    # close() ends the read phase: the same crash after reopening is stored again
    serialport.close_port(pty_port.name)
    msgs.clear()
    serialport.open_port(pty_port.name, 115200)
    pty_port.write(*_lines(REAL_DIR / "esp32s3-reboot-loop.log")[:45], *SENTINEL)
    assert bf.wait_for(lambda: any(m.get("text") == SENTINEL[-1] for m in msgs), timeout=SLOW_S)
    assert [p.get("repeat") for p in _panics(msgs)] == [None] and len(_panic_files()) == 2


def test_monitor_lists_repeats_with_the_first_log_ref(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", '{"monitor_max_seconds": 1}')
    board.register_provider("sim://", bf.TestProvider(lines=_lines(REAL_DIR / "esp32s3-reboot-loop.log")))
    env = serialport.monitor(PORT, 1)
    r = env["result"]
    assert env["ok"] and len(r["panics"]) == 2 and r["panics"][1]["repeat"] == 2
    assert r["log_ref"] == r["panics"][0]["log_ref"] == r["panics"][1]["log_ref"]
    detected = [w for w in env["warnings"] if w["code"] == "panic_detected"]
    assert len(detected) == 1 and "2 times" in detected[0]["message"]

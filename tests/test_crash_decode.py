"""Crash decoder: fake addr2line (tests/fakes/bin), frames, inline chain, interpretation with sources, ELF checks."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from circuit_bench.bench_core import clitools, crash, sources
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES, validate_envelope

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "crash"
FAKES_BIN = ROOT / "tests" / "fakes" / "bin"
EM = {"xtensa": 94, "riscv": 243}  # ELF e_machine (source elf-gabi-e-machine)


def log(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fake_elf(dirpath: Path, arch: str = "xtensa", name: str = "firmware.elf", scenario: str | None = None,
             project: Path | None = None, **extra) -> tuple[Path, Path]:
    """A tiny ELF header file plus the fake addr2line side scenario (<elf>.a2l.json). Returns (elf, argv_log)."""
    dirpath.mkdir(parents=True, exist_ok=True)
    elf = dirpath / name
    head = bytearray(b"\x7fELF\x01\x01\x01" + bytes(9)) + (2).to_bytes(2, "little") + EM[arch].to_bytes(2, "little")
    elf.write_bytes(bytes(head) + b"synthetic test file, not firmware\n")
    argv_log = dirpath / "argv.jsonl"
    data: dict = {}
    if scenario:
        text = (FIXTURES / scenario).read_text(encoding="utf-8")
        text = text.replace("{project}", str(project or dirpath)).replace("{home}", os.environ["HOME"])
        data = json.loads(text)
    data.update(extra)
    data["argv_log"] = str(argv_log)
    Path(str(elf) + ".a2l.json").write_text(json.dumps(data), encoding="utf-8")
    return elf, argv_log


def calls(argv_log: Path) -> list[list[str]]:
    if not argv_log.exists():
        return []
    return [json.loads(x) for x in argv_log.read_text(encoding="utf-8").splitlines()]


def sha_line(elf: Path, n: int = 9) -> str:
    return hashlib.sha256(elf.read_bytes()).hexdigest()[:n]


def assert_sourced(env: dict) -> None:
    """Every interpretation and warning cites known sources, and the envelope lists them all."""
    assert validate_envelope(env) == []
    listed = {s["id"] for s in env["sources"]}
    for item in env["result"].get("interpretation", []):
        assert item["source_id"], item
        sources.get(item["source_id"])
        assert item["source_id"] in listed
    for w in env["warnings"]:
        for sid in w["source_ids"]:
            assert sid in listed
    assert len(json.dumps(env, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES


@pytest.fixture
def project(tmp_path) -> Path:
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    return p


def store_prohibited(tmp_path, project):
    elf, argv_log = fake_elf(project / ".pio" / "build" / "s3", scenario="xtensa_store_prohibited.a2l.json", project=project)
    text = log("xtensa_store_prohibited.log").replace("ELF file SHA256: 3f9a5c0d2", f"ELF file SHA256: {sha_line(elf)}")
    return elf, argv_log, text


def test_xtensa_decode_matches_the_desktop_fixture(tmp_path, project):
    elf, argv_log, text = store_prohibited(tmp_path, project)
    env = crash.decode(text, elf=str(elf), chip="esp32s3", project_dir=str(project))
    assert env["ok"] is True, env
    assert_sourced(env)
    fixture = json.loads((ROOT / "desktop-src" / "fixtures" / "crash.decode.json").read_text(encoding="utf-8"))
    assert env.keys() == fixture.keys()
    assert env["result"].keys() == fixture["result"].keys()
    # the fixture is the real simulated chain (scripts/gen_demo_fixtures.py, main.cpp:44); this synthetic log
    # resolves to main.cpp:5 through the fake addr2line: compare the structure, not the values
    assert "write_sensor_buffer" in env["summary"] and "src/main.cpp:5" in env["summary"]
    res = env["result"]
    assert (res["kind"], res["reason"], res["core"], res["arch"]) == ("cpu_exception", "StoreProhibited", 1, "xtensa")
    assert res["registers"]["EXCVADDR"] == "0x0000000c"
    assert len(res["frames"]) >= 2
    for got in res["frames"]:
        assert got.keys() == fixture["result"]["frames"][0].keys()
    assert [i["code"] for i in res["interpretation"]] == ["store_prohibited", "null_pointer"]
    assert res["interpretation"][1]["text"] == fixture["result"]["interpretation"][1]["text"]
    assert {i["source_id"] for i in res["interpretation"]} == {"idf-v6.1-fatal-errors"}
    assert res["elf_match"] is True
    assert res["reset_reason"] == {"code": "0xc", "name": "RTC_SW_CPU_RST", "when": "after_crash"}
    assert [c["id"] for c in env["checks"]] == ["crash.parse", "crash.addr2line", "crash.elf_match"]
    assert [c["status"] for c in env["checks"]] == ["passed", "passed", "passed"]
    assert env["checks"][1]["detail"] == "3 of 3 frames resolved"
    assert [a["key"] for a in env["assumptions"]] == ["near_zero_limit", "elf_sha256_line"]
    assert "unverified" in env["assumptions"][1]["reason"]
    assert env["simulated"] is False
    (call,) = calls(argv_log)
    assert call == ["xtensa-esp32s3-elf-addr2line", "-pfiaC", "-e", str(elf), "0x42001d67", "0x42001d8a", "0x42003a5e"]


def test_paths_relative_to_project_dir_else_absolute_or_home(tmp_path, project):
    elf, _, text = store_prohibited(tmp_path, project)
    env = crash.decode(text, elf=elf, chip="esp32s3")
    files = [f["file"] for f in env["result"]["frames"]]
    assert files[0] == str(project / "src" / "main.cpp")  # project under HOME? no: tmp_path/proj is outside HOME
    assert files[2] == "~/.platformio/packages/framework-arduinoespressif32/cores/esp32/main.cpp"
    env = crash.decode(text, elf=elf, chip="esp32s3", project_dir=project)
    assert env["result"]["frames"][0]["file"] == "src/main.cpp"


def test_inline_chain_from_addr2line(tmp_path, project):
    elf, _ = fake_elf(tmp_path / "b", scenario="xtensa_assert.a2l.json", project=project)
    env = crash.decode(log("xtensa_assert.log"), elf=elf, chip="esp32s3", project_dir=project)
    assert env["ok"] is True
    assert_sourced(env)
    frames = env["result"]["frames"]
    assert [f["i"] for f in frames] == list(range(len(frames)))
    inl = [f for f in frames if f["pc"] == "0x42008d3f"]
    assert [(f["function"], f["line"], f["inlined"]) for f in inl] == [("copy_frame", 41, True), ("read_sensor", 42, False)]
    assert all(f["source"] == "backtrace" for f in frames)
    assert len(frames) == 7  # 6 PCs, one with an inlined caller
    assert env["result"]["kind"] == "assert"
    assert env["summary"] == "assert failed in read_sensor (main.c:42): len <= sizeof(buf)."
    assert [i["code"] for i in env["result"]["interpretation"]] == ["assert_failed"]
    assert env["result"]["interpretation"][0]["source_id"] == "idf-v6.1-src-assert"


def test_without_elf_only_parse_with_elf_missing(tmp_path):
    env = crash.decode(log("xtensa_store_prohibited.log"), chip="esp32s3")
    assert env["ok"] is True
    assert_sourced(env)
    assert [w["code"] for w in env["warnings"]] == ["elf_missing"]
    frames = env["result"]["frames"]
    assert [f["pc"] for f in frames] == ["0x42001d67", "0x42001d8a", "0x42003a5e"]
    assert all(f["function"] is None and f["file"] is None and f["line"] is None for f in frames)
    assert env["checks"][1] == {"id": "crash.addr2line", "status": "skipped", "detail": "no ELF file"}
    assert env["result"]["elf_match"] is None
    assert env["summary"] == "StoreProhibited on core 1 at 0x42001d67: write through a NULL pointer at offset 12 bytes."
    missing = crash.decode(log("xtensa_store_prohibited.log"), elf=tmp_path / "nope.elf")
    assert missing["warnings"][0]["code"] == "elf_missing"
    assert "nope.elf" in missing["warnings"][0]["message"]


def test_elf_mismatch_and_zero_hash(tmp_path, project):
    elf, _, text = store_prohibited(tmp_path, project)
    bad = text.replace(f"ELF file SHA256: {sha_line(elf)}", "ELF file SHA256: 000000001")
    env = crash.decode(bad, elf=elf, chip="esp32s3", project_dir=project)
    assert env["result"]["elf_match"] is False
    w = [w for w in env["warnings"] if w["code"] == "elf_mismatch"]
    assert w and w[0]["severity"] == "caution"
    assert env["checks"][2]["status"] == "failed"
    assert_sourced(env)
    elf2, _ = fake_elf(tmp_path / "abort", scenario="xtensa_abort.a2l.json", project=project)
    env = crash.decode(log("xtensa_abort.log"), elf=elf2, chip="esp32s3", project_dir=project)
    assert env["result"]["elf_match"] is None
    assert "elf_sha256_zero" in [w["code"] for w in env["warnings"]]
    no_line = crash.decode(text.replace(f"ELF file SHA256: {sha_line(elf)}\n", ""), elf=elf, chip="esp32s3")
    assert no_line["result"]["elf_sha256_log"] is None
    assert no_line["checks"][2]["status"] == "skipped"


def test_riscv_mepc_ra_and_heuristic_stack_scan(tmp_path, project):
    elf, argv_log = fake_elf(tmp_path / "c3", arch="riscv", scenario="riscv_store_access_fault.a2l.json", project=project)
    text = log("riscv_store_access_fault.log").replace("ELF file SHA256: 7c1d0e9a4", f"ELF file SHA256: {sha_line(elf)}")
    env = crash.decode(text, elf=elf, chip="esp32c3", project_dir=project)
    assert env["ok"] is True
    assert_sourced(env)
    res = env["result"]
    assert (res["kind"], res["reason"], res["arch"]) == ("cpu_exception", "Store access fault", "riscv")
    frames = res["frames"]
    assert [(f["source"], f["function"], f["line"]) for f in frames] == [
        ("mepc", "bar", 18), ("ra", "foo", 22), ("stack_scan", "app_main", 28), ("stack_scan", "main_task", 142),
        ("stack_scan", "vPortTaskWrapper", 130)]
    assert frames[0]["file"] == "main/hello_world_main.c"
    codes = [w["code"] for w in env["warnings"]]
    assert "stack_scan_heuristic" in codes and "ra_return_address" in codes
    assert [i["code"] for i in res["interpretation"]] == ["access_fault", "null_pointer"]
    assert res["interpretation"][1]["text"] == "MTVAL 0x00000000: write through a NULL pointer."
    assert {i["source_id"] for i in res["interpretation"]} == {"idf-v6.1-fatal-errors-esp32c3"}
    assert res["elf_match"] is True
    assert env["summary"] == "Store access fault on core 0 in bar (main/hello_world_main.c:18): write through a NULL pointer."
    (call,) = calls(argv_log)
    assert call[0] == "riscv32-esp-elf-addr2line"
    assert call[4:6] == ["0x42006686", "0x42006692"]
    assert "0x40057fa6" in call  # code-looking word from the stack dump, unresolved -> not shown
    assert all(f["pc"] != "0x40057fa6" for f in frames)


def test_riscv_backtrace_when_present(tmp_path):
    elf, _ = fake_elf(tmp_path / "eh", arch="riscv", scenario="riscv_eh_frame.a2l.json")
    env = crash.decode(log("riscv_eh_frame.log"), elf=elf)
    res = env["result"]
    assert res["arch"] == "riscv"
    assert [f["source"] for f in res["frames"]] == ["backtrace"] * 6
    assert res["frames"][-1]["function"] is None  # 0xfffffffe: '?? ??:0'
    assert [i["code"] for i in res["interpretation"]] == ["access_fault", "null_pointer"]
    assert "offset 16 bytes" in res["interpretation"][1]["text"]
    assert any(a["key"] == "toolchain" for a in env["assumptions"]) or env["checks"][1]["status"] == "passed"
    assert_sourced(env)


def test_riscv_abort_resolves_the_abort_pc(tmp_path, project):
    elf, argv_log = fake_elf(tmp_path / "ra", arch="riscv", scenario="riscv_abort.a2l.json", project=project)
    env = crash.decode(log("riscv_abort.log"), elf=elf, chip="esp32c3", project_dir=project)
    res = env["result"]
    assert res["kind"] == "abort"
    interp = {i["code"]: i for i in res["interpretation"]}
    assert "(in app_main, main/hello_world_main.c:42)" in interp["abort"]["text"]
    assert env["summary"].startswith("abort() was called on core 0 in app_main (main/hello_world_main.c:42)")
    (call,) = calls(argv_log)
    assert call[-1] == "0x42067cd5"
    assert_sourced(env)


@pytest.mark.parametrize(("name", "codes"), [
    ("xtensa_load_prohibited_corrupted.log", ["load_prohibited", "null_pointer"]),
    ("xtensa_instr_fetch_prohibited.log", ["instr_fetch_prohibited", "bad_function_pointer"]),
    ("xtensa_abort.log", ["abort"]),
    ("heap_corrupt.log", ["heap_corrupt", "assert_failed"]),
    ("stack_smashing.log", ["stack_smashing", "abort"]),
    ("brownout.log", ["brownout"]),
    ("brownout_partial.log", ["brownout"]),
    ("task_wdt.log", ["task_wdt", "task_wdt_nonfatal"]),
    ("int_wdt.log", ["int_wdt"]),
    ("stack_canary.log", ["stack_overflow"]),
    ("stack_overflow_hook.log", ["stack_overflow"]),
    ("esp_error_check.log", ["esp_error_check"]),
    ("ubsan.log", ["ubsan"]),
    ("riscv_breakpoint.log", ["breakpoint"]),
    ("riscv_stack_protection.log", ["stack_protection_fault"]),
    ("rtc_wdt_reset.log", ["rtc_wdt_reset"]),
])
def test_interpretations_have_sources(name, codes):
    env = crash.decode(log(name))
    assert env["ok"] is True, env
    assert [i["code"] for i in env["result"]["interpretation"]] == codes
    assert_sourced(env)


def test_summaries_per_kind(tmp_path, project):
    def summary(name, scenario=None, **kw):
        elf = fake_elf(tmp_path / name, scenario=scenario, project=project)[0] if scenario else None
        return crash.decode(log(name), elf=elf, project_dir=project, **kw)["summary"]

    assert summary("brownout.log") == "Brownout: the supply voltage dropped below a safe level and the chip was reset."
    assert summary("task_wdt.log", "task_wdt.a2l.json").startswith(
        "Task watchdog triggered: IDLE0 (CPU 0) did not reset the watchdog in time; backtrace in wait_for_sensor")
    assert summary("int_wdt.log") == "Interrupt wdt timeout on CPU1 at 0x4037a6af."
    assert summary("stack_canary.log") == "Stack canary watchpoint triggered in task sensor_task on core 0 at 0x40379e39."
    assert summary("stack_overflow_hook.log") == "Stack overflow in task sensor_task."  # frames are the panic path
    assert summary("esp_error_check.log") == ("ESP_ERROR_CHECK failed with ESP_ERR_TIMEOUT (0x107) in app_main "
                                              "(/Users/user/esp/example/main/main.c:20): sdmmc_card_init(host, &card).")
    assert summary("ubsan.log", "ubsan.a2l.json") == "Undefined behavior: out_of_bounds in test_ub (main.c:128)."
    assert summary("rtc_wdt_reset.log") == "No crash report in the log; reset reason RTCWDT_RTC_RST (0x10): RTC watchdog reset."
    assert summary("xtensa_load_prohibited_corrupted.log", "xtensa_load_prohibited_corrupted.a2l.json") == (
        "LoadProhibited on core 0 in app_main (/home/user/esp/example/main/main.cpp:36): read through a NULL pointer.")


def test_backtrace_markers_and_multiple_crashes():
    env = crash.decode(log("xtensa_load_prohibited_corrupted.log"))
    assert "backtrace_corrupted" in [w["code"] for w in env["warnings"]]
    env = crash.decode(log("stack_canary.log"))
    assert "backtrace_continues" in [w["code"] for w in env["warnings"]]
    env = crash.decode(log("two_crashes.log"))
    assert "multiple_crashes" in [w["code"] for w in env["warnings"]]
    assert env["result"]["reason"] == "LoadProhibited"
    env = crash.decode(log("riscv_stack_protection.log"))
    assert "no_backtrace" not in [w["code"] for w in env["warnings"]]  # MEPC/RA are frames
    env = crash.decode("Guru Meditation Error: Core  0 panic'ed (IntegerDivideByZero). Exception was unhandled.\n")
    assert "no_backtrace" in [w["code"] for w in env["warnings"]]
    assert_sourced(env)


@pytest.mark.parametrize(("excvaddr", "code"), [("0x00000000", "null_pointer"), ("0x00000ffc", "null_pointer"),
                                              ("0xdeadbeef", "bad_pointer"), ("0x00001000", "bad_pointer"),
                                              ("0x3fc94a60", None), ("0x6000f000", None)])
def test_excvaddr_only_as_documented(excvaddr, code):
    text = log("xtensa_store_prohibited.log").replace("EXCVADDR: 0x0000000c", f"EXCVADDR: {excvaddr}")
    env = crash.decode(text)
    codes = [i["code"] for i in env["result"]["interpretation"]]
    assert codes == ["store_prohibited"] + ([code] if code else [])
    assert_sourced(env)


def test_header_lost_is_an_assumption():
    env = crash.decode(log("riscv_header_lost.log"))
    assert env["result"]["reason"] == "Load access fault"
    assert env["assumptions"][0]["key"] == "reason"
    assert "MCAUSE 0x00000005" in env["assumptions"][0]["reason"]
    assert "null_pointer" in [i["code"] for i in env["result"]["interpretation"]]


def test_errors_are_envelopes():
    env = crash.decode(log("no_crash.log"))
    assert (env["ok"], env["error"]["code"]) == (False, "decode_failed")
    assert env["checks"][0]["status"] == "failed"
    assert validate_envelope(env) == []
    assert crash.decode("")["error"]["code"] == "invalid_args"
    assert crash.decode(None)["error"]["code"] == "invalid_args"  # type: ignore[arg-type]
    assert crash.decode(42)["error"]["code"] == "invalid_args"  # type: ignore[arg-type]
    assert crash.decode(log("brownout.log"), chip="esp8266")["error"]["code"] == "unknown_chip"


def test_chip_and_elf_arch_mismatch(tmp_path):
    env = crash.decode(log("riscv_store_access_fault.log"), chip="esp32s3")
    assert "chip_mismatch" in [w["code"] for w in env["warnings"]]
    elf, _ = fake_elf(tmp_path / "x", arch="xtensa")
    env = crash.decode(log("riscv_eh_frame.log"), elf=elf)
    assert "elf_arch_mismatch" in [w["code"] for w in env["warnings"]]
    assert_sourced(env)


def test_addr2line_failure_unresolved_and_timeout(tmp_path):
    elf, _ = fake_elf(tmp_path / "f", rc=1, stderr="xtensa-esp32s3-elf-addr2line: firmware.elf: file format not recognized\n")
    env = crash.decode(log("xtensa_store_prohibited.log"), elf=elf, chip="esp32s3")
    assert env["ok"] is True
    w = [w for w in env["warnings"] if w["code"] == "tool_failed"]
    assert w and "file format not recognized" in w[0]["message"]
    assert env["checks"][1]["status"] == "failed"
    assert all(f["function"] is None for f in env["result"]["frames"])

    elf2, _ = fake_elf(tmp_path / "u")  # no addresses known -> '?? ??:0' everywhere
    env = crash.decode(log("xtensa_store_prohibited.log"), elf=elf2, chip="esp32s3")
    assert "unresolved" in [w["code"] for w in env["warnings"]]
    assert env["checks"][1] == {"id": "crash.addr2line", "status": "failed", "detail": "0 of 3 frames resolved"}

    def slow(argv, *, timeout, tail):
        return {"rc": None, "out_tail": [], "timed_out": True, "duration_s": timeout}

    env = crash.decode(log("xtensa_store_prohibited.log"), elf=elf2, chip="esp32s3", run=slow)
    assert env["checks"][1]["status"] == "failed"
    assert "timed out" in env["warnings"][0]["message"]


def test_injected_runner_for_sim(tmp_path):
    seen = []

    def run(argv, *, timeout, tail):
        seen.append(list(argv))
        return {"rc": 0, "timed_out": False, "out_tail": [
            "0x42001d67: write_sensor_buffer(unsigned char*, int) at /sim/proj/src/main.cpp:5",
            "0x42001d8a: loop() at /sim/proj/src/main.cpp:21",
            "0x42003a5e: loopTask(void*) at /sim/core/main.cpp:74"]}

    env = crash.decode(log("xtensa_store_prohibited.log"), elf="/sim/proj/.pio/build/s3/firmware.elf", chip="esp32s3",
                       project_dir="/sim/proj", run=run)
    assert Path(seen[0][0]).name == "xtensa-esp32s3-elf-addr2line"
    assert seen[0][1:4] == ["-pfiaC", "-e", "/sim/proj/.pio/build/s3/firmware.elf"]
    assert env["result"]["frames"][0]["file"] == "src/main.cpp"
    assert env["result"]["elf_match"] is None  # the ELF does not exist: nothing to compare


def test_tool_missing(tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    elf, _ = fake_elf(tmp_path / "m")
    env = crash.decode(log("xtensa_store_prohibited.log"), elf=elf, chip="esp32s3")
    assert env["ok"] is True
    assert "tool_missing" in [w["code"] for w in env["warnings"]]
    assert env["checks"][1]["status"] == "skipped"


def test_explicit_addr2line_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable))  # python3 for the fake's shebang, no addr2line
    elf, argv_log = fake_elf(tmp_path / "e", scenario="xtensa_store_prohibited.a2l.json")
    tool = str(FAKES_BIN / "xtensa-esp32s3-elf-addr2line")
    env = crash.decode(log("xtensa_store_prohibited.log"), elf=elf, addr2line=tool)
    assert env["checks"][1]["status"] == "passed"
    assert calls(argv_log)[0][0] == "xtensa-esp32s3-elf-addr2line"


def test_find_addr2line_order(tmp_path, monkeypatch):
    # 1. next to cc_path
    tc = tmp_path / "tc" / "bin"
    tc.mkdir(parents=True)
    for n in ("xtensa-esp32s3-elf-gcc", "xtensa-esp32s3-elf-addr2line"):
        (tc / n).write_text("#!/bin/sh\n")
        (tc / n).chmod(0o755)
    assert crash.find_addr2line("esp32s3", str(tc / "xtensa-esp32s3-elf-gcc")) == str(tc / "xtensa-esp32s3-elf-addr2line")
    # cc_path decides the prefix even without a chip
    assert crash.find_addr2line(None, str(tc / "xtensa-esp32s3-elf-gcc")) == str(tc / "xtensa-esp32s3-elf-addr2line")
    # 2. PATH (the fakes come first in tests)
    assert crash.find_addr2line("esp32c3") == str(FAKES_BIN / "riscv32-esp-elf-addr2line")
    # 3. PlatformIO packages
    core = tmp_path / "pio-core"
    pkg = core / "packages" / "toolchain-riscv32-esp" / "bin"
    pkg.mkdir(parents=True)
    (pkg / "riscv32-esp-elf-addr2line").write_text("#!/bin/sh\n")
    (pkg / "riscv32-esp-elf-addr2line").chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(core))
    assert crash.find_addr2line("ESP32-C3") == str(pkg / "riscv32-esp-elf-addr2line")
    assert crash.find_addr2line("esp32s3") is None
    assert crash.find_addr2line(None) is None
    monkeypatch.delenv("PLATFORMIO_CORE_DIR")
    home_pkg = Path(os.environ["HOME"]) / ".platformio" / "packages" / "toolchain-xtensa-esp32" / "bin"
    home_pkg.mkdir(parents=True)
    (home_pkg / "xtensa-esp32-elf-addr2line").write_text("#!/bin/sh\n")
    (home_pkg / "xtensa-esp32-elf-addr2line").chmod(0o755)
    assert crash.find_addr2line("esp32") == str(home_pkg / "xtensa-esp32-elf-addr2line")


def test_result_stays_small_with_a_long_backtrace(tmp_path):
    pairs = " ".join(f"0x{0x42000000 + 4 * i:08x}:0x3fc9{i:04x}" for i in range(400))
    text = f"Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.\n\nBacktrace: {pairs}\n"
    addrs = {f"0x{0x42000000 + 4 * i:08x}": [f"inner_{i}(int, char const*) at /p/very/long/path/to/src/f{i}.cpp:{i + 1}",
                                             f"outer_{i}() at /p/very/long/path/to/src/f{i}.cpp:{i + 2}"] for i in range(400)}
    elf, _ = fake_elf(tmp_path / "big", addresses=addrs)
    env = crash.decode(text, elf=elf, chip="esp32s3")
    assert env["ok"] is True
    assert len(json.dumps(env, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES
    assert len(env["result"]["frames"]) <= crash.MAX_FRAMES
    codes = [w["code"] for w in env["warnings"]]
    assert "frames_truncated" in codes


def test_decode_never_imports_board():
    src = (ROOT / "circuit_bench" / "bench_core" / "crash.py").read_text(encoding="utf-8")
    assert "import board" not in src and "from .board" not in src and "from . import board" not in src
    assert crash.decode.__kwdefaults__["run"] is clitools.run

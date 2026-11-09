import gc
import json
import os
import signal
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

import pytest

from circuit_bench.bench_core import clitools
from circuit_bench.bench_core.contracts import BenchError

FAKE = str(Path(__file__).resolve().parent / "fakes" / "bin" / "cb-fake-tool")


def test_run_captures_tail_and_rc(tmp_path, monkeypatch):
    scen = tmp_path / "s.json"
    scen.write_text(json.dumps({"build": {"rc": 3, "stdout": "\n".join(f"l{i}" for i in range(10)) + "\n"}}))
    log = tmp_path / "argv.log"
    res = clitools.run([FAKE, "build", "-x"], timeout=10, tail=3,
                       env_extra={"CB_FAKE_SCENARIO": str(scen), "CB_FAKE_ARGV_LOG": str(log)})
    assert res["rc"] == 3 and res["out_tail"] == ["l7", "l8", "l9"] and res["timed_out"] is False
    assert json.loads(log.read_text()) == ["cb-fake-tool", "build", "-x"]


def test_run_minimal_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("ESPTOOL_BEFORE", "no-reset")
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", "/x/pio")
    env = clitools.minimal_env({"A": "1"})
    assert "OPENAI_API_KEY" not in env and "ESPTOOL_BEFORE" not in env
    assert env["PLATFORMIO_CORE_DIR"] == "/x/pio" and env["A"] == "1" and env["LANG"] == "C.UTF-8"


def test_pio_telemetry_off_by_default(monkeypatch, tmp_path):
    """PlatformIO calls get PLATFORMIO_SETTING_ENABLE_TELEMETRY=No unless the user set it."""
    monkeypatch.delenv(clitools.PIO_TELEMETRY, raising=False)
    assert clitools.minimal_env(pio=True)[clitools.PIO_TELEMETRY] == "No"
    assert clitools.PIO_TELEMETRY not in clitools.minimal_env()  # other tools: untouched
    monkeypatch.setenv(clitools.PIO_TELEMETRY, "Yes")  # the user's value wins
    assert clitools.minimal_env(pio=True)[clitools.PIO_TELEMETRY] == "Yes"
    assert clitools.minimal_env({clitools.PIO_TELEMETRY: "Yes"}, pio=True)[clitools.PIO_TELEMETRY] == "Yes"
    monkeypatch.delenv(clitools.PIO_TELEMETRY)
    seen = []
    real = clitools.minimal_env
    monkeypatch.setattr(clitools, "minimal_env", lambda extra=None, **kw: seen.append(kw) or real(extra, **kw))
    pio = str(Path(__file__).resolve().parent / "fakes" / "bin" / "pio")
    clitools.run([pio, "run", "-d", str(tmp_path), "-t", "buildprog"], timeout=10,
                 env_extra={"CB_FAKE_SCENARIO": ""})
    clitools.run([FAKE, "x"], timeout=10)
    assert seen == [{"pio": True}, {"pio": False}]


def test_run_timeout_kills_process_group(tmp_path):
    marker = tmp_path / "child.pid"
    code = (f"import os,subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
            f"open({str(marker)!r},'w').write(str(p.pid)); time.sleep(60)")
    t0 = time.monotonic()
    res = clitools.run([sys.executable, "-c", code], timeout=1.5, hardware=False)
    assert res["timed_out"] is True and time.monotonic() - t0 < 10
    child = int(marker.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("child of the timed-out tool survived")


def test_run_missing_tool():
    with pytest.raises(BenchError) as e:
        clitools.run(["/nonexistent/cb-missing-tool", "run"], timeout=5, hardware=False)
    assert e.value.code == "tool_missing"


@pytest.mark.parametrize(("argv", "hw"), [
    (["esptool", "--port", "/dev/ttyACM0", "flash-id"], True),
    (["/x/esptool.py", "chip-id"], True),
    (["python3", "-m", "esptool", "read-mac"], True),
    (["pio", "run", "-d", "x", "-t", "upload"], True),
    (["pio", "run", "--target=upload"], True),
    (["pio", "run", "-t", "nobuild", "-t", "upload"], True),
    (["pio", "device", "monitor"], True),
    (["pio", "run", "-d", "x"], True),  # without -t pio runs the `targets` of platformio.ini
    (["pio", "run", "-d", "x", "-t", "checkprogsize", "-t", "buildprog"], False),
    (["pio", "run", "-d", "x", "--target", "__idedata"], False),
    (["pio", "run", "-d", "x", "-tbuildprog", "-tupload"], True),
    (["pio", "run", "-t", "buildprog", "-t", "program"], True),
    (["pio", "run", "-t", "erase"], True),
    (["pio", "test", "-e", "s3"], True),
    (["pio", "project", "metadata", "--json-output"], False),
    (["pio", "project", "config", "--json-output"], False),
    (["pio", "--version"], False),
    (["python3", "-m", "platformio", "run"], True),
    (["esptool", "version"], False),
    (["xtensa-esp32s3-elf-addr2line", "-e", "f.elf"], False),
])
def test_touches_hardware(argv, hw):
    assert clitools.touches_hardware(argv) is hw


def test_hardware_switch_refuses(monkeypatch):
    with pytest.raises(BenchError) as e:
        clitools.run(["esptool", "flash-id"], timeout=5)
    assert e.value.code == "sim_only"
    with pytest.raises(BenchError):
        clitools.run([FAKE, "x"], timeout=5, hardware=True)
    with pytest.raises(BenchError) as e:  # hardware=False cannot clear a `pio run` without -t
        clitools.run(["pio", "run", "-d", "x"], timeout=5, hardware=False)
    assert e.value.code == "sim_only"


def test_find_override_path_and_candidates(tmp_path, monkeypatch):
    assert clitools.find("cb-fake-tool") == FAKE  # tests/fakes/bin is first on PATH
    assert clitools.find("pio", override=FAKE) == FAKE
    assert clitools.find("pio", override=str(tmp_path / "missing")) is None
    home = Path(os.environ["HOME"])
    pio = home / ".platformio" / "penv" / "bin" / "pio"
    pio.parent.mkdir(parents=True)
    pio.write_text("#!/bin/sh\n")
    pio.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert clitools.find("pio") == str(pio)
    assert clitools.find("esptool") is None


def test_on_line_callback_errors_are_ignored(tmp_path):
    seen = []
    def cb(line):
        seen.append(line)
        raise RuntimeError("boom")
    res = clitools.run([sys.executable, "-c", "print('a'); print('b')"], timeout=10, hardware=False, on_line=cb)
    assert res["rc"] == 0 and seen == ["a", "b"]


def _spy_popen(monkeypatch):
    started = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(clitools.subprocess, "Popen", spy)
    return started


def _interrupt_after(seconds):
    def interrupt(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGALRM, interrupt)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    return previous


def _run_case(case):
    if case == "normal":
        res = clitools.run([sys.executable, "-c", "print('a'); print('b')"], timeout=10, hardware=False)
        assert res["rc"] == 0 and res["out_tail"] == ["a", "b"]
    elif case == "timeout":
        res = clitools.run([sys.executable, "-c", "print('a', flush=True); import time; time.sleep(30)"],
                           timeout=0.5, hardware=False)
        assert res["timed_out"] is True
    elif case == "stop_when":
        res = clitools.run([sys.executable, "-c", "print('stop', flush=True); import time; time.sleep(30)"],
                           timeout=30, hardware=False, stop_when=lambda line: line == "stop")
        assert res["stopped"] is True and res["stop_line"] == "stop"
    else:
        previous = _interrupt_after(0.3)
        try:
            with pytest.raises(KeyboardInterrupt):
                clitools.run([sys.executable, "-c", "print('a', flush=True); import time; time.sleep(30)"],
                             timeout=60, hardware=False)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("case", ["normal", "timeout", "stop_when", "interrupt"])
def test_run_closes_the_output_pipe_and_reaps_the_tool(monkeypatch, case):
    """Every way out of run() closes the tool's output pipe and leaves a returncode (no zombie, no ResourceWarning
    when the Popen object is collected)."""
    if case == "interrupt" and not hasattr(signal, "setitimer"):
        pytest.skip("needs signal.setitimer")
    started = _spy_popen(monkeypatch)
    _run_case(case)
    assert len(started) == 1
    proc = started.pop()
    assert proc.stdout.closed
    assert proc.returncode is not None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        del proc
        gc.collect()
    assert [w for w in caught if issubclass(w.category, ResourceWarning)] == []


def test_run_tolerates_a_pipe_closed_under_the_reader(monkeypatch):
    """A pipe closed while the reader still iterates ends the reader quietly; the result stays intact."""
    started = _spy_popen(monkeypatch)
    seen, thread_errors = [], []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_type))

    def close_on_first(line):
        seen.append(line)
        started[0].stdout.close()

    res = clitools.run([sys.executable, "-c", "print('a'); print('b')"], timeout=10, hardware=False,
                       on_line=close_on_first)
    assert res["rc"] == 0 and res["out_tail"] == ["a"] and seen == ["a"]
    assert started[0].stdout.closed and thread_errors == []

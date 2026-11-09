"""clitools.run ends the tool's process group when waiting is interrupted (e.g. KeyboardInterrupt)."""
import os
import signal
import subprocess
import sys
import time

import pytest

from circuit_bench.bench_core import clitools


class _InterruptedPopen:
    """Stands in for subprocess.Popen: no real process, ``wait`` raises KeyboardInterrupt."""

    pid = 999_999_999
    returncode = None
    stdout = None

    def __init__(self, *args, **kwargs):
        pass

    def wait(self, timeout=None):
        raise KeyboardInterrupt


def test_interrupt_while_waiting_kills_the_group_once_and_raises(monkeypatch):
    killed = []
    monkeypatch.setattr(clitools.subprocess, "Popen", _InterruptedPopen)
    monkeypatch.setattr(clitools, "_kill_group", lambda proc: killed.append(proc))
    with pytest.raises(KeyboardInterrupt):
        clitools.run([sys.executable, "-c", "pass"], timeout=30, hardware=False)
    assert len(killed) == 1 and isinstance(killed[0], _InterruptedPopen)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="needs signal.setitimer")
def test_interrupt_ends_a_real_child_process_group(monkeypatch):
    started = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        started.append(proc)
        return proc

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    monkeypatch.setattr(clitools.subprocess, "Popen", spy)
    previous = signal.signal(signal.SIGALRM, interrupt)
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.3)
        with pytest.raises(KeyboardInterrupt):
            clitools.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60, hardware=False)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    assert len(started) == 1
    pgid = started[0].pid  # start_new_session: the child leads its own process group
    try:
        deadline = time.monotonic() + 2.0
        while _group_alive(pgid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _group_alive(pgid), "the tool's process group survived the interrupt"
    finally:
        if _group_alive(pgid):
            os.killpg(pgid, signal.SIGKILL)
            started[0].wait(timeout=5)

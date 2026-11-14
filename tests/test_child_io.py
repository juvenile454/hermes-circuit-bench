"""tests/child_io.py: a silent child ends a test with a clear failure after the time limit, never with a hang."""
import sys
import time

import pytest
from child_io import Child, ChildEnded, ChildTimeout

SILENT = "import time; time.sleep(60)"


def test_a_silent_child_fails_after_the_limit_and_is_killed():
    t0 = time.monotonic()
    with pytest.raises(ChildTimeout) as e, Child([sys.executable, "-c", SILENT]) as child:
        proc = child.proc
        child.readline("the READY line", timeout=0.5)
    assert 0.4 <= time.monotonic() - t0 < 15
    message = str(e.value)
    assert "no the READY line from the child within 0.5 s" in message and "still running" in message
    assert proc.returncode is not None  # the with block killed it
    assert proc.stdout.closed and proc.stderr.closed and proc.stdin.closed


def test_a_child_that_ends_early_reports_its_exit_code_and_stderr():
    code = "import sys; print('first', flush=True); sys.stderr.write('boom\\n'); sys.exit(7)"
    with Child([sys.executable, "-c", code]) as child:
        assert child.readline("first") == "first\n"
        with pytest.raises(ChildEnded) as e:
            child.readline("the second line", timeout=10)
        assert "ended while waiting for the second line" in str(e.value)
        assert "exited with 7" in str(e.value) and "boom" in str(e.value)
        with pytest.raises(ChildEnded):  # and it stays ended
            child.readline("anything", timeout=10)
        assert child.returncode == 7 and child.stderr_text() == "boom\n"


def test_a_child_that_ignores_its_input_is_killed_by_finish():
    with Child([sys.executable, "-c", SILENT]) as child:
        proc = child.proc
        with pytest.raises(ChildTimeout, match="did not end within 0.5 s after its input"):
            child.finish("\n", timeout=0.5)
        assert proc.returncode is not None


def test_lines_input_and_exit_code_of_a_well_behaved_child():
    code = "import sys; print('READY', flush=True); print(sys.stdin.readline().strip().upper(), flush=True)"
    with Child([sys.executable, "-c", code]) as child:
        assert child.readline("READY").strip() == "READY"
        child.send("done\n")
        assert child.readline("the echo").strip() == "DONE"
        assert child.finish("") == 0
        assert child.read_remaining() == ""
        assert child.stdout_lines == ["READY\n", "DONE\n"]


def test_read_remaining_is_time_limited_too():
    with Child([sys.executable, "-c", SILENT]) as child, pytest.raises(ChildTimeout, match="did not end within 0.3 s"):
        child.read_remaining(timeout=0.3)


def test_a_child_that_closes_stdout_and_ends_a_moment_later_is_reported_as_exited():
    # stdout is at its end while the child still lives: the message must wait for the exit code and the stderr line
    code = ("import os, sys, time; print('first', flush=True); os.close(1); time.sleep(0.3); "
            "sys.stderr.write('late boom\\n'); sys.stderr.flush(); sys.exit(7)")
    with Child([sys.executable, "-c", code]) as child:
        assert child.readline("first") == "first\n"
        with pytest.raises(ChildEnded) as e:
            child.readline("the second line", timeout=10)
        assert "exited with 7" in str(e.value) and "late boom" in str(e.value)
        assert "still running" not in str(e.value)
        assert child.returncode == 7 and child.stderr_text() == "late boom\n"


def test_a_child_that_closes_stdout_but_runs_on_is_reported_as_still_running_without_a_hang():
    code = "import os, sys, time; print('first', flush=True); os.close(1); time.sleep(2); sys.exit(4)"
    with Child([sys.executable, "-c", code], settle_timeout=0.3) as child:
        assert child.readline("first") == "first\n"
        t0 = time.monotonic()
        with pytest.raises(ChildEnded) as e:
            child.readline("the second line", timeout=10)
        assert time.monotonic() - t0 >= 0.25  # it waited for the settle limit, and then gave up on the child
        assert "still running" in str(e.value) and "exited with" not in str(e.value)
        assert child.finish("", timeout=10) == 4  # the child does end after the limit; nothing hung

"""``clitools.run(stop_when=...)`` ends the tool on the line it is told to stop at."""
import sys
import time

from circuit_bench.bench_core import clitools

# prints a line, then (if not stopped) leaves a marker file after a pause; the marker proves the tool ran on
SCRIPT = """
import sys, time, pathlib
print("hello", flush=True)
print(sys.argv[1], flush=True)
time.sleep(float(sys.argv[3]))
pathlib.Path(sys.argv[2]).write_text("ran on")
print("after", flush=True)
"""


def _run(tmp_path, line, stop_when, pause=5.0):
    marker = tmp_path / "marker"
    started = time.monotonic()
    res = clitools.run([sys.executable, "-c", SCRIPT, line, str(marker), str(pause)], timeout=30,
                       stop_when=stop_when)
    return res, marker, time.monotonic() - started


def test_stop_when_ends_the_tool_before_it_goes_on(tmp_path):
    res, marker, took = _run(tmp_path, "MAC: 02:00:00:00:00:02", lambda line: line.startswith("MAC: "))
    assert res["stopped"] is True and res["stop_line"] == "MAC: 02:00:00:00:00:02"
    assert res["timed_out"] is False and res["rc"] != 0
    assert not marker.exists()
    assert took < 1.5
    assert "after" not in res["out_tail"]


def test_stop_when_exception_stops_fail_closed(tmp_path):
    def broken(line: str) -> bool:
        if line == "STOP":
            raise ValueError("bad check")
        return False

    res, marker, took = _run(tmp_path, "STOP", broken)
    assert res["stopped"] is True and res["stop_line"] == "STOP"
    assert not marker.exists() and took < 1.5


def test_stop_when_false_runs_to_the_end(tmp_path):
    seen: list[str] = []

    def never(line: str) -> bool:
        seen.append(line)
        return False

    res, marker, _ = _run(tmp_path, "MAC: 02:00:00:00:00:01", never, pause=0.2)
    assert res["stopped"] is False and res["stop_line"] is None and res["rc"] == 0
    assert marker.exists() and seen == ["hello", "MAC: 02:00:00:00:00:01", "after"]


def test_without_stop_when_unchanged(tmp_path):
    res, marker, _ = _run(tmp_path, "MAC: 02:00:00:00:00:01", None, pause=0.2)
    assert res["rc"] == 0 and res["stopped"] is False and res["stop_line"] is None and marker.exists()
    assert set(res) == {"rc", "out_tail", "duration_s", "timed_out", "stopped", "stop_line"}


def test_stop_when_sees_lines_after_on_line(tmp_path):
    order: list[str] = []
    marker = tmp_path / "marker"
    clitools.run([sys.executable, "-c", SCRIPT, "X", str(marker), "0"], timeout=30,
                 on_line=lambda line: order.append(f"on:{line}"),
                 stop_when=lambda line: order.append(f"stop:{line}") or False)
    assert order[:2] == ["on:hello", "stop:hello"]


def test_timeout_still_wins_without_a_stop(tmp_path):
    marker = tmp_path / "marker"
    started = time.monotonic()
    res = clitools.run([sys.executable, "-c", SCRIPT, "x", str(marker), "10"], timeout=1, stop_when=lambda line: False)
    assert res["timed_out"] is True and res["stopped"] is False and res["stop_line"] is None
    assert not marker.exists() and time.monotonic() - started < 5

"""The serial monitor never runs past Hermes' tool deadline.

Hermes ends a tool call after ``timeouts.tools.sequential_call``, else ``timeouts.tools.concurrent_batch``, else the
environment variable ``HERMES_CONCURRENT_TOOL_TIMEOUT_S``, else 420 s (0 or negative: no deadline; an invalid value
falls to the next level). The monitor listens for at most that deadline minus a 20 s reserve, never under 1 s, and
says so in the warning ``monitor_capped``.

Every test uses a fake ``hermes_cli.config`` (no Hermes in the test environment) and a sim:// port. The fake clock
makes a monitor run of minutes finish at once; it only moves forward when the monitor (or the port reader) sleeps.
"""
from __future__ import annotations

import json
import sys
import time
import types

import board_fixtures as bf
import pytest
from board_fixtures import _board_isolation  # noqa: F401 - fixture (autouse)

from circuit_bench.bench_core import board, contracts, serialport

PORT = "sim://test-s3"
ENV_NAME = "HERMES_CONCURRENT_TOOL_TIMEOUT_S"
SEQ = "timeouts.tools.sequential_call"
BATCH = "timeouts.tools.concurrent_batch"
DEFAULT = "Hermes default"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"monitor_max_seconds": 3600}))
    board.register_provider("sim://", bf.TestProvider(lines=["boot", "ready"]))


@pytest.fixture
def hermes(monkeypatch):
    """Fake public hermes_cli.config; ``state.value`` is what load_config returns."""
    state = types.SimpleNamespace(value={})
    mod = types.ModuleType("hermes_cli.config")
    mod.load_config = lambda: state.value  # type: ignore[attr-defined]
    pkg = types.ModuleType("hermes_cli")
    pkg.config = mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    return state


@pytest.fixture
def fast_clock(monkeypatch):
    """Every sleep moves the monitor's clock 100 times as far, so a 400 s listen takes a moment."""
    offset = [0.0]
    real_sleep = time.sleep

    def monotonic() -> float:
        return time.monotonic() + offset[0]

    def sleep(seconds: float) -> None:
        offset[0] += 100 * max(0.0, seconds)
        real_sleep(0.0003)

    fake = types.SimpleNamespace(monotonic=monotonic, sleep=sleep, time=time.time)
    monkeypatch.setattr(serialport, "time", fake)
    return offset


def _config(**timeouts):
    """``{"timeouts": {"tools": {...}}}`` with the given keys (``None`` = key absent)."""
    tools = {k: v for k, v in timeouts.items() if v is not NOTHING}
    return {"timeouts": {"tools": tools}} if tools else {}


NOTHING = object()


class FailedConfigRead(dict):
    """Like Hermes' fallback for a config.yaml it cannot read: a dict (last known good values, the defaults or
    empty) with the attribute ``read_error`` set to the exception."""

    def __init__(self, data=(), *, error):
        super().__init__(data)
        self.read_error = error


def _run(seconds, fast_clock):
    env = serialport.monitor(PORT, seconds)
    assert contracts.validate_envelope(env) == [] and env["ok"], env.get("error")
    return env


def _capped(env):
    return [w for w in env["warnings"] if w["code"] == "monitor_capped"]


# ------------------------------------------------------------------------------------------ the chain of levels

@pytest.mark.parametrize("timeouts, env_value, deadline, source", [
    ({"sequential_call": 100}, None, 100, SEQ),
    ({"sequential_call": 100, "concurrent_batch": 50}, "30", 100, SEQ),  # the first valid level wins
    ({"concurrent_batch": 200}, None, 200, BATCH),
    ({"concurrent_batch": 200}, "30", 200, BATCH),
    ({}, "300", 300, ENV_NAME),
    ({}, " 90 ", 90, ENV_NAME),  # Hermes strips the variable
    ({}, None, 420, DEFAULT),
    ({}, "", 420, DEFAULT),
    ({"sequential_call": "150"}, None, 150, SEQ),  # a number as text is a number for Hermes
    ({"sequential_call": 100.5}, None, 100.5, SEQ),
])
def test_deadline_from_the_first_valid_level(hermes, fast_clock, monkeypatch, timeouts, env_value, deadline, source):
    hermes.value = _config(**timeouts)
    if env_value is not None:
        monkeypatch.setenv(ENV_NAME, env_value)
    env = _run(3000, fast_clock)
    effective = deadline - 20
    assert env["result"]["seconds"] == effective
    (w,) = _capped(env)
    assert w["severity"] == "info"
    assert f"{effective:g} s" in w["message"] and "3000 s" in w["message"] and f"{deadline:g} s" in w["message"]
    assert source in w["message"]
    assert (f"{effective:g} s") in env["summary"]


@pytest.mark.parametrize("value", ["abc", "", True, False, None, [], {}, "nan", float("nan"), "1,5"])
def test_invalid_level_falls_to_the_next(hermes, fast_clock, monkeypatch, value):
    hermes.value = _config(sequential_call=value, concurrent_batch=200)
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 180
    assert BATCH in _capped(env)[0]["message"]


@pytest.mark.parametrize("value", ["abc", True, None, [], float("nan")])
def test_invalid_levels_fall_through_to_the_environment_and_the_default(hermes, fast_clock, monkeypatch, value):
    hermes.value = _config(sequential_call=value, concurrent_batch=value)
    monkeypatch.setenv(ENV_NAME, "250")
    assert _run(3000, fast_clock)["result"]["seconds"] == 230
    monkeypatch.setenv(ENV_NAME, "not a number")  # an invalid variable is ignored as well
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 400 and DEFAULT in _capped(env)[0]["message"]


@pytest.mark.parametrize("config, env_value", [
    (_config(sequential_call=0), None),
    (_config(sequential_call=-1), None),
    (_config(sequential_call=-0.5, concurrent_batch=100), "100"),  # a later level does not bring the deadline back
    (_config(sequential_call="0", concurrent_batch=100), None),
    (_config(concurrent_batch=0), None),
    (_config(concurrent_batch=-30), "100"),
    (_config(sequential_call="abc", concurrent_batch=0), "100"),
    (_config(), "0"),
    (_config(), "-5"),
    (_config(), "nan"),  # Hermes reads a NaN in the variable as no deadline
])
def test_zero_or_negative_means_no_deadline(hermes, fast_clock, monkeypatch, config, env_value):
    hermes.value = config
    if env_value is not None:
        monkeypatch.setenv(ENV_NAME, env_value)
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 3000
    assert _capped(env) == []


def test_a_huge_deadline_is_capped_like_hermes_and_does_not_shorten(hermes, fast_clock):
    for value in (1e12, "1e400", 10 ** 30, float("inf")):
        hermes.value = _config(sequential_call=value)
        env = _run(3000, fast_clock)
        assert env["result"]["seconds"] == 3000 and _capped(env) == []
    hermes.value = _config(sequential_call=10 ** 400)  # float() overflows: not a usable number
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 400 and DEFAULT in _capped(env)[0]["message"]


# --------------------------------------------------------------------------------------- reserve and lower bound

@pytest.mark.parametrize("deadline, effective", [(21.5, 1.5), (21, 1), (20, 1), (5, 1), (0.5, 1), (22, 2)])
def test_lower_bound_is_one_second(hermes, fast_clock, deadline, effective):
    hermes.value = _config(sequential_call=deadline)
    env = _run(60, fast_clock)
    assert env["result"]["seconds"] == effective
    assert f"{effective:g} s" in _capped(env)[0]["message"]


def test_a_request_below_the_lower_bound_is_not_raised(hermes, fast_clock):
    hermes.value = _config(sequential_call=5)
    env = _run(0.5, fast_clock)
    assert env["result"]["seconds"] == 0.5 and _capped(env) == []


# --------------------------------------------------------------------------------------------- the warning

def test_no_warning_without_a_cut(hermes, fast_clock):
    env = _run(300, fast_clock)  # default deadline 420 s: 400 s allowed
    assert env["result"]["seconds"] == 300 and _capped(env) == []
    hermes.value = _config(sequential_call=100)
    env = _run(80, fast_clock)  # exactly the allowed time: nothing cut
    assert env["result"]["seconds"] == 80 and _capped(env) == []
    env = _run(10, fast_clock)
    assert env["result"]["seconds"] == 10 and _capped(env) == []


def test_warning_names_both_numbers_the_deadline_and_the_setting(hermes, fast_clock):
    hermes.value = _config(sequential_call=300)
    env = _run(1000, fast_clock)
    (w,) = _capped(env)
    assert w["code"] == "monitor_capped" and w["severity"] == "info"
    assert "1000 s" in w["message"] and "280 s" in w["message"] and "300 s" in w["message"]
    assert "timeouts.tools.sequential_call" in w["message"]
    assert env["result"]["seconds"] == 280
    assert contracts.validate_envelope(env) == []


def test_the_monitor_max_seconds_assumption_stays(hermes, fast_clock, monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"monitor_max_seconds": 120}))
    # the setting is the smaller limit: its assumption, no warning
    env = _run(600, fast_clock)
    assert env["result"]["seconds"] == 120 and _capped(env) == []
    (a,) = [a for a in env["assumptions"] if a["key"] == "seconds"]
    assert a["value"] == "120" and a["reason"] == "limited by the monitor_max_seconds setting (120 s)"
    # Hermes' deadline is the smaller limit: both are reported, the warning counts from the already limited 120 s
    hermes.value = _config(sequential_call=70)
    env = _run(600, fast_clock)
    assert env["result"]["seconds"] == 50
    (a,) = [a for a in env["assumptions"] if a["key"] == "seconds"]
    assert a["value"] == "120"
    (w,) = _capped(env)
    assert "120 s" in w["message"] and "50 s" in w["message"] and "70 s" in w["message"]
    # no limit hit: neither
    env = _run(30, fast_clock)
    assert env["result"]["seconds"] == 30 and _capped(env) == []
    assert not [a for a in env["assumptions"] if a["key"] == "seconds"]


# -------------------------------------------------------------------- Hermes missing or its configuration unreadable

def test_without_hermes_the_environment_and_then_420_apply(fast_clock, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_cli", None)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 400 and DEFAULT in _capped(env)[0]["message"]
    monkeypatch.setenv(ENV_NAME, "100")
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 80 and ENV_NAME in _capped(env)[0]["message"]


@pytest.mark.parametrize("broken", ["read_error", "raises", "not_a_dict", "level_not_a_dict"])
def test_unreadable_configuration_counts_as_not_set(hermes, fast_clock, monkeypatch, broken):
    """Unreadable without any fallback values: the two configuration levels are not set."""
    if broken == "read_error":
        hermes.value = FailedConfigRead({}, error=ValueError("bad yaml"))  # an empty fallback
    elif broken == "raises":
        def boom():
            raise RuntimeError("broken")

        monkeypatch.setattr(sys.modules["hermes_cli.config"], "load_config", boom)
    elif broken == "not_a_dict":
        hermes.value = ["timeouts"]
    else:
        hermes.value = {"timeouts": "fast"}
    monkeypatch.setenv(ENV_NAME, "100")
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 80 and ENV_NAME in _capped(env)[0]["message"]


# A config.yaml broken while Hermes runs: Hermes keeps using its fallback values (the last known good config, its
# defaults or nothing), so the monitor uses the same ones and never listens longer than Hermes waits.

@pytest.mark.parametrize("error", [ValueError("bad yaml"), OSError(5, "io")], ids=lambda e: type(e).__name__)
def test_fallback_sequential_call_is_the_deadline(hermes, fast_clock, monkeypatch, error):
    hermes.value = FailedConfigRead(_config(sequential_call=60), error=error)
    monkeypatch.setenv(ENV_NAME, "300")
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 40
    message = _capped(env)[0]["message"]
    assert SEQ in message and "60 s" in message and "40 s" in message


def test_fallback_concurrent_batch_is_the_deadline(hermes, fast_clock, monkeypatch):
    hermes.value = FailedConfigRead(_config(concurrent_batch=90), error=ValueError("bad yaml"))
    monkeypatch.setenv(ENV_NAME, "300")
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 70 and BATCH in _capped(env)[0]["message"]


def test_empty_fallback_uses_the_environment_and_then_420(hermes, fast_clock, monkeypatch):
    hermes.value = FailedConfigRead({}, error=ValueError("bad yaml"))
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 400 and DEFAULT in _capped(env)[0]["message"]
    monkeypatch.setenv(ENV_NAME, "100")
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 80 and ENV_NAME in _capped(env)[0]["message"]


@pytest.mark.parametrize("timeouts", ["broken", ["tools"], {"tools": "fast"}, {"tools": {"sequential_call": "x"}}])
def test_fallback_with_an_unusable_level_falls_to_the_next(hermes, fast_clock, monkeypatch, timeouts):
    hermes.value = FailedConfigRead({"timeouts": timeouts}, error=ValueError("bad yaml"))
    monkeypatch.setenv(ENV_NAME, "100")
    env = _run(3000, fast_clock)
    assert env["result"]["seconds"] == 80 and ENV_NAME in _capped(env)[0]["message"]


def test_fallback_zero_means_no_deadline(hermes, fast_clock, monkeypatch):
    hermes.value = FailedConfigRead(_config(sequential_call=0), error=ValueError("bad yaml"))
    monkeypatch.setenv(ENV_NAME, "100")
    env = _run(600, fast_clock)
    assert env["result"]["seconds"] == 600 and _capped(env) == []


def test_fallback_short_deadline_gives_the_lower_bound(hermes, fast_clock):
    hermes.value = FailedConfigRead(_config(sequential_call=15), error=ValueError("bad yaml"))
    env = _run(30, fast_clock)
    assert env["result"]["seconds"] == 1 and len(_capped(env)) == 1


def test_fallback_does_not_change_the_plugin_settings(hermes, fast_clock, monkeypatch):
    """The fallback counts for the deadline only: the plugin settings in it are not used (the safe values)."""
    monkeypatch.delenv("CIRCUIT_BENCH_SETTINGS_JSON", raising=False)
    monkeypatch.setenv("CIRCUIT_BENCH_HW", "on")
    monkeypatch.setattr(serialport._settings, "_unreadable_logged", False, raising=False)
    entry = {"hardware_access": True, "allow_flash": True, "approve_serial": False, "monitor_max_seconds": 5}
    data = {**_config(sequential_call=60), "plugins": {"entries": {"circuit-bench": {"settings": entry}}}}
    hermes.value = FailedConfigRead(data, error=ValueError("bad yaml"))
    s = serialport._settings.load()
    assert s["hardware_access"] is False and s["allow_flash"] is False and s["approve_serial"] is True
    assert serialport._hermes_tool_deadline() == (60, SEQ)


def test_the_configuration_is_read_through_hermes_value_only(monkeypatch, fast_clock):
    """No import of Hermes modules in the monitor: the two keys come through ``settings.hermes_value``."""
    asked: list[tuple] = []

    def fake(*path, default=None, last_known_good=False):
        asked.append((path, last_known_good))
        return {("timeouts", "tools", "sequential_call"): None,
                ("timeouts", "tools", "concurrent_batch"): 90}.get(path, default)

    monkeypatch.setattr(serialport._settings, "hermes_value", fake)
    env = _run(3000, fast_clock)
    # the deadline Hermes itself uses: its fallback values count while config.yaml cannot be read
    assert asked == [(("timeouts", "tools", "sequential_call"), True), (("timeouts", "tools", "concurrent_batch"), True)]
    assert env["result"]["seconds"] == 70 and BATCH in _capped(env)[0]["message"]


# ----------------------------------------------------------------------------------------- real clock, no cheating

def test_a_capped_monitor_really_listens_for_the_shortened_time(hermes):
    hermes.value = _config(sequential_call=21.5)
    t0 = time.monotonic()
    env = serialport.monitor(PORT, 30)
    took = time.monotonic() - t0
    assert 1.4 <= took < 4 and env["result"]["seconds"] == 1.5
    assert env["result"]["lines"] == ["boot", "ready"] and len(_capped(env)) == 1
    assert not serialport.port_is_open(PORT)

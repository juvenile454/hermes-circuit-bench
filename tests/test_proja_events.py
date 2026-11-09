"""events.emit -> hermes_cli.plugin_events.broadcast_plugin_event (no-op without Hermes)."""
import importlib.util
import logging
import sys
import types

import pytest

from circuit_bench.bench_core import events

PAYLOADS = {
    "project.updated": {"id": "laser-trigger", "rev": 13, "changed": ["assignments"], "by": "agent"},
    "board.changed": {"port": "sim://esp32s3-n16r8", "state": "linked", "simulated": True},
    "panic.detected": {"project": "laser-trigger", "port": "sim://esp32s3-n16r8", "reason": "StoreProhibited",
                       "top_frame": "write_sensor_buffer (src/main.cpp:5)", "log_ref": "panic-20261106-214002.log"},
    "job.updated": {"job_id": "j1", "kind": "build", "state": "running", "progress": 0.5},
}


@pytest.fixture
def fake_hermes(monkeypatch):
    calls = []
    pkg = types.ModuleType("hermes_cli")
    mod = types.ModuleType("hermes_cli.plugin_events")

    def broadcast_plugin_event(plugin_id, event, payload=None):
        calls.append((plugin_id, event, payload))

    mod.broadcast_plugin_event = broadcast_plugin_event
    pkg.plugin_events = mod
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", mod)
    return types.SimpleNamespace(calls=calls, module=mod)


def test_no_hermes_is_a_debug_noop(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", None)  # import raises ImportError
    with caplog.at_level(logging.DEBUG, logger="circuit_bench.bench_core.events"):
        for name, payload in PAYLOADS.items():
            assert events.emit(name, payload) is False
    assert sum("not sent (no Hermes" in r.getMessage() for r in caplog.records) == len(PAYLOADS)
    assert all(r.levelno == logging.DEBUG for r in caplog.records)


def test_without_hermes_on_path_too():
    # the test venv has no Hermes at all: the real import fails and emit stays silent
    if "hermes_cli" in sys.modules or importlib.util.find_spec("hermes_cli") is not None:
        pytest.skip("Hermes is importable in this run")
    assert events.emit("project.updated", PAYLOADS["project.updated"]) is False


def test_every_event_goes_to_broadcast(fake_hermes):
    for name, payload in PAYLOADS.items():
        assert events.emit(name, payload) is True
    assert [c[:2] for c in fake_hermes.calls] == [("circuit-bench", n) for n in PAYLOADS]
    assert fake_hermes.calls[0][2] == PAYLOADS["project.updated"]


def test_payload_is_a_detached_json_copy(fake_hermes):
    payload = {"id": "p", "rev": 2, "changed": ["notes"], "by": "ui", "extra": (1, 2)}
    events.emit("project.updated", payload)
    sent = fake_hermes.calls[0][2]
    assert sent == {"id": "p", "rev": 2, "changed": ["notes"], "by": "ui", "extra": [1, 2]}
    sent["changed"].append("x")
    assert payload["changed"] == ["notes"]


@pytest.mark.parametrize("name", ["", "project..updated", ".project", "project.", "../x", "a b", "a/b", "x" * 129,
                                  None, 3, "project.deleted", "plugin.circuit-bench.project.updated"])
def test_invalid_or_unknown_name_raises(fake_hermes, name):
    with pytest.raises(ValueError):
        events.emit(name, {})
    assert fake_hermes.calls == []


@pytest.mark.parametrize("payload", [None, [], "x", {"id": "p", "rev": 1, "changed": []},
                                     {"id": "p", "rev": 1, "changed": [], "by": "agent", "bad": object()},
                                     {"id": "p", "rev": float("nan"), "changed": [], "by": "agent"}])
def test_bad_payload_raises(fake_hermes, payload):
    with pytest.raises(ValueError):
        events.emit("project.updated", payload)
    assert fake_hermes.calls == []


def test_delivery_error_is_swallowed(fake_hermes, caplog):
    def boom(*a, **kw):
        raise RuntimeError("transport wedged")

    fake_hermes.module.broadcast_plugin_event = boom
    with caplog.at_level(logging.DEBUG, logger="circuit_bench.bench_core.events"):
        assert events.emit("job.updated", PAYLOADS["job.updated"]) is False
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


def test_wire_name():
    assert events.wire_name("project.updated") == "plugin.circuit-bench.project.updated"
    with pytest.raises(ValueError):
        events.wire_name("nope")


@pytest.mark.hermes
def test_real_hermes_bridge_builds_the_wire_name(monkeypatch):
    """With the scratch clone: the real plugin_events accepts our names and forwards plugin.circuit-bench.<event>."""
    pe = pytest.importorskip("hermes_cli.plugin_events")
    sent = []
    server = types.ModuleType("tui_gateway.server")
    server._broadcast_global_event = lambda name, payload=None, **kw: sent.append((name, payload))
    pkg = types.ModuleType("tui_gateway")
    pkg.server = server
    monkeypatch.setitem(sys.modules, "tui_gateway", pkg)
    monkeypatch.setitem(sys.modules, "tui_gateway.server", server)
    for name, payload in PAYLOADS.items():
        assert pe.plugin_event_name(events.PLUGIN_ID, name) == events.wire_name(name)
        assert events.emit(name, payload) is True
    assert [n for n, _ in sent] == [f"plugin.circuit-bench.{n}" for n in PAYLOADS]
    assert sent[0][1] == PAYLOADS["project.updated"]

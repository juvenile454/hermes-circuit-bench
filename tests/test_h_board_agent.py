"""set_board pin checks, fit() keeps the scalar keys, a simulated flash is not verified, and approval modes are
read like Hermes' ``_binary_approval_mode``."""
import json
import sys
import types

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import contracts, guard, sim


def call(host, name, **args):
    env = json.loads(tools.make_handlers(host)[name](args))
    assert contracts.validate_envelope(env) == [], env
    return env


# ------------------------------------------------------------------------------------------------ set_board

def test_set_board_answers_with_the_pin_checks_like_assign():
    host = tools.Host(hook_active=True)
    env = call(host, "bench_project", action="create", id="hb-pins", title="Pins", chip="esp32s3", variant="n16r8",
               devkit="esp32-s3-devkitc-1", assignments=[{"role": "LED", "mode": "out", "pin": "GPIO4"},
                                                         {"role": "SDA", "mode": "i2c_sda", "pin": "GPIO35"}])
    assert env["ok"], env
    assigned = call(host, "bench_project", action="assign", id="hb-pins", role="BTN", mode="in_pullup", pin="GPIO5")
    pin_ids = sorted(c["id"] for c in assigned["checks"])
    assert pin_ids, assigned
    env = call(host, "bench_project", action="set_board", id="hb-pins", wifi=False)
    assert env["ok"], env
    assert sorted(c["id"] for c in env["checks"]) == pin_ids  # same checks as an assign answer
    assert env["result"]["all_roles"] == ["LED", "SDA", "BTN"]
    # without assignments there is nothing to check (and no error)
    call(host, "bench_project", action="create", id="hb-empty", title="Empty", chip="esp32s3")
    env = call(host, "bench_project", action="set_board", id="hb-empty", wifi=False)
    assert env["ok"] and env["checks"] == []


# ------------------------------------------------------------------------------------------------ fit()

KEPT = {"ok": True, "rev": 7, "port": "/dev/ttyACM0", "mac": "02:00:00:00:00:01", "elf_sha256": "c" * 64,
        "log_ref": "flash-20261107-120000-abcdef.log", "svg_path": "/tmp/cb/x.svg", "calc_id": "calc-led-1",
        "job_id": "j-0001-abcdef"}


def test_fit_keeps_the_scalar_keys_in_its_last_stage():
    huge = {f"k{i:05d}": i for i in range(5000)}  # many keys: no list/text cut makes this small
    env = contracts.envelope("board.flash", "Flashed.", {**KEPT, "noise": huge, "nested": {"port": "inner"}})
    assert len(json.dumps(env)) > 50_000
    out = tools.fit(env)
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= tools.MAX_BYTES
    assert contracts.validate_envelope(out) == []
    assert out["result"] == {**KEPT, "truncated": True}
    assert any(w["code"] == "result_truncated" for w in out["warnings"])


def test_fit_last_stage_keeps_only_scalars_and_short_texts():
    big = {**KEPT, "port": "x" * 20_000, "rev": {"no": "dict"}, "mac": None,
           "noise": {f"k{i:05d}": i for i in range(5000)}}
    out = tools.fit(contracts.envelope("board.flash", "Flashed.", big))
    assert len(json.dumps(out, ensure_ascii=False).encode("utf-8")) <= tools.MAX_BYTES
    r = out["result"]
    assert r["truncated"] is True and "rev" not in r and r["mac"] is None
    assert len(r["port"]) <= 301 and r["elf_sha256"] == "c" * 64


# ------------------------------------------------------------------------------------------------ sim flash

def test_simulated_flash_does_not_claim_verified(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(sim, "TIME_SCALE", 0.0)
    fw = tmp_path / "fw"
    shutil.copytree(sim.EXAMPLES_DIR / "laser-trigger", fw)
    from circuit_bench.bench_core import board
    sha = board.build(fw, "s3", port=sim.PORT)["result"]["elf_sha256"]
    env = board.flash(fw, "s3", sim.PORT, expected_elf_sha256=sha,
                      guard=lambda: guard.check_flash(via="tool", settings=None, project=None, port=sim.PORT,
                                                      cron=False))
    assert env["ok"] and env["simulated"] is True, env
    assert env["result"]["verified"] is False
    assert {c["id"]: c["status"] for c in env["checks"]}["board.flash.verified"] == "not_checked"
    from circuit_bench.bench_core import runtime
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


# ------------------------------------------------------------------------------------------------ approval modes

@pytest.fixture
def hermes_config(monkeypatch):
    state = types.SimpleNamespace(value={})
    mod = types.ModuleType("hermes_cli.config")

    def load_config():
        if isinstance(state.value, BaseException):
            raise state.value
        return state.value

    mod.load_config = load_config  # type: ignore[attr-defined]
    pkg = types.ModuleType("hermes_cli")
    pkg.config = mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    return state


@pytest.mark.parametrize("key", ["single_query_mode", "unattended_mode"])
@pytest.mark.parametrize("value, bypass", [
    (False, False), (True, False),  # YAML bools: Hermes reads "false"/"true" -> deny
    ("approve", True), (" Approve\n", True), ("allow", True), ("yes", True), ("off", True),
    ("deny", False), ("true", False), ("on", False), ("", False), (None, False), (0, False), (1, False),
])
def test_auto_approve_values_like_hermes(hermes_config, key, value, bypass):
    hermes_config.value = {"approvals": {"mode": "manual", key: value}}
    assert guard.approvals_bypassed() is bypass


@pytest.mark.parametrize("cfg", [RuntimeError("broken yaml"), ["approvals"], {"approvals": "manual"}])
def test_unreadable_config_stays_fail_closed(hermes_config, cfg):
    hermes_config.value = cfg
    assert guard.approvals_bypassed() is True


def test_odd_values_stringify_like_hermes(hermes_config):
    class Weird:
        def __str__(self):
            return "APPROVE"

    hermes_config.value = {"approvals": {"unattended_mode": Weird()}}
    assert guard.approvals_bypassed() is True

    class Broken:
        def __str__(self):
            raise ValueError("no text")

    hermes_config.value = {"approvals": {"unattended_mode": Broken()}}
    assert guard.approvals_bypassed() is True  # unreadable: fail closed (Hermes would deny the auto-approval)

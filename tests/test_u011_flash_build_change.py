"""The flash grant names the images and the time (``at``) of the last build at the time of the question: a new build
between the question and the handler (Bench UI, another session) with the same ELF but another partition table is
refused with not_confirmed, and esptool never starts. The whole agent path runs: hook, handler, board.flash, with
the fake pio/esptool and a pty port (nothing reaches a real device)."""
import hashlib
import json
import sys
import types

import board_fixtures as bf
import pytest
import test_api_support as sup
from board_fixtures import fake_tools, hw_on, pty_port  # noqa: F401

from circuit_bench import hooks, tools
from circuit_bench.bench_core import board, project, runtime

MAC = "aa:bb:cc:dd:ee:ff"
TASK = "task-A"
PID = "rebuild"


@pytest.fixture
def cfg(monkeypatch):
    mod = types.ModuleType("hermes_cli.config")
    mod.value = {"approvals": {"mode": "manual"},
                 "plugins": {"entries": {"circuit-bench": {"settings": {"allow_flash": True}}}}}
    mod.load_config = lambda: mod.value
    pkg = types.ModuleType("hermes_cli")
    pkg.config = mod
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", mod)
    monkeypatch.delenv("HERMES_YOLO_MODE", raising=False)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    monkeypatch.delenv("CIRCUIT_BENCH_SETTINGS_JSON", raising=False)  # settings come from the fake Hermes config
    yield mod
    b = runtime.peek("broker")
    if b is not None:
        b.shutdown()


def _ready(fake_tools, pty_port, monkeypatch, tmp_path, *, images=True):  # noqa: F811
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fw = sup.write_firmware(tmp_path / "fw")
    fake_tools.scenario("board-pio-flash-ok.json")
    built = board.build(fw, "s3")
    assert built["ok"], built["error"]
    result = dict(built["result"])
    if not images:  # a build recorded by an older version: no images
        result.pop("images", None)
    assert project.create(PID, "Rebuild", "esp32s3", "n16r8", "esp32-s3-devkitc-1", by="agent")["ok"]
    upd = project.update(PID, 1, [
        {"op": "set_detected", "port": pty_port.name, "mac": MAC, "chip": "ESP32-S3 (QFN56) (revision v0.2)"},
        {"op": "set_firmware", "dir": str(fw), "env": "s3"}, {"op": "set_build", **result}],
        by="ui", trusted=True)
    assert upd["ok"], upd
    host = tools.Host(hook_active=True)
    args = {"action": "flash", "project": PID, "elf_sha256": result["elf_sha256"]}
    return types.SimpleNamespace(fw=fw, host=host, args=args, built=result, tools=fake_tools)


@pytest.fixture
def ready(fake_tools, hw_on, pty_port, monkeypatch, tmp_path, cfg):  # noqa: F811
    return _ready(fake_tools, pty_port, monkeypatch, tmp_path)


def hook(r):
    return hooks.decide(r.host, "bench_board", r.args, TASK)


def handler(r):
    return json.loads(tools.make_handlers(r.host)["bench_board"](r.args, task_id=TASK))


def writes(r):
    return [c for c in r.tools.calls("esptool") if "write-flash" in c["argv"]]


def store_build(result):
    rev = project.get(PID)["result"]["project"]["rev"]
    upd = project.update(PID, rev, [{"op": "set_build", **result}], by="ui", trusted=True)
    assert upd["ok"], upd


def test_a_rebuild_with_the_same_elf_and_new_partitions_during_the_question_is_refused(ready):
    assert hook(ready)["action"] == "approve"
    new = b"NEW PARTITION TABLE"
    (ready.fw / ".pio" / "build" / "s3" / "partitions.bin").write_bytes(new)
    images = {**ready.built["images"], "partitions.bin": hashlib.sha256(new).hexdigest()}
    calls_before = len(ready.tools.calls("esptool"))
    store_build({**ready.built, "images": images})
    env = handler(ready)
    assert env["ok"] is False and env["error"]["code"] == "not_confirmed", env
    assert env["error"]["message"] == "the build changed after the approval"
    assert env["error"]["hint"] == "flash again: the user approves the new build"
    assert len(ready.tools.calls("esptool")) == calls_before and writes(ready) == []


def test_a_rebuild_with_the_same_images_but_a_new_time_is_refused(ready):
    assert hook(ready)["action"] == "approve"
    store_build({**ready.built, "at": "2030-01-01T00:00:00Z"})
    env = handler(ready)
    assert env["ok"] is False and env["error"]["code"] == "not_confirmed", env
    assert writes(ready) == []


def test_a_flash_right_after_the_build_goes_through(ready):
    assert hook(ready)["action"] == "approve"
    env = handler(ready)
    assert env["ok"], env
    assert len(writes(ready)) == 1


def test_a_flash_under_an_always_rule_goes_through_each_time(ready):
    """With "always" Hermes still runs the hook for each call (it only skips the question): each call gets its own
    grant naming the build at that time."""
    keys = set()
    for n in (1, 2):
        dec = hook(ready)
        assert dec["action"] == "approve"
        keys.add(dec["rule_key"])
        env = handler(ready)
        assert env["ok"], env
        assert len(writes(ready)) == n
    assert len(keys) == 1  # the same rule: "always" covers the second call


def test_a_new_question_after_the_rebuild_flashes_the_new_build(ready):
    assert hook(ready)["action"] == "approve"
    store_build({**ready.built, "at": "2030-01-01T00:00:00Z"})
    assert handler(ready)["error"]["code"] == "not_confirmed"
    assert hook(ready)["action"] == "approve"
    env = handler(ready)
    assert env["ok"], env
    assert len(writes(ready)) == 1


def test_a_build_without_images_from_an_older_version_is_not_refused(fake_tools, hw_on, pty_port, monkeypatch,  # noqa: F811
                                                                   tmp_path, cfg):
    r = _ready(fake_tools, pty_port, monkeypatch, tmp_path, images=False)
    assert "images" not in project.get(PID)["result"]["project"]["firmware"]["last_build"]
    assert hook(r)["action"] == "approve"
    env = handler(r)
    assert env["ok"], env
    assert len(writes(r)) == 1


def test_the_binding_compares_images_and_time_with_the_project():
    proj = {"id": "p", "board": {"detected": {"port": "/dev/ttyCB0", "mac": MAC}},
            "firmware": {"dir": "/w/fw", "env": "s3",
                         "last_build": {"ok": True, "elf_sha256": "a" * 64, "at": "2026-11-14T00:00:00Z",
                                        "images": {"partitions.bin": "b" * 64}}}}
    grant = {"port": "/dev/ttyCB0", "mac": MAC, "elf_sha256": "a" * 64, "dir": "/w/fw", "env": "s3",
             "images": {"partitions.bin": "b" * 64}, "at": "2026-11-14T00:00:00Z"}
    assert tools._flash_binding(proj, "/dev/ttyCB0", "a" * 64, "a" * 12, grant) is None
    for change in ({"images": {"partitions.bin": "c" * 64}}, {"images": None}, {"at": "2026-11-14T00:00:01Z"},
                   {"at": None}):
        env = tools._flash_binding(proj, "/dev/ttyCB0", "a" * 64, "a" * 12, {**grant, **change})
        assert env["error"]["code"] == "not_confirmed", change
    old = {k: v for k, v in grant.items() if k not in ("images", "at")}  # a grant without them: fail closed
    assert tools._flash_binding(proj, "/dev/ttyCB0", "a" * 64, "a" * 12, old)["error"]["code"] == "not_confirmed"
    bare = {**proj, "firmware": {**proj["firmware"], "last_build": {"ok": True, "elf_sha256": "a" * 64}}}
    assert tools._flash_binding(bare, "/dev/ttyCB0", "a" * 64, "a" * 12, old) is None  # both sides without: equal

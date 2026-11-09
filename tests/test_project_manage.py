"""Project manager: project.delete moves the folder to the trash; DELETE /projects/{id} (UI only)."""
import json
import threading

import test_api_support as sup
from test_api_support import *  # noqa: F403

from circuit_bench.bench_core import contracts, jobs, project, storage


def _make(pid, tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUIT_BENCH_DATA_DIR", str(tmp_path))
    env = project.create(pid, pid.upper(), "esp32s3", "n16r8", "esp32-s3-devkitc-1", by="ui")
    assert env["ok"], env
    return project.path(pid)


def test_delete_moves_the_whole_folder_to_the_trash(tmp_path, monkeypatch):
    pdir = _make("bench-x", tmp_path, monkeypatch)
    (pdir / "firmware").mkdir()
    (pdir / "firmware" / "main.cpp").write_text("// mine", encoding="utf-8")
    env = project.delete("bench-x")
    assert env["ok"] and env["action"] == "project.delete" and env["result"]["id"] == "bench-x"
    trash = storage.data_dir() / "trash"
    moved = trash / env["result"]["trash"].rsplit("/", 1)[1]
    assert env["result"]["trash"] == str(moved) and moved.name.startswith("bench-x-") and pdir.parent.parent == trash.parent
    assert not pdir.exists()
    assert json.loads((moved / "project.json").read_text(encoding="utf-8"))["id"] == "bench-x"
    assert (moved / "firmware" / "main.cpp").read_text(encoding="utf-8") == "// mine"  # nothing is removed
    assert [p["id"] for p in project.list()["result"]["projects"]] == []
    assert project.get("bench-x")["error"]["code"] == "project_not_found"
    # the same id can be created again and trashed again without clobbering the first copy
    _make("bench-x", tmp_path, monkeypatch)
    second = project.delete("bench-x")
    assert second["ok"] and second["result"]["trash"] != env["result"]["trash"]
    assert len(list(trash.iterdir())) == 2


def test_delete_never_touches_a_firmware_folder_outside_the_project(tmp_path, monkeypatch):
    _make("bench-o", tmp_path, monkeypatch)
    own = tmp_path / "my-firmware"
    sup.write_firmware(own, env="s3")
    env = project.update("bench-o", 1, [{"op": "set_firmware", "dir": str(own), "env": "s3"}], by="agent")
    assert env["ok"], env
    assert project.delete("bench-o")["ok"]
    assert (own / "platformio.ini").is_file()


def test_delete_refusals(tmp_path, monkeypatch):
    _make("bench-r", tmp_path, monkeypatch)
    assert project.delete("nope")["error"]["code"] == "project_not_found"
    for bad in ("../bench-r", "Bench", "", "a/b", None):
        assert project.delete(bad)["error"]["code"] == "invalid_args", bad
    assert project.delete("bench-r", by="cron")["error"]["code"] == "invalid_args"
    assert project.path("bench-r").is_dir()


def test_a_damaged_project_can_be_deleted(tmp_path, monkeypatch):
    pdir = _make("bench-d", tmp_path, monkeypatch)
    (pdir / "project.json").write_text("{broken", encoding="utf-8")
    env = project.delete("bench-d")
    assert env["ok"] and env["result"]["title"] == "bench-d"
    assert not pdir.exists()


def test_action_and_running_helper_are_known():
    assert "project.delete" in contracts.ACTIONS
    table = jobs.JobTable(emit=lambda *a: None)
    gate = threading.Event()
    job = table.start("build", lambda ctx: (gate.wait(5), {"ok": True})[1], key="build:bench-j")
    assert table.running("build:bench-j") == job["job_id"] and table.running("build:other") is None
    gate.set()
    table.wait(job["job_id"], 5)
    assert table.running("build:bench-j") is None


# --------------------------------------------------------------------------------------------- route

def test_delete_route(api, events):
    api.create("bench-a")
    api.create("bench-b")
    env = api.ok(api.delete("/projects/bench-a"))
    assert env["action"] == "project.delete" and "/trash/bench-a-" in env["result"]["trash"]
    assert [x["id"] for x in api.ok(api.get("/projects"))["result"]["projects"]] == ["bench-b"]
    api.err(api.delete("/projects/bench-a"), 404, "project_not_found")
    api.err(api.delete("/projects/Bad..id"), 400, "invalid_args")
    deleted = [e for e in events.of("project.updated") if e["changed"] == ["deleted"]]
    assert [(e["id"], e["rev"], e["by"]) for e in deleted] == [("bench-a", 1, "ui")]


def test_delete_route_waits_for_a_running_build(api):
    api.create("bench-j")
    table = sup.route_module("jobs").table()
    gate = threading.Event()
    job = table.start("build", lambda ctx: (gate.wait(5), {"ok": True})[1], key="build:bench-j")
    try:
        body = api.err(api.delete("/projects/bench-j"), 423, "port_busy")
        assert job["job_id"] in body["error"]["message"]
    finally:
        gate.set()
        table.wait(job["job_id"], 5)
    api.ok(api.delete("/projects/bench-j"))


# --------------------------------------------------------------------------------------------- remove_parts

def test_remove_parts(tmp_path, monkeypatch, events):
    _make("bench-p", tmp_path, monkeypatch)
    env = project.update("bench-p", 1, [{"op": "add_parts", "parts": [
        {"ref": "R1", "kind": "resistor", "value": "1 kΩ", "from_calc": "npn-1"},
        {"ref": "Q1", "kind": "transistor", "value": "2N2222A"}, {"ref": "LED1", "kind": "led", "value": "red"}]},
        {"op": "add_calc", "calc": {"id": "npn-1", "type": "npn", "inputs": {}, "result": {}}}], by="ui")
    assert env["ok"], env
    env = project.update("bench-p", 2, [{"op": "remove_parts", "refs": ["r1", "LED1", "R1"]}], by="ui")
    assert env["ok"] and env["result"]["changed"] == ["parts"]
    p = env["result"]["project"]
    assert [x["ref"] for x in p["parts"]] == ["Q1"]
    assert [c["id"] for c in p["calcs"]] == ["npn-1"]  # the calculation stays
    assert events.of("project.updated")[-1]["changed"] == ["parts"]


def test_remove_parts_refusals(tmp_path, monkeypatch):
    _make("bench-q", tmp_path, monkeypatch)
    assert project.update("bench-q", 1, [{"op": "add_parts", "parts": [{"ref": "R1", "kind": "resistor", "value": "1k"}]}],
                          by="ui")["ok"]
    for bad in ([], None, "R1", [""], [7]):
        env = project.update("bench-q", 2, [{"op": "remove_parts", "refs": bad}], by="ui")
        assert env["error"]["code"] == "invalid_args", bad
    env = project.update("bench-q", 2, [{"op": "remove_parts", "refs": ["R1", "C9"]}], by="ui")
    assert env["error"]["code"] == "invalid_args" and "C9" in env["error"]["message"] and "R1" in env["error"]["hint"]
    assert project.get("bench-q")["result"]["project"]["parts"][0]["ref"] == "R1"  # nothing changed
    assert project.update("bench-q", 2, [{"op": "remove_parts", "refs": ["R1"], "extra": 1}], by="ui")["error"]["code"] == "invalid_args"

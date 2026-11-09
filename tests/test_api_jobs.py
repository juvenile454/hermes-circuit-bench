"""Job table (bench_core/jobs.py): job object, job.updated, limits, project records."""
import threading

import pytest

from circuit_bench.bench_core import contracts, jobs, project, runtime

JOB_KEYS = ["job_id", "kind", "state", "progress", "started", "finished", "log_tail", "result"]


class Emits:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, event, payload):
        with self.lock:
            self.calls.append((event, dict(payload)))

    def states(self, job_id):
        with self.lock:
            return [p["state"] for e, p in self.calls if e == "job.updated" and p["job_id"] == job_id]


def ok_build(ctx):
    ctx.log("Compiling .pio/build/s3/src/main.cpp.o")
    ctx.log("Linking .pio/build/s3/firmware.elf")
    return contracts.envelope("board.build", "Build ok.", {"ok": True, "ram_pct": 5.6, "flash_pct": 7.9,
                                                           "elf": "firmware.elf", "elf_sha256": "a" * 64})


def test_job_object_and_events_follow_the_contract():
    emits = Emits()
    table = jobs.JobTable(emit=emits)
    job = table.start("build", ok_build)
    assert list(job) == JOB_KEYS
    assert job["kind"] == "build" and job["state"] in ("queued", "running") and job["result"] is None
    assert job["job_id"].startswith("j-0001-")
    done = table.wait(job["job_id"], 5)
    assert done["state"] == "done" and done["progress"] == 1.0
    assert done["finished"] and done["started"]
    assert done["log_tail"] == ["Compiling .pio/build/s3/src/main.cpp.o", "Linking .pio/build/s3/firmware.elf"]
    assert done["result"]["action"] == "board.build" and done["result"]["ok"] is True
    assert emits.states(job["job_id"]) == ["running", "done"]
    payload = [p for e, p in emits.calls][-1]
    assert sorted(payload) == ["job_id", "kind", "progress", "state"]


def test_failed_result_and_exceptions_end_failed():
    emits = Emits()
    table = jobs.JobTable(emit=emits)

    def bad(ctx):
        return contracts.fail("board.flash", "elf_mismatch", "firmware changed")

    def boom(ctx):
        raise RuntimeError("secret /home/user/path")

    def bench_error(ctx):
        raise contracts.BenchError("timeout", "too slow", "retry")

    j1, j2, j3 = (table.start("flash", bad), table.start("detect", boom), table.start("build", bench_error))
    r1, r2, r3 = (table.wait(j["job_id"], 5) for j in (j1, j2, j3))
    assert r1["state"] == "failed" and r1["result"]["error"]["code"] == "elf_mismatch"
    assert r2["state"] == "failed" and r2["result"]["error"]["code"] == "tool_failed"
    assert "secret" not in r2["result"]["summary"] and r2["result"]["action"] == "board.detect"
    assert r3["result"]["error"] == {"code": "timeout", "message": "too slow", "hint": "retry"}
    for r in (r1, r2, r3):
        assert contracts.validate_envelope(r["result"]) == []
        assert emits.states(r["job_id"])[-1] == "failed"


def test_same_key_is_busy_until_the_job_ends():
    release = threading.Event()
    table = jobs.JobTable(emit=lambda *a: None)

    def slow(ctx):
        release.wait(5)
        return contracts.envelope("board.detect", "ok", {"port": "sim://x"})

    first = table.start("detect", slow, key="port:sim://x")
    with pytest.raises(contracts.BenchError) as e:
        table.start("flash", slow, key="port:sim://x")
    assert e.value.code == "port_busy" and first["job_id"] in e.value.message
    other = table.start("detect", slow, key="port:sim://y")  # another port is fine
    release.set()
    assert table.wait(first["job_id"], 5)["state"] == "done"
    assert table.wait(other["job_id"], 5)["state"] == "done"
    again = table.start("detect", slow, key="port:sim://x")
    assert table.wait(again["job_id"], 5)["state"] == "done"


def test_unknown_kind_and_unknown_id():
    table = jobs.JobTable(emit=lambda *a: None)
    with pytest.raises(contracts.BenchError) as e:
        table.start("erase", ok_build)
    assert e.value.code == "invalid_args"
    assert table.get("j-0001") is None and table.wait("nope") is None and table.is_simulated("nope") is None


def test_ids_of_another_process_are_unknown():
    a, b = jobs.JobTable(emit=lambda *x: None), jobs.JobTable(emit=lambda *x: None)
    ja = a.start("build", ok_build)
    jb = b.start("build", ok_build)
    assert ja["job_id"][:6] == jb["job_id"][:6] == "j-0001"
    assert ja["job_id"] != jb["job_id"] and b.get(ja["job_id"]) is None


def test_at_most_20_jobs_finished_ones_go_first():
    table = jobs.JobTable(emit=lambda *a: None)
    release = threading.Event()

    def slow(ctx):
        release.wait(5)
        return contracts.envelope("board.build", "ok", {"ok": True})

    running = table.start("build", slow)
    ids = [table.start("build", ok_build)["job_id"] for _ in range(25)]
    for job_id in ids[-19:]:
        table.wait(job_id, 5)
    assert len(table.list()) == jobs.MAX_JOBS
    assert table.get(running["job_id"]) is not None  # still running: kept
    assert table.get(ids[0]) is None
    release.set()
    assert table.wait_all(5)


def test_flash_progress_from_esptool_lines():
    emits = Emits()
    table = jobs.JobTable(emit=emits)
    seen = []
    step = threading.Event()

    def flash(ctx):
        ctx.log("Writing at 0x00000000 [==========] 100.0%")  # bootloader: below the app, no progress
        ctx.log("Writing at 0x0000e000... (100 %)")
        seen.append(table.get(ctx.job_id)["progress"])
        ctx.log("Writing at 0x00010000 [=====>     ] 52.3%")
        seen.append(table.get(ctx.job_id)["progress"])
        ctx.log("Writing at 0x00020000... (75 %)")
        seen.append(table.get(ctx.job_id)["progress"])
        ctx.log("x" * 500)
        step.set()
        return contracts.envelope("board.flash", "ok", {"ok": True})

    job = table.start("flash", flash, simulated=True)
    done = table.wait(job["job_id"], 5)
    assert seen == [None, 0.523, 0.75]
    assert max(len(line) for line in done["log_tail"]) == jobs.LOG_LINE_CHARS
    assert table.is_simulated(job["job_id"]) is True
    assert "running" in emits.states(job["job_id"])


def test_table_is_process_wide():
    assert jobs.table() is jobs.table() is runtime.get("jobs", dict)


def test_summary_sentences():
    assert jobs.summary({"kind": "build", "state": "running", "progress": 0.42, "job_id": "j"}) == "Build running (42 %)."
    assert jobs.summary({"kind": "flash", "state": "queued", "progress": None, "job_id": "j-1"}) == "Flash queued (job j-1)."
    assert jobs.summary({"kind": "build", "state": "done", "result": {"summary": "Build ok."}}) == "Build done: Build ok."


# --------------------------------------------------------------------------------------------- record()

@pytest.fixture
def proj():
    env = project.create("rec-a", "Record", "esp32s3", "n16r8")
    assert env["ok"], env
    return "rec-a"


def detect_env(port="sim://test-s3", mac="aa:bb:cc:dd:ee:ff"):
    return contracts.envelope("board.detect", "ok", {"port": port, "mac": mac, "chip": "ESP32-S3", "features": ["Wi-Fi"],
                                                     "flash_size": "16MB", "chip_id": "esp32s3", "log_tail": ["x"],
                                                     "reset_happened": True}, simulated=True)


def test_record_detect_build_flash(proj):
    assert jobs.record("detect", proj, detect_env()) is None
    p = project.get(proj)["result"]["project"]
    assert p["board"]["detected"]["mac"] == "aa:bb:cc:dd:ee:ff" and p["board"]["detected"]["simulated"] is True
    assert "chip_id" not in p["board"]["detected"]
    build = contracts.envelope("board.build", "ok", {"ok": True, "ram_pct": 5.6, "flash_pct": 7.9, "elf": "fw.elf",
                                                     "elf_sha256": "b" * 64, "log_ref": "build-20261106-213852.log"})
    assert jobs.record("build", proj, build) is None
    assert project.get(proj)["result"]["project"]["firmware"]["last_build"]["elf_sha256"] == "b" * 64
    flash = contracts.envelope("board.flash", "ok", {"ok": True, "port": "sim://test-s3", "elf_sha256": "b" * 64})
    assert jobs.record("flash", proj, flash, mac="aa:bb:cc:dd:ee:ff") is None
    last = project.get(proj)["result"]["project"]["firmware"]["last_flash"]
    assert last["ok"] is True and last["mac"] == "aa:bb:cc:dd:ee:ff" and last["port"] == "sim://test-s3"


def test_record_failures(proj):
    rev = project.get(proj)["result"]["rev"]
    assert jobs.record("detect", proj, contracts.fail("board.detect", "timeout", "slow")) is None
    assert project.get(proj)["result"]["rev"] == rev  # a failed detection stores nothing
    jobs.record("build", proj, contracts.envelope("board.build", "ok", {"ok": True, "elf_sha256": "c" * 64}))
    jobs.record("build", proj, contracts.fail("board.build", "tool_failed", "compile error"))
    last = project.get(proj)["result"]["project"]["firmware"]["last_build"]
    assert last["ok"] is False and last["elf_sha256"] is None  # no stale approved hash after a failed build
    jobs.record("flash", proj, contracts.fail("board.flash", "timeout", "upload too slow"), port="sim://test-s3")
    assert project.get(proj)["result"]["project"]["firmware"]["last_flash"]["ok"] is False


def test_record_warns_instead_of_raising():
    w = jobs.record("detect", "missing-project", detect_env())
    assert w["code"] == "project_not_updated" and w["severity"] == "caution" and "missing-project" in w["message"]


def test_record_retries_on_conflict(proj, monkeypatch):
    real = project.update
    calls = []

    def racing(pid, rev, ops, *, by, trusted=False):
        calls.append(rev)
        if len(calls) == 1:  # somebody else writes first
            real(pid, rev, [{"op": "note", "text": "concurrent"}], by="agent")
        return real(pid, rev, ops, by=by, trusted=trusted)

    monkeypatch.setattr(project, "update", racing)
    assert jobs.record("detect", proj, detect_env()) is None
    assert len(calls) == 2 and calls[1] == calls[0] + 1

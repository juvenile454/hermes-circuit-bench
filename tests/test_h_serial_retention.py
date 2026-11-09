"""Retention of the artifacts folder. Per prefix the newest 200 files stay, pruning starts at 220;
files a project points to in debug.last_panic.log_ref stay; symlinks and other kinds are not touched."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import serialport, storage

BASE_NS = 1_700_000_000 * 10**9


def _make(folder: Path, names: list[str]) -> None:
    """Files with strictly increasing mtimes (the first name is the oldest)."""
    for i, name in enumerate(names):
        path = folder / name
        path.write_text("synthetic\n", encoding="utf-8")
        os.utime(path, ns=(BASE_NS + i * 10**9, BASE_NS + i * 10**9))


def _names(n: int, kind: str = "panic", ext: str = "log") -> list[str]:
    return [f"{kind}-20261101-{i // 60:04d}{i % 60:02d}.{ext}" for i in range(n)]


def _count(folder: Path, prefix: str) -> int:
    return sum(1 for p in folder.iterdir() if p.name.startswith(prefix + "-") and p.is_file() and not p.is_symlink())


def _project(pid: str, log_ref: str | None, text: str | None = None) -> None:
    pdir = storage.data_dir() / "projects" / pid
    pdir.mkdir(parents=True, exist_ok=True)
    body = text if text is not None else json.dumps({"schema": 1, "id": pid,
                                                     "debug": {"last_panic": {"log_ref": log_ref} if log_ref else None}})
    (pdir / "project.json").write_text(body, encoding="utf-8")


def test_230_panic_files_leave_200_and_keep_the_referenced_and_other_kinds(tmp_path):
    folder = serialport.artifacts_dir()
    old = _names(229)
    _make(folder, old)
    _make(folder, [f"build-20261101-0000{i:02d}.log" for i in range(5)])
    outside = tmp_path / "outside.log"
    outside.write_text("not an artifact\n", encoding="utf-8")
    link = folder / "panic-20261031-235959.log"
    link.symlink_to(outside)
    os.utime(link, ns=(BASE_NS - 10**9, BASE_NS - 10**9), follow_symlinks=False)
    _project("keeper", old[0])  # the oldest panic file is referenced
    _project("other", None)
    _project("broken", None, text="{not json")  # unreadable projects are skipped
    (storage.data_dir() / "projects" / "empty").mkdir()  # a folder without project.json
    ref = serialport.write_artifact("panic", ["Guru Meditation Error: Core  1 panic'ed (StoreProhibited)."])
    names = {p.name for p in folder.iterdir()}
    assert _count(folder, "panic") == 200
    assert ref in names and old[0] in names
    # the 30 oldest unreferenced files went: old[1..30]; old[31..] and the new one stay
    assert not any(n in names for n in old[1:31]) and all(n in names for n in old[31:])
    assert _count(folder, "build") == 5
    assert link.is_symlink() and outside.read_text(encoding="utf-8") == "not an artifact\n"


def test_pruning_starts_at_220():
    folder = serialport.artifacts_dir()
    _make(folder, _names(218))
    serialport.write_artifact("panic", ["x"])
    assert _count(folder, "panic") == 219  # below the limit: nothing pruned
    serialport.write_artifact("panic", ["x"])
    assert _count(folder, "panic") == 200


def test_every_prefix_is_counted_on_its_own():
    folder = serialport.artifacts_dir()
    _make(folder, _names(225, kind="schematic", ext="svg") + _names(150, kind="monitor"))
    serialport.write_artifact("panic", ["x"])
    assert _count(folder, "schematic") == 200 and _count(folder, "monitor") == 150 and _count(folder, "panic") == 1


def test_open_artifact_prunes_and_never_the_new_file():
    folder = serialport.artifacts_dir()
    names = _names(230, kind="flash")
    _make(folder, names)
    future = BASE_NS + 10**12  # older stamps than the existing files cannot remove the new one either
    for n in names:
        os.utime(folder / n, ns=(future, future))
    ref, f = serialport.open_artifact("flash")
    with f:
        f.write("esptool output\n")
    assert (folder / ref).is_file() and _count(folder, "flash") == 200


def test_cleanup_errors_are_logged_not_raised(monkeypatch, caplog):
    folder = serialport.artifacts_dir()
    _make(folder, _names(225))

    def refuse(*a, **k):
        raise PermissionError("read-only folder (test)")

    monkeypatch.setattr(os, "unlink", refuse)  # Path.unlink goes through os.unlink as well
    with caplog.at_level(logging.WARNING, logger=serialport.logger.name):
        ref = serialport.write_artifact("panic", ["x"])
    assert (folder / ref).is_file() and _count(folder, "panic") == 226
    assert any("artifact" in r.getMessage() and "read-only" in r.getMessage() for r in caplog.records)


def test_broker_panic_artifacts_are_pruned_too():
    folder = serialport.artifacts_dir()
    _make(folder, _names(219))
    import board_fixtures as bf
    from circuit_bench.bench_core import board
    lines = (Path(__file__).resolve().parent / "fixtures" / "crash" / "xtensa_store_prohibited.log").read_text(
        encoding="utf-8").splitlines()
    board.register_provider("sim://", bf.TestProvider(lines=[*lines, "ESP-ROM:esp32s3-20210327", "end"]))
    serialport.open_port("sim://test-s3")
    assert bf.wait_for(lambda: serialport.tail("sim://test-s3")["panic"] is not None, timeout=15)
    ref = serialport.tail("sim://test-s3")["panic"]["log_ref"]
    assert (folder / ref).is_file() and _count(folder, "panic") == 200

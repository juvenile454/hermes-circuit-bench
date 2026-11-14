"""board.flash writes from a private copy of the image set: the copies are checked and handed to esptool, so a
file swapped in the build folder after the copy is never written. The fake pio/esptool and a pty port stand in
for PlatformIO, esptool and the board (nothing reaches a real device)."""
from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import stat
import threading
import time
from pathlib import Path

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, clitools, contracts, serialport, storage

BUILD_NAMES = ("bootloader.bin", "partitions.bin", "firmware.bin")


@pytest.fixture
def fw(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


@pytest.fixture
def port(hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    return pty_port.name


def _build(fake_tools, fw):
    fake_tools.scenario("board-pio-flash-ok.json")
    env = board.build(fw, "s3")
    assert env["ok"], env["error"]
    return env["result"]


def _sources(fw: Path) -> dict[str, Path]:
    out = {n: fw / ".pio" / "build" / "s3" / n for n in BUILD_NAMES}
    out["boot_app0.bin"] = fw / ".pio" / "fake-framework" / "boot_app0.bin"
    return out


def _root() -> Path:
    return storage.data_dir() / "tmp"


def _leftovers() -> list[str]:
    root = _root()
    return sorted(p.name for p in root.iterdir() if p.name.startswith("flash-")) if root.is_dir() else []


def _flash(fw, port, r, **kw):
    kw.setdefault("expected_images", r["images"])
    return board.flash(fw, "s3", port, expected_elf_sha256=r["elf_sha256"], guard=lambda: None, **kw)


def _image_args(argv: list[str]) -> list[str]:
    """The image paths of an esptool call (image-info: the last argument; write-flash: every second one)."""
    if "image-info" in argv:
        return [argv[-1]]
    i = argv.index("detect") + 1
    return argv[i + 1::2]


class Spy:
    """Wraps clitools.run: records what esptool would read from each image path at the time it runs, the mode of
    the folder and the files, and lets a test act just before the write."""

    def __init__(self, monkeypatch, before_write=None, before_info=None):
        self.real = clitools.run
        self.reads: dict[str, bytes] = {}
        self.modes: dict[str, int] = {}
        self.mtimes: dict[str, int] = {}
        self.dirs: set[str] = set()
        self.argv: list[list[str]] = []
        self.before_write = before_write
        self.before_info = before_info
        monkeypatch.setattr(clitools, "run", self)

    def __call__(self, argv, **kw):
        argv = [str(a) for a in argv]
        if any(a in ("write-flash", "image-info") for a in argv):
            hook = self.before_write if "write-flash" in argv else self.before_info
            if hook is not None:
                hook()
            self.argv.append(argv)
            for p in _image_args(argv):
                self.reads[p] = Path(p).read_bytes()
                self.modes[p] = stat.S_IMODE(os.stat(p).st_mode)
                self.mtimes[p] = os.stat(p).st_mtime_ns
                self.dirs.add(str(Path(p).parent))
        return self.real(argv, **kw)


def _swap(paths) -> None:
    for p in paths:
        p.write_bytes(b"SWAPPED " + p.name.encode() + b"\n")


def test_esptool_gets_only_paths_in_the_snapshot(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == [] and env["ok"], env["error"]
    root = _root().resolve()
    info, write = [c["argv"] for c in fake_tools.calls("esptool")]
    for p in _image_args(info) + _image_args(write):
        assert Path(p).parent.parent == root and Path(p).parent.name.startswith("flash-"), p
    assert [Path(p).name for p in _image_args(write)] == ["bootloader.bin", "partitions.bin", "boot_app0.bin",
                                                          "firmware.bin"]
    assert Path(_image_args(info)[0]).name == "firmware.bin"
    assert not any(str(fw.resolve()) in a for c in fake_tools.calls("esptool") for a in c["argv"])
    for p, data in spy.reads.items():
        assert data == src[Path(p).name].read_bytes(), p
    # result.images: same form as before (offset, original name, SHA-256 of the written content); result.elf the ELF
    images = env["result"]["images"]
    assert [sorted(i) for i in images] == [["name", "offset", "sha256"]] * 4
    assert [(i["offset"], i["name"]) for i in images] == [("0x0000", "bootloader.bin"), ("0x8000", "partitions.bin"),
                                                          ("0xe000", "boot_app0.bin"), ("0x10000", "firmware.bin")]
    assert {i["name"]: i["sha256"] for i in images} == {n: board.sha256_file(p) for n, p in src.items()}
    assert env["result"]["elf"] == str(fw.resolve() / ".pio" / "build" / "s3" / "firmware.elf")
    assert _leftovers() == []


def test_swap_after_the_snapshot_writes_the_approved_content(fake_tools, fw, port, monkeypatch):
    """Swapped while the images are being checked (after the copy): the checks and esptool still see the approved
    bytes, the swapped files in the build folder are never read."""
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    real_hash = board.sha256_file
    swapped: list[bool] = []

    def hash_then_swap(path):
        if Path(path).suffix == ".bin" and not swapped:
            swapped.append(True)
            _swap(src.values())
        return real_hash(path)

    monkeypatch.setattr(board, "sha256_file", hash_then_swap)
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    assert swapped and env["ok"], env["error"]
    assert all(p.read_bytes().startswith(b"SWAPPED") for p in src.values())
    written = {Path(p).name: data for p, data in spy.reads.items() if p in _image_args(spy.argv[-1])}
    assert written == approved
    assert {i["name"]: i["sha256"] for i in env["result"]["images"]} == {
        n: hashlib.sha256(data).hexdigest() for n, data in approved.items()}


def test_swap_just_before_the_write_does_not_reach_esptool(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    spy = Spy(monkeypatch, before_info=lambda: _swap(src.values()), before_write=lambda: _swap(src.values()))
    env = _flash(fw, port, r)
    assert env["ok"], env["error"]
    assert len(spy.reads) == 4  # image-info and write-flash read the same four copies
    assert all(data == approved[Path(p).name] for p, data in spy.reads.items())


@pytest.mark.parametrize("name", BUILD_NAMES)
def test_swap_before_the_snapshot_is_elf_mismatch(fake_tools, fw, port, name):
    r = _build(fake_tools, fw)
    _swap([_sources(fw)[name]])
    env = _flash(fw, port, r)
    assert env["ok"] is False and env["error"]["code"] == "elf_mismatch" and name in env["error"]["message"]
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls("esptool"))
    assert _leftovers() == []


def test_snapshot_keeps_modes_and_mtimes(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    for p in src.values():
        p.chmod(0o644)
    spy = Spy(monkeypatch)
    assert _flash(fw, port, r)["ok"]
    (folder,) = spy.dirs
    assert spy.modes and all(m == 0o600 for m in spy.modes.values()), spy.modes
    for p, mtime in spy.mtimes.items():
        assert mtime == src[Path(p).name].stat().st_mtime_ns, p
    assert not Path(folder).exists()


def test_snapshot_folder_mode_is_0700(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    seen: list[int] = []

    def look():
        (folder,) = [p for p in _root().iterdir() if p.name.startswith("flash-")]
        seen.append(stat.S_IMODE(folder.stat().st_mode))

    Spy(monkeypatch, before_write=look)
    assert _flash(fw, port, r)["ok"]
    assert seen == [0o700]


def test_age_check_without_recorded_images_uses_the_copied_mtime(fake_tools, fw, port):
    """Projects built before image hashes were recorded: firmware.bin older than the ELF stays elf_mismatch."""
    r = _build(fake_tools, fw)
    image = _sources(fw)["firmware.bin"]
    old = image.stat().st_mtime_ns - 10_000_000_000
    os.utime(image, ns=(old, old))
    env = _flash(fw, port, r, expected_images=None)
    assert env["error"]["code"] == "elf_mismatch" and "older than" in env["error"]["message"]
    assert _leftovers() == []
    new = time.time_ns()
    os.utime(image, ns=(new, new))
    assert _flash(fw, port, r, expected_images=None)["ok"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files without read permission")
def test_unreadable_image_is_tool_failed_before_any_port_access(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    paused: list[str] = []
    real_pause = serialport.pause
    monkeypatch.setattr(serialport, "pause", lambda p: paused.append(p) or real_pause(p))
    monkeypatch.setattr(serialport, "check_port_free", lambda p: paused.append(f"free {p}"))
    target = _sources(fw)["partitions.bin"]
    target.chmod(0)
    try:
        env = _flash(fw, port, r)
    finally:
        target.chmod(0o644)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert "partitions.bin" in env["error"]["message"]
    assert fake_tools.calls("esptool") == [] and paused == []
    assert _leftovers() == []


def test_snapshot_folder_that_cannot_be_created_is_tool_failed(fake_tools, fw, port):
    r = _build(fake_tools, fw)
    storage.data_dir().joinpath("tmp").write_text("not a folder\n", encoding="utf-8")
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert fake_tools.calls("esptool") == []


@pytest.mark.parametrize("name, code", [("firmware.bin", "elf_missing"), ("partitions.bin", "elf_mismatch"),
                                        ("bootloader.bin", "elf_mismatch"), ("boot_app0.bin", "elf_missing")])
def test_missing_image_keeps_its_error_code(fake_tools, fw, port, name, code):
    r = _build(fake_tools, fw)
    src = _sources(fw)[name]
    src.unlink()
    env = _flash(fw, port, r)
    assert env["ok"] is False and env["error"]["code"] == code and name in env["error"]["message"], env["error"]
    if name == "boot_app0.bin":
        assert str(src) in env["error"]["message"]  # names the file the build points to, not a copy
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls("esptool"))
    assert _leftovers() == []


@pytest.mark.parametrize("outcome", ["success", "refusal", "tool_error", "exception", "timeout"])
def test_snapshot_is_removed_on_every_exit(fake_tools, fw, port, monkeypatch, outcome):
    r = _build(fake_tools, fw)
    expected = dict(r["images"])
    timeout = board.FLASH_TIMEOUT_S
    created: list[Path] = []
    real_hash = board.sha256_file

    def note(path):
        if Path(path).suffix == ".bin":
            created.append(Path(path).parent)
        return real_hash(path)

    monkeypatch.setattr(board, "sha256_file", note)
    if outcome == "refusal":
        expected["partitions.bin"] = "0" * 64
    elif outcome == "tool_error":
        fake_tools.scenario("board-pio-flash-ok.json", **{"write-flash": {"rc": 2, "sleep": 0,
                                                                          "stdout": "A fatal error occurred: x\n"}})
    elif outcome == "timeout":
        fake_tools.scenario("board-pio-flash-ok.json", **{"write-flash": {"sleep": 5}})
        timeout = 0.5

    def boom():
        raise RuntimeError("interrupted")

    Spy(monkeypatch, before_write=boom if outcome == "exception" else None)
    if outcome == "exception":
        with pytest.raises(RuntimeError):
            _flash(fw, port, r, expected_images=expected, timeout=timeout)
    else:
        env = _flash(fw, port, r, expected_images=expected, timeout=timeout)
        want = {"success": None, "refusal": "elf_mismatch", "tool_error": None, "timeout": "timeout"}[outcome]
        if outcome == "success":
            assert env["ok"], env["error"]
        elif want:
            assert env["error"]["code"] == want, env["error"]
        else:
            assert env["ok"] is False
    snaps = {p for p in created if p.name.startswith("flash-")}
    assert snaps, "no image was read from a snapshot"
    assert all(not p.exists() for p in snaps) and _leftovers() == []


def test_leftovers_older_than_an_hour_are_removed_by_the_next_flash(fake_tools, fw, port):
    r = _build(fake_tools, fw)
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for name, age in (("flash-old", 2 * 3600), ("flash-young", 10 * 60), ("other-old", 2 * 3600)):
        d = root / name
        d.mkdir()
        (d / "firmware.bin").write_bytes(b"left over\n")
        os.utime(d / "firmware.bin", (now - age, now - age))
        os.utime(d, (now - age, now - age))
    assert _flash(fw, port, r)["ok"]
    assert not (root / "flash-old").exists()
    assert (root / "flash-young" / "firmware.bin").is_file() and (root / "other-old").is_dir()
    assert _leftovers() == ["flash-young"]



# ------------------------------------------------------------------ swaps after the snapshot (symlinks, folders)

def _after_snapshot(monkeypatch, action) -> None:
    """Run ``action`` right after the private copies were made (before the checks, image-info and the write)."""
    real = board._snapshot

    def snap(files):
        out = real(files)
        action()
        return out

    monkeypatch.setattr(board, "_snapshot", snap)


def _in_snapshot(path: str) -> bool:
    root = str(_root().resolve())
    parts = Path(path).relative_to(root).parts if path.startswith(root + os.sep) else ()
    return bool(parts) and parts[0].startswith("flash-") and len(parts) in (2, 3)


def _no_port_access(monkeypatch) -> list[str]:
    touched: list[str] = []
    real_pause = serialport.pause
    monkeypatch.setattr(serialport, "pause", lambda p: touched.append(p) or real_pause(p))
    monkeypatch.setattr(serialport, "check_port_free", lambda p: touched.append(f"free {p}"))
    return touched


def _assert_wrote_approved(env, spy, fake_tools, approved) -> None:
    """The flash went through, esptool got only snapshot paths and every image it read holds the approved bytes."""
    assert env["ok"], env["error"]
    calls = [c["argv"] for c in fake_tools.calls("esptool")]
    assert calls and all(_in_snapshot(p) for c in calls for p in _image_args(c)), calls
    written = {Path(p).name: spy.reads[p] for p in _image_args(spy.argv[-1])}
    assert written == approved
    assert {i["name"]: i["sha256"] for i in env["result"]["images"]} == {
        n: hashlib.sha256(d).hexdigest() for n, d in approved.items()}
    assert _leftovers() == []


def _evil(path: Path) -> None:
    path.write_bytes(b"EVIL " + path.name.encode() + b"\n")


def _evil_tree(folder: Path) -> None:
    for p in folder.rglob("*.bin"):
        if p.is_file() and not p.is_symlink():
            _evil(p)


def test_build_images_turned_into_symlinks_to_approved_copies_that_change_later(fake_tools, fw, port, monkeypatch,
                                                                                tmp_path):
    """After the copy each build image becomes a symlink to an identical file elsewhere; that file turns evil just
    before the write. esptool reads only the snapshot."""
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    side = tmp_path / "side"
    side.mkdir()

    def to_symlinks():
        for n in BUILD_NAMES:
            (side / n).write_bytes(approved[n])
            src[n].unlink()
            src[n].symlink_to(side / n)

    _after_snapshot(monkeypatch, to_symlinks)
    spy = Spy(monkeypatch, before_write=lambda: [_evil(side / n) for n in BUILD_NAMES])
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


def test_build_folder_moved_behind_a_symlink_that_changes_later(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    build = fw / ".pio" / "build" / "s3"

    def move():
        real = build.with_name("s3.real")
        build.rename(real)
        build.symlink_to(real)

    _after_snapshot(monkeypatch, move)
    spy = Spy(monkeypatch, before_write=lambda: [_evil(build / n) for n in BUILD_NAMES])
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


def test_build_image_replaced_by_a_symlink_to_another_file(fake_tools, fw, port, monkeypatch, tmp_path):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    other = tmp_path / "other.bin"
    other.write_bytes(b"OTHER IMAGE\n")

    def swap():
        for n in BUILD_NAMES:
            src[n].unlink()
            src[n].symlink_to(other)

    _after_snapshot(monkeypatch, swap)
    spy = Spy(monkeypatch)
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


def test_build_folder_replaced_by_a_symlink_to_other_images(fake_tools, fw, port, monkeypatch, tmp_path):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    build = fw / ".pio" / "build" / "s3"
    other = tmp_path / "other-build"

    def swap():
        shutil.copytree(build, other)
        _evil_tree(other)
        build.rename(build.with_name("s3.approved"))
        build.symlink_to(other)

    _after_snapshot(monkeypatch, swap)
    spy = Spy(monkeypatch)
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


@pytest.mark.parametrize("level", ["fw", "fw/.pio", "fw/.pio/build"])
def test_folder_higher_up_in_the_path_swapped(fake_tools, fw, port, monkeypatch, tmp_path, level):
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    folder = tmp_path / level
    other = tmp_path / "other-tree"

    def swap():
        shutil.copytree(folder, other, symlinks=True)
        _evil_tree(other)
        folder.rename(folder.with_name(folder.name + ".approved"))
        folder.symlink_to(other)

    _after_snapshot(monkeypatch, swap)
    spy = Spy(monkeypatch)
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


@pytest.mark.parametrize("how", ["file_symlink", "folder_symlink", "file_rewritten"])
def test_framework_boot_app0_swapped_after_the_snapshot(fake_tools, fw, port, monkeypatch, tmp_path, how):
    """boot_app0.bin is not in last_build.images; its copy is what gets written, whatever happens to the original."""
    r = _build(fake_tools, fw)
    src = _sources(fw)
    approved = {n: p.read_bytes() for n, p in src.items()}
    boot = src["boot_app0.bin"]
    other = tmp_path / "other-framework"
    other.mkdir()
    _evil(other / "boot_app0.bin")

    def swap():
        if how == "file_symlink":
            boot.unlink()
            boot.symlink_to(other / "boot_app0.bin")
        elif how == "folder_symlink":
            boot.parent.rename(boot.parent.with_name("fake-framework.approved"))
            boot.parent.symlink_to(other)
        else:
            _evil(boot)

    _after_snapshot(monkeypatch, swap)
    spy = Spy(monkeypatch)
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


@pytest.mark.parametrize("name", [*BUILD_NAMES, "boot_app0.bin"])
def test_file_of_the_write_list_missing_from_the_snapshot_is_tool_failed(fake_tools, fw, port, monkeypatch, name):
    """No fallback to the original: a file of the write list without a copy stops the flash before any port use."""
    r = _build(fake_tools, fw)
    real = board._snapshot

    def drop(files):
        folder, copies = real(files)
        return folder, {k: v for k, v in copies.items() if Path(k).name != name}

    monkeypatch.setattr(board, "_snapshot", drop)
    touched = _no_port_access(monkeypatch)
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


@pytest.mark.parametrize("where", ["build_folder", "elsewhere"])
def test_foreign_path_in_the_write_list_never_reaches_esptool(fake_tools, fw, port, monkeypatch, tmp_path, where):
    r = _build(fake_tools, fw)
    real = board._write_list
    foreign = _sources(fw)["partitions.bin"] if where == "build_folder" else tmp_path / "partitions.bin"
    foreign.write_bytes(foreign.read_bytes() if foreign.exists() else b"FOREIGN\n")

    def sneak(*a, **kw):
        pairs, described = real(*a, **kw)
        return [(o, foreign if Path(p).name == "partitions.bin" else p) for o, p in pairs], described

    monkeypatch.setattr(board, "_write_list", sneak)
    touched = _no_port_access(monkeypatch)
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


def _with_extra_images(fake_tools, extra: list[tuple[str, str]]) -> None:
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    images = data["metadata"]["json"]["{env}"]["extra"]["flash_images"]
    images += [{"offset": o, "path": "{project_dir}/" + rel} for o, rel in extra]
    fake_tools.scenario(data)


def test_name_clash_in_the_snapshot_is_tool_failed(fake_tools, fw, port, monkeypatch):
    """A second file of the same name goes into a numbered subfolder; when a copied file already has that number as
    its name, the flash stops with tool_failed (no raw exception) and the folder is gone."""
    r = _build(fake_tools, fw)
    for rel in (".pio/other/4", ".pio/other/bootloader.bin"):
        (fw / rel).parent.mkdir(parents=True, exist_ok=True)
        (fw / rel).write_bytes(b"EXTRA " + rel.encode() + b"\n")
    # write list: bootloader, partitions, boot_app0, other/4 (copied as "4"), other/bootloader.bin (index 4: the
    # subfolder "4" clashes with the copied file "4"), firmware.bin
    _with_extra_images(fake_tools, [("0x200000", ".pio/other/4"), ("0x300000", ".pio/other/bootloader.bin")])
    touched = _no_port_access(monkeypatch)
    made: list[Path] = []
    real_mkdtemp = board.tempfile.mkdtemp

    def note(*a, **kw):
        out = real_mkdtemp(*a, **kw)
        made.append(Path(out))
        return out

    monkeypatch.setattr(board.tempfile, "mkdtemp", note)
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert made and not any(p.exists() for p in made) and _leftovers() == []


def test_same_name_from_another_folder_gets_its_own_copy(fake_tools, fw, port, monkeypatch):
    """Two files of the write list with the same name (one without a recorded hash) get separate copies."""
    r = _build(fake_tools, fw)
    extra = fw / ".pio" / "other" / "boot_app0.bin"
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b"SECOND BOOT APP0\n")
    _with_extra_images(fake_tools, [("0x300000", ".pio/other/boot_app0.bin")])
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    assert env["ok"], env["error"]
    paths = _image_args(spy.argv[-1])
    assert all(_in_snapshot(p) for p in paths), paths
    by_offset = dict(zip(spy.argv[-1][spy.argv[-1].index("detect") + 1::2], paths, strict=True))
    assert spy.reads[by_offset["0x300000"]] == b"SECOND BOOT APP0\n"
    assert spy.reads[by_offset["0xe000"]] == _sources(fw)["boot_app0.bin"].read_bytes()
    hashes = [(i["offset"], i["sha256"]) for i in env["result"]["images"]]
    assert ("0x300000", hashlib.sha256(b"SECOND BOOT APP0\n").hexdigest()) in hashes


def test_result_images_name_the_hash_of_the_written_copy(fake_tools, fw, port):
    """result.images: the SHA-256 of the bytes handed to esptool, also for a build-folder image whose recorded hash
    the checks do not look at (a name that is not one of the build's own images)."""
    r = _build(fake_tools, fw)
    extra = fw / ".pio" / "build" / "s3" / "extra.bin"
    extra.write_bytes(b"EXTRA IMAGE\n")
    _with_extra_images(fake_tools, [("0x300000", ".pio/build/{env}/extra.bin")])
    expected = {**r["images"], "extra.bin": "0" * 64}
    env = _flash(fw, port, r, expected_images=expected)
    assert env["ok"], env["error"]
    got = {i["name"]: i["sha256"] for i in env["result"]["images"]}
    assert got["extra.bin"] == hashlib.sha256(b"EXTRA IMAGE\n").hexdigest()
    assert {n: got[n] for n in _sources(fw)} == {n: board.sha256_file(p) for n, p in _sources(fw).items()}


# ------------------------------------------------------------------ the checked file is the copy that is written

def _edit_flash_images(fake_tools, edit) -> None:
    """Rewrite extra.flash_images of the fake pio metadata (``edit``: list of {offset, path} -> new list)."""
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    extra = data["metadata"]["json"]["{env}"]["extra"]
    extra["flash_images"] = edit(extra["flash_images"])
    fake_tools.scenario(data)


def _via_alias(fake_tools, fw) -> Path:
    """The write list names the build images through a symlink to the build folder; prog_path keeps the real one."""
    alias = fw / ".pio" / "alias"
    alias.symlink_to(fw / ".pio" / "build" / "s3")
    _edit_flash_images(fake_tools, lambda items: [
        dict(i, path=i["path"].replace("/.pio/build/{env}/", "/.pio/alias/")) for i in items])
    return alias


def _swapped_only_for_the_snapshot(monkeypatch, path: Path) -> bytes:
    """``path`` holds other bytes while the copies are made and its approved bytes again right after."""
    approved = path.read_bytes()
    real = board._snapshot

    def snap(files):
        _evil(path)
        try:
            return real(files)
        finally:
            path.write_bytes(approved)

    monkeypatch.setattr(board, "_snapshot", snap)
    return approved


@pytest.mark.parametrize("name", ["bootloader.bin", "partitions.bin"])
def test_image_named_through_an_alias_folder_is_checked_at_its_copy(fake_tools, fw, port, monkeypatch, name):
    """Swapped while the copies are made and swapped back right after: the copy (what would be written) is checked,
    not the original in the build folder."""
    r = _build(fake_tools, fw)
    _via_alias(fake_tools, fw)
    _swapped_only_for_the_snapshot(monkeypatch, _sources(fw)[name])
    touched = _no_port_access(monkeypatch)
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "elf_mismatch", env["error"]
    assert name in env["error"]["message"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


def test_alias_folder_without_a_swap_writes_the_approved_images(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    _via_alias(fake_tools, fw)
    approved = {n: p.read_bytes() for n, p in _sources(fw).items()}
    spy = Spy(monkeypatch)
    _assert_wrote_approved(_flash(fw, port, r), spy, fake_tools, approved)


@pytest.mark.parametrize("same", [False, True], ids=["other_content", "same_content"])
@pytest.mark.parametrize("name", ["bootloader.bin", "partitions.bin", "Bootloader.BIN"])
def test_approved_name_from_another_folder_must_match_too(fake_tools, fw, port, monkeypatch, name, same):
    """Every file of the write list with an approved name (any case) must hold the approved bytes."""
    r = _build(fake_tools, fw)
    extra = fw / ".pio" / "other" / name
    extra.parent.mkdir(parents=True)
    extra.write_bytes(_sources(fw)[name.lower()].read_bytes() if same else b"FOREIGN " + name.encode() + b"\n")
    _with_extra_images(fake_tools, [("0x300000", ".pio/other/" + name)])
    touched = _no_port_access(monkeypatch)
    env = _flash(fw, port, r)
    if same:
        assert env["ok"], env["error"]
    else:
        assert env["ok"] is False and env["error"]["code"] == "elf_mismatch", env["error"]
        assert str(extra) in env["error"]["message"]
        assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


@pytest.mark.parametrize("changed", [False, True], ids=["unchanged", "changed"])
def test_approved_image_that_is_not_written_is_checked_in_place(fake_tools, fw, port, monkeypatch, changed):
    r = _build(fake_tools, fw)
    _edit_flash_images(fake_tools, lambda items: [i for i in items if not i["path"].endswith("/partitions.bin")])
    if changed:
        _evil(_sources(fw)["partitions.bin"])
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    if changed:
        assert env["ok"] is False and env["error"]["code"] == "elf_mismatch", env["error"]
        assert "partitions.bin" in env["error"]["message"] and fake_tools.calls("esptool") == []
    else:
        assert env["ok"], env["error"]
        assert [Path(p).name for p in _image_args(spy.argv[-1])] == ["bootloader.bin", "boot_app0.bin", "firmware.bin"]
    assert _leftovers() == []


def test_boot_app0_has_no_recorded_hash_and_is_written_as_copied(fake_tools, fw, port, monkeypatch):
    """boot_app0.bin comes from the framework package and has no recorded hash: the bytes it held when the copies
    were made are written, and result.images names their hash."""
    r = _build(fake_tools, fw)
    boot = _sources(fw)["boot_app0.bin"]
    _swapped_only_for_the_snapshot(monkeypatch, boot)
    copied = b"EVIL boot_app0.bin\n"
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    assert env["ok"], env["error"]
    written = {Path(p).name: spy.reads[p] for p in _image_args(spy.argv[-1])}
    assert written["boot_app0.bin"] == copied and boot.read_bytes() != copied
    got = {i["name"]: i["sha256"] for i in env["result"]["images"]}
    assert got["boot_app0.bin"] == hashlib.sha256(copied).hexdigest()
    assert _leftovers() == []


# ------------------------------------------------------------------ the copy itself: only regular files, bounded

def _swap_source_at_the_copy(monkeypatch, name, make) -> None:
    """Turn the source ``name`` into something else after the snapshot looked at it, just before it is opened."""
    real = board._copy_file

    def copy(src, dst):
        if Path(src).name == name:
            make(Path(src))
        return real(src, dst)

    monkeypatch.setattr(board, "_copy_file", copy)


def _release_fifo(path: Path) -> None:
    """Open and close the writing end without blocking: a reader stuck in open() then reads EOF."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
    except OSError:
        pass  # no reader waiting


def test_source_turned_into_a_fifo_is_tool_failed_without_hanging(fake_tools, fw, port, monkeypatch):
    r = _build(fake_tools, fw)
    fifo = _sources(fw)["firmware.bin"]

    def make(p):
        p.unlink()
        os.mkfifo(p)

    _swap_source_at_the_copy(monkeypatch, "firmware.bin", make)
    touched = _no_port_access(monkeypatch)
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(env=_flash(fw, port, r)), daemon=True)
    t.start()
    t.join(15)
    hung = t.is_alive()
    deadline = time.monotonic() + 10
    while t.is_alive() and time.monotonic() < deadline:  # never leave a thread blocked on the FIFO behind
        _release_fifo(fifo)
        t.join(0.2)
    assert not hung, "the copy blocked on a FIFO"
    env = out["env"]
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert "not a regular file" in env["error"]["message"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


@pytest.mark.parametrize("kind", ["device", "folder"])
def test_source_that_is_not_a_regular_file_is_tool_failed(fake_tools, fw, port, monkeypatch, kind):
    r = _build(fake_tools, fw)

    def make(p):
        p.unlink()
        if kind == "device":
            p.symlink_to("/dev/zero")
        else:
            p.mkdir()

    _swap_source_at_the_copy(monkeypatch, "firmware.bin", make)
    touched = _no_port_access(monkeypatch)
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    limit = 8 << 20 if hard == resource.RLIM_INFINITY else min(8 << 20, hard)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, hard))  # a copy without a bound stops here, not at a full disk
    try:
        env = _flash(fw, port, r)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert "not a regular file" in env["error"]["message"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


def test_copy_reads_at_most_the_size_seen_when_the_source_was_opened(tmp_path, monkeypatch):
    src = tmp_path / "grows.bin"
    src.write_bytes(b"A" * 1000)
    ino = src.stat().st_ino
    real = os.fstat
    grown: list[bool] = []

    def fstat(fd):
        st = real(fd)
        if st.st_ino == ino and not grown:  # the source grows right after the copy looked at its size
            grown.append(True)
            with open(src, "ab") as f:
                f.write(b"B" * 5000)
        return st

    monkeypatch.setattr(os, "fstat", fstat)
    dst = tmp_path / "copy.bin"
    board._copy_file(src, dst)
    assert grown and src.stat().st_size == 6000
    assert dst.read_bytes() == b"A" * 1000
    assert stat.S_IMODE(dst.stat().st_mode) == 0o600


# ------------------------------------------------------------------ one write list: every spelling names one file

BUILD = "{project_dir}/.pio/build/{env}"
# How a path of the pio metadata can name a file of the build folder (<n>: its name, <N>: the name in upper case).
SPELLINGS = {
    "unchanged": BUILD + "/<n>",
    "alias_folder": "{project_dir}/.pio/alias/<n>",
    "dotdot_middle": BUILD + "/../{env}/<n>",
    "dotdot_tail": BUILD + "/<n>/x/..",
    "dot_slash": BUILD + "/./<n>",
    "double_slash": "{project_dir}//.pio/build//{env}//<n>",
    "trailing_slash": BUILD + "/<n>/",
    "relative_to_project": ".pio/build/{env}/<n>",
    "other_case_symlink": BUILD + "/<N>",
    "same_name_other_folder": "{project_dir}/.pio/other/<n>",
}


def _spelled(how: str, name: str) -> str:
    return SPELLINGS[how].replace("<n>", name).replace("<N>", name.upper())


def _no_sleep(data: dict) -> dict:
    data["write-flash"] = {**data["write-flash"], "sleep": 0}
    return data


def _spell_entry(fake_tools, fw, how: str, image: str) -> Path:
    """Name ``image`` in the pio metadata the way ``how`` says (the app image through prog_path, firmware.elf);
    returns the file the spelling stands for (where a swap has to happen)."""
    build = fw / ".pio" / "build" / "s3"
    names = ["firmware.elf", "firmware.bin"] if image == "firmware.bin" else [image]
    if how == "alias_folder":
        (fw / ".pio" / "alias").symlink_to(build)
    elif how == "other_case_symlink":  # the app image name follows the ELF: FIRMWARE.ELF -> FIRMWARE.bin
        links = {"FIRMWARE.ELF": "firmware.elf", "FIRMWARE.bin": "firmware.bin"} if image == "firmware.bin" else {
            image.upper(): image}
        for link, real in links.items():
            (build / link).symlink_to(real)
    elif how == "same_name_other_folder":
        (fw / ".pio" / "other").mkdir()
        for n in names:
            shutil.copy2(build / n, fw / ".pio" / "other" / n)
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    entry = data["metadata"]["json"]["{env}"]
    if image == "firmware.bin":
        entry["prog_path"] = _spelled(how, "firmware.elf")
    else:
        entry["extra"]["flash_images"] = [dict(i, path=_spelled(how, image)) if i["path"].endswith("/" + image) else i
                                          for i in entry["extra"]["flash_images"]]
    fake_tools.scenario(_no_sleep(data))
    return (fw / ".pio" / "other" if how == "same_name_other_folder" else build) / image


def _assert_refused_or_approved(env, spy, approved: dict[str, str], *, may_refuse: bool) -> None:
    """The one statement about a flash: it was refused before any write, or every file handed to esptool whose
    name is an approved image name (the name of the copy and its name in result.images, any case) holds the
    approved bytes."""
    assert contracts.validate_envelope(env) == []
    if not env["ok"]:
        assert may_refuse, env["error"]
        assert not any("write-flash" in a for a in spy.argv), spy.argv
        assert _leftovers() == []
        return
    want = {n.casefold(): h for n, h in approved.items()}
    (write,) = [a for a in spy.argv if "write-flash" in a]
    i = write.index("detect") + 1
    images = {img["offset"]: img for img in env["result"]["images"]}
    assert sorted(images) == sorted(write[i::2])
    handed = [(p, images[o]["name"]) for o, p in zip(write[i::2], write[i + 1::2], strict=True)]
    handed += [(a[-1], Path(a[-1]).name) for a in spy.argv if "image-info" in a]
    for path, listed in handed:
        assert listed not in ("", ".", "..") and listed == Path(path).name, (path, listed)
        got = hashlib.sha256(spy.reads[path]).hexdigest()
        for name in (Path(path).name, listed):
            if name.casefold() in want:
                assert got == want[name.casefold()], (path, listed)
    assert _leftovers() == []


@pytest.mark.parametrize("swap", [False, True], ids=["no_swap", "swapped_only_for_the_snapshot"])
@pytest.mark.parametrize("image", BUILD_NAMES)
@pytest.mark.parametrize("how", list(SPELLINGS))
def test_every_spelling_of_an_entry_writes_only_approved_bytes(fake_tools, fw, port, monkeypatch, how, image, swap):
    r = _build(fake_tools, fw)
    target = _spell_entry(fake_tools, fw, how, image)
    if swap:
        _swapped_only_for_the_snapshot(monkeypatch, target)
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    _assert_refused_or_approved(env, spy, r["images"], may_refuse=swap)
    if swap:  # the copy holds the swapped bytes under an approved name: the swap reached what would be written
        assert env["ok"] is False and env["error"]["code"] == "elf_mismatch", env["error"]


def _dotdot_case(fake_tools, fw, monkeypatch, case: str) -> None:
    build = fw / ".pio" / "build" / "s3"
    other = fw / ".pio" / "other" / "bootloader.bin"
    if case != "build_race":
        other.parent.mkdir()
        other.write_bytes(b"FOREIGN bootloader\n")
    tail = {"build_race": BUILD + "/bootloader.bin/x/..",
            "foreign_replace": "{project_dir}/.pio/other/bootloader.bin/x/.."}

    def edit(items):
        if case == "foreign_extra":
            return items + [{"offset": "0x300000", "path": "{project_dir}/.pio/other/bootloader.bin/x/.."}]
        return [dict(i, path=tail[case]) if i["path"].endswith("/bootloader.bin") else i for i in items]

    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    extra = data["metadata"]["json"]["{env}"]["extra"]
    extra["flash_images"] = edit(extra["flash_images"])
    fake_tools.scenario(_no_sleep(data))
    if case == "build_race":
        _swapped_only_for_the_snapshot(monkeypatch, build / "bootloader.bin")


@pytest.mark.parametrize("case", ["build_race", "foreign_replace", "foreign_extra"])
def test_entry_ending_in_dotdot_is_checked_under_its_real_name(fake_tools, fw, port, monkeypatch, case):
    """``<folder>/bootloader.bin/x/..`` names bootloader.bin: its copy is checked like any bootloader.bin."""
    r = _build(fake_tools, fw)
    _dotdot_case(fake_tools, fw, monkeypatch, case)
    touched = _no_port_access(monkeypatch)
    env = _flash(fw, port, r)
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "elf_mismatch", env["error"]
    assert "bootloader.bin" in env["error"]["message"]
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls("esptool")) and touched == []
    assert _leftovers() == []


@pytest.mark.parametrize("how", ["dotdot_tail", "dotdot_middle", "dot_slash", "double_slash", "trailing_slash",
                                 "relative_to_project"])
def test_result_images_name_the_normalised_file_name(fake_tools, fw, port, monkeypatch, how):
    """Every build image (the app image through prog_path) spelled the same odd way: result.images and the copies
    handed to esptool carry the plain file names."""
    r = _build(fake_tools, fw)
    data = json.loads((bf.SCENARIOS / "board-pio-flash-ok.json").read_text(encoding="utf-8"))
    entry = data["metadata"]["json"]["{env}"]
    entry["prog_path"] = _spelled(how, "firmware.elf")
    entry["extra"]["flash_images"] = [dict(i, path=_spelled(how, Path(i["path"]).name)) if "/build/" in i["path"]
                                      else i for i in entry["extra"]["flash_images"]]
    fake_tools.scenario(_no_sleep(data))
    spy = Spy(monkeypatch)
    env = _flash(fw, port, r)
    assert env["ok"], env["error"]
    assert [(i["offset"], i["name"]) for i in env["result"]["images"]] == [
        ("0x0000", "bootloader.bin"), ("0x8000", "partitions.bin"), ("0xe000", "boot_app0.bin"),
        ("0x10000", "firmware.bin")]
    assert [Path(p).name for p in _image_args(spy.argv[-1])] == [i["name"] for i in env["result"]["images"]]
    _assert_refused_or_approved(env, spy, r["images"], may_refuse=False)


# ------------------------------------------------------------------ the copy: a source that shrinks, no tty

def _shrink_after_fstat(monkeypatch, src: Path, keep: int) -> list[bool]:
    ino = src.stat().st_ino
    real = os.fstat
    done: list[bool] = []

    def fstat(fd):
        st = real(fd)
        if st.st_ino == ino and not done:  # the source shrinks right after the copy looked at its size
            done.append(True)
            os.truncate(src, keep)
        return st

    monkeypatch.setattr(os, "fstat", fstat)
    return done


def test_copy_of_a_source_that_shrinks_is_tool_failed(tmp_path, monkeypatch):
    src = tmp_path / "shrinks.bin"
    src.write_bytes(b"A" * 5000)
    done = _shrink_after_fstat(monkeypatch, src, 1000)
    with pytest.raises(contracts.BenchError) as e:
        board._copy_file(src, tmp_path / "copy.bin")
    assert done and e.value.code == "tool_failed" and "changed while it was copied" in e.value.message


@pytest.mark.parametrize("name", ["boot_app0.bin", "bootloader.bin"])
def test_image_that_shrinks_while_it_is_copied_stops_the_flash(fake_tools, fw, port, monkeypatch, name):
    r = _build(fake_tools, fw)
    src = _sources(fw)[name]
    src.write_bytes(src.read_bytes() * 200)  # bootloader.bin no longer matches: the copy must fail first
    done = _shrink_after_fstat(monkeypatch, src, 10)
    touched = _no_port_access(monkeypatch)
    env = _flash(fw, port, r)
    assert done
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed", env["error"]
    assert "changed while it was copied" in env["error"]["message"] and name in env["error"]["message"]
    assert fake_tools.calls("esptool") == [] and touched == []
    assert _leftovers() == []


def test_copy_opens_the_source_without_becoming_its_controlling_terminal(tmp_path, monkeypatch):
    src = tmp_path / "image.bin"
    src.write_bytes(b"IMAGE\n")
    flags: dict[str, int] = {}
    real = os.open

    def note(path, fl, *a, **kw):
        flags[str(path)] = fl
        return real(path, fl, *a, **kw)

    monkeypatch.setattr(os, "open", note)
    board._copy_file(src, tmp_path / "copy.bin")
    assert flags[str(src)] & os.O_NOCTTY and flags[str(src)] & os.O_NONBLOCK

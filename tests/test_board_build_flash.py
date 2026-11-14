"""board.metadata, board.build and board.flash with the fake pio/esptool (guard, ELF hash, write-flash argv,
pause)."""
import functools
import json
import os
import shutil
import time
from pathlib import Path

import pytest
import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts, serialport, storage

SIZES = ["Linking .pio/build/s3/firmware.elf",
         "RAM:   [=         ]   5.6% (used 18432 bytes from 327680 bytes)",
         "Flash: [=         ]   7.9% (used 263377 bytes from 3342336 bytes)",
         "========================= [SUCCESS] Took 4.22 seconds ========================="]


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def _ok(env):
    assert contracts.validate_envelope(env) == [], env
    assert env["ok"], env["error"]
    return env


def _built(fake_tools, project, scenario="board-pio-flash-ok.json"):
    fake_tools.scenario(scenario)
    env = _ok(board.build(project, "s3"))
    return env["result"]["elf_sha256"]


def allow():
    return None


def test_parse_sizes():
    s = board.parse_sizes(SIZES)
    assert s == {"ram_pct": 5.6, "flash_pct": 7.9, "ram_used": 18432, "ram_total": 327680,
                 "flash_used": 263377, "flash_total": 3342336}
    assert board.parse_sizes(["RAM:   [          ]   0.0%", "nothing"])["ram_pct"] == 0.0
    assert board.parse_sizes([])["flash_pct"] is None


def test_metadata_fields(fake_tools, project):
    fake_tools.scenario("board-pio-build-ok.json")
    m = board.metadata(project, "s3")
    assert m["prog_path"] == f"{project.resolve()}/.pio/build/s3/firmware.elf"
    assert m["cc_path"].endswith("/xtensa-esp32s3-elf-gcc")
    assert m["toolchain_prefix"].endswith("/xtensa-esp32s3-elf-") and m["addr2line"].endswith("xtensa-esp32s3-elf-addr2line")
    (call,) = fake_tools.calls("pio")
    assert call["argv"][:6] == ["project", "metadata", "-d", str(project.resolve()), "-e", "s3"]
    assert call["argv"][6] == "--json-output-path"


def test_build_ok(fake_tools, project):
    fake_tools.scenario("board-pio-build-ok.json")
    lines = []
    env = _ok(board.build(project, "s3", on_line=lines.append))
    r = env["result"]
    elf = project / ".pio" / "build" / "s3" / "firmware.elf"
    assert r["ok"] is True and r["ram_pct"] == 5.6 and r["flash_pct"] == 7.9
    assert r["elf"] == ".pio/build/s3/firmware.elf" and r["elf_sha256"] == board.sha256_file(elf)
    assert r["addr2line"].endswith("xtensa-esp32s3-elf-addr2line")
    assert env["summary"].startswith("Build ok in ") and "RAM 5.6 %, flash 7.9 %" in env["summary"]
    assert env["simulated"] is False and env["checks"][0]["status"] == "passed"
    assert any("[SUCCESS]" in ln for ln in lines)
    log = serialport.artifact_path(r["log_ref"]).read_text(encoding="utf-8")
    assert "RAM:   [=         ]   5.6%" in log
    run, meta = fake_tools.calls("pio")
    assert run["argv"] == ["run", "-d", str(project.resolve()), "-e", "s3", "-t", "checkprogsize", "-t", "buildprog"]
    assert meta["argv"][1] == "metadata"
    for key in ("ok", "duration_s", "ram_pct", "flash_pct", "elf", "elf_sha256", "log_ref"):  # job.build.done fixture
        assert key in r


def test_build_compile_error(fake_tools, project):
    fake_tools.scenario("board-pio-build-fail.json")
    env = board.build(project, "s3")
    assert contracts.validate_envelope(env) == []
    assert env["ok"] is False and env["error"]["code"] == "tool_failed"
    assert "'undefined_call' was not declared" in env["error"]["message"]
    assert env["result"]["errors"] == ["src/main.cpp:7:3: error: 'undefined_call' was not declared in this scope"]
    assert [c["argv"][0] for c in fake_tools.calls("pio")] == ["run"]  # no metadata after a failed build


def test_build_answer_stays_small(fake_tools, project):
    long_err = "src/main.cpp:7:3: error: " + "x" * 2000
    fake_tools.scenario({"run": {"rc": 1, "stdout": "\n".join([long_err] * 10 + ["y" * 5000] * 50) + "\n"}})
    env = board.build(project, "s3")
    assert env["error"]["code"] == "tool_failed" and len(json.dumps(env)) <= contracts.MAX_RESULT_BYTES


def test_build_unknown_env(fake_tools, project):
    fake_tools.scenario({"run": {"rc": 1, "stdout": "UnknownEnvNamesError: Unknown environment names 'x'. Valid names are 's3'\n"}})
    env = board.build(project, "x")
    assert env["error"]["code"] == "invalid_args" and "Valid names are 's3'" in env["error"]["message"]


def test_build_checks_project_folder(fake_tools, project, tmp_path):
    fake_tools.scenario("board-pio-build-ok.json")
    (tmp_path / "file.txt").write_text("x")
    for bad in (tmp_path / "missing", tmp_path / "file.txt", tmp_path, ""):
        env = board.build(bad, "s3")
        assert env["error"]["code"] == "invalid_args", bad
    assert board.build(project, "s3; rm -rf /")["error"]["code"] == "invalid_args"
    assert fake_tools.calls() == []


def test_build_timeout(fake_tools, project, tmp_path):
    pid_file = tmp_path / "child.pid"
    fake_tools.scenario({"run": {"sleep": 60, "spawn_child": True, "child_pid_file": str(pid_file)}})
    t0 = time.monotonic()
    env = board.build(project, "s3", timeout=1.5)
    assert env["error"]["code"] == "timeout" and time.monotonic() - t0 < 10
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("pio's child process survived the timeout")


def test_build_missing_elf(fake_tools, project):
    fake_tools.scenario("board-pio-build-ok.json", run={"write_files": {}})
    env = board.build(project, "s3")
    assert env["error"]["code"] == "elf_missing"


def test_build_tool_missing(project, monkeypatch, tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert board.build(project, "s3")["error"]["code"] == "tool_missing"


def test_build_works_with_hardware_off(fake_tools, project):
    fake_tools.scenario("board-pio-build-ok.json")
    assert os.environ["CIRCUIT_BENCH_HW"] == "off"
    _ok(board.build(project, "s3"))


def test_build_through_provider(fake_tools, project):
    board.register_provider("sim://", bf.TestProvider())
    env = _ok(board.build(project, "s3", port="sim://test-s3"))
    assert env["simulated"] is True and env["result"]["elf_sha256"] == bf.SHA_A and fake_tools.calls() == []


# ------------------------------------------------------------------------------------------------ flash

def test_flash_writes_all_images_with_esptool(fake_tools, project, hw_on, pty_port, monkeypatch):
    """Bootloader, partition table, boot_app0 and the app at the offsets of pio project metadata, with the
    mode/frequency of the app image header and --chip of the image; no pio upload (it wrote only the app)."""
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    env = _ok(board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow))
    assert not [c for c in fake_tools.calls("pio") if "upload" in c["argv"]]
    info, write = [c for c in fake_tools.calls("esptool")]
    build = project.resolve() / ".pio" / "build" / "s3"
    snap = Path(info["argv"][-1]).parent  # esptool reads private copies of the images, never the build folder
    assert snap.parent == storage.data_dir() / "tmp" and snap.name.startswith("flash-") and not snap.exists()
    assert info["argv"] == ["image-info", str(snap / "firmware.bin")]
    assert write["argv"] == ["--chip", "esp32s3", "--port", pty_port.name, "--baud", "460800", "--before", "default-reset",
                             "--after", "hard-reset", "write-flash", "-z", "--flash-mode", "dio", "--flash-freq", "80m",
                             "--flash-size", "detect", "0x0000", str(snap / "bootloader.bin"),
                             "0x8000", str(snap / "partitions.bin"),
                             "0xe000", str(snap / "boot_app0.bin"),
                             "0x10000", str(snap / "firmware.bin")]
    assert write["home"] == write["cwd"] and write["cwd"] != str(project.resolve())  # no esptool.cfg of the user
    assert not any("erase" in a for c in fake_tools.calls() for a in c["argv"])
    r = env["result"]
    assert r["ok"] and r["port"] == pty_port.name and r["mac"] == "aa:bb:cc:dd:ee:ff" and r["elf_sha256"] == sha
    assert [(i["offset"], i["name"]) for i in r["images"]] == [("0x0000", "bootloader.bin"), ("0x8000", "partitions.bin"),
                                                               ("0xe000", "boot_app0.bin"), ("0x10000", "firmware.bin")]
    assert r["images"][0]["sha256"] == board.sha256_file(build / "bootloader.bin")
    assert r["images"][2]["sha256"] == board.sha256_file(project / ".pio" / "fake-framework" / "boot_app0.bin")
    assert r["verified"] is True and "duration_s" in r and env["simulated"] is False
    assert {c["id"]: c["status"] for c in env["checks"]} == {"board.flash.elf_hash": "passed", "board.flash.verified": "passed"}
    assert env["summary"].startswith(f"Flashed firmware.elf ({sha[:8]}…) to {pty_port.name}")
    ids = {s["id"] for s in env["sources"]}
    assert {"board-pio-6.2.0-flash-images", "board-pio-espressif32-6.9.0-upload-args", "board-esptool-5.6.0-write-flash",
            "board-observed-2026-11-07-app-only"} <= ids


def test_flash_upload_speed_and_app_offset_come_from_the_project(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    data = fake_tools.scenario("board-pio-flash-ok.json")
    data["metadata"]["json"]["{env}"]["extra"]["application_offset"] = "0x20000"
    fake_tools.scenario(data)
    sha = _ok(board.build(project, "s3"))["result"]["elf_sha256"]
    ini = project / "platformio.ini"
    ini.write_text(ini.read_text() + "upload_speed = 921600\n")
    _ok(board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow))
    argv = fake_tools.calls("esptool")[-1]["argv"]
    assert argv[argv.index("--baud") + 1] == "921600" and argv[-2] == "0x20000"
    assert Path(argv[-1]).name == "firmware.bin" and Path(argv[-1]).parent.parent == storage.data_dir() / "tmp"


def test_flash_without_extra_images_is_refused(fake_tools, project, hw_on, pty_port, monkeypatch):
    """No bootloader/partition table in the metadata -> elf_missing, no esptool (was: app_only)."""
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    data = fake_tools.scenario("board-pio-flash-ok.json")
    data["metadata"]["json"]["{env}"].pop("extra")
    fake_tools.scenario(data)
    sha = _ok(board.build(project, "s3"))["result"]["elf_sha256"]
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["ok"] is False and env["error"]["code"] == "elf_missing"
    assert "complete image sets" in env["error"]["message"]
    assert not any(w["code"] == "app_only" for w in env["warnings"])
    assert fake_tools.calls("esptool") == []


def test_flash_missing_extra_image_or_unreadable_header_writes_nothing(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    (project / ".pio" / "fake-framework" / "boot_app0.bin").unlink()
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["error"]["code"] == "elf_missing" and "boot_app0.bin" in env["error"]["message"]
    sha = _built(fake_tools, project)
    fake_tools.scenario("board-pio-flash-ok.json", **{"image-info": {"rc": 2, "stdout": "A fatal error occurred: bad image\n"}})
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["error"]["code"] == "tool_failed" and "image-info" in env["error"]["message"]
    assert not [c for c in fake_tools.calls("esptool") if "write-flash" in c["argv"]]


def test_flash_wrong_chip_is_chip_mismatch(fake_tools, project, hw_on, pty_port, monkeypatch):
    """esptool's own check (--chip of the image): the second line of defence after guard.check_flash."""
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    fake_tools.scenario("board-pio-flash-ok.json", **{"write-flash": {
        "rc": 2, "stdout": "esptool v5.6.0\nConnecting....\n\nA fatal error occurred: This chip is ESP32-C6, not ESP32-S3. "
                           "Wrong chip argument?\n"}})
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["error"]["code"] == "chip_mismatch" and "ESP32-C6" in env["error"]["message"]
    assert "nothing was written" in env["error"]["message"]


def test_flash_without_guard_ok_runs_no_cli(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    fake_tools.log.unlink()
    refusal = contracts.fail("board.flash", "not_confirmed", "run detect and build first")
    calls = []

    def deny(**kw):
        calls.append(kw)
        return refusal

    def boom():
        raise RuntimeError("guard crashed")

    guards = [functools.partial(deny, via="tool", port=pty_port.name), boom, None, "yes",
              lambda: {"ok": "maybe"}, lambda: contracts.fail("board.flash", "flash_disabled", "allow_flash is off")]
    codes = []
    for guard in guards:
        env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=guard)
        assert contracts.validate_envelope(env) == [] and env["ok"] is False
        codes.append(env["error"]["code"])
    assert codes == ["not_confirmed"] * 5 + ["flash_disabled"]
    assert calls == [{"via": "tool", "port": pty_port.name}]
    assert fake_tools.calls() == []  # neither metadata nor upload ran


def test_flash_elf_changed_is_elf_mismatch_without_upload(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    elf = project / ".pio" / "build" / "s3" / "firmware.elf"
    elf.write_text("FAKE-ELF build 2 (changed after approval)\n")
    fake_tools.log.unlink()
    guard_calls = []
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=lambda: guard_calls.append(1))
    assert env["ok"] is False and env["error"]["code"] == "elf_mismatch"
    assert guard_calls == [1]
    # read-only lookups: the computed configuration and the ELF path
    assert [c["argv"][:2] for c in fake_tools.calls()] == [["project", "config"], ["project", "metadata"]]
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256="0" * 64, guard=allow)
    assert env["error"]["code"] == "elf_mismatch"
    assert board.flash(project, "s3", pty_port.name, expected_elf_sha256="abc", guard=allow)["error"]["code"] == "invalid_args"
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls())


def test_flash_image_older_than_elf_is_refused(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    image = project / ".pio" / "build" / "s3" / "firmware.bin"
    old = time.time() - 3600
    os.utime(image, (old, old))
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["error"]["code"] == "elf_mismatch" and "older" in env["error"]["message"]
    image.unlink()
    assert board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)["error"]["code"] == "elf_missing"
    assert not any("write-flash" in c["argv"] for c in fake_tools.calls())


def test_flash_refuses_erase_in_platformio_ini(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    ini = project / "platformio.ini"
    ini.write_text(ini.read_text() + "upload_flags = --erase-all\n")
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["error"]["code"] == "invalid_args" and "never erases" in env["error"]["message"]
    ini.write_text(ini.read_text().replace("upload_flags = --erase-all\n", "; erase is never used here\n"))
    _ok(board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow))


def test_flash_hardware_off_is_sim_only_without_cli(fake_tools, project):
    fake_tools.scenario("board-pio-flash-ok.json")
    guard_calls = []
    env = board.flash(project, "s3", "/dev/ttyACM0", expected_elf_sha256=bf.SHA_A, guard=lambda: guard_calls.append(1))
    assert env["error"]["code"] == "sim_only" and guard_calls == [] and fake_tools.calls() == []


def test_flash_no_serial_data_hint(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x4001, "TinyUSB CDC")])
    sha = _built(fake_tools, project, "board-pio-flash-no-serial-data.json")
    lines = []
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow, on_line=lines.append)
    assert env["error"]["code"] == "tool_failed" and env["error"]["hint"] == board.NO_AUTO_RESET_HINT
    assert any(w["code"] == "no_auto_reset" for w in env["warnings"])
    assert lines[0] == f"warning: {board.NO_AUTO_RESET_HINT}"
    assert env["result"]["log_ref"] and "No serial data received" in serialport.artifact_path(env["result"]["log_ref"]).read_text()


def test_flash_pauses_an_open_port_and_reopens_it(fake_tools, project, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    sha = _built(fake_tools, project)
    b = serialport.broker()
    states = []
    b.subscribe(pty_port.name, lambda m: states.append(m["state"]) if m["t"] == "state" else None)
    b.open(pty_port.name, 115200)
    seen = {}
    real_run = board.clitools.run

    def spy(argv, **kw):
        if "write-flash" in argv:
            seen["state"] = b.status(pty_port.name)["state"]
            seen["open"] = b.is_open(pty_port.name)
            seen["pause_file"] = serialport.pause_path(pty_port.name).exists()
        return real_run(argv, **kw)

    monkeypatch.setattr(board.clitools, "run", spy)
    _ok(board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow))
    assert seen == {"state": "paused", "open": False, "pause_file": True}
    assert b.is_open(pty_port.name) and b.status(pty_port.name)["state"] == "open"
    assert states == ["open", "paused", "open"]
    assert not serialport.pause_path(pty_port.name).exists()


def test_flash_through_provider(fake_tools, project):
    prov = bf.TestProvider()
    board.register_provider("sim://", prov)
    env = _ok(board.flash(project, "s3", "sim://test-s3", expected_elf_sha256=bf.SHA_A, guard=allow))
    assert env["simulated"] is True and env["result"]["port"] == "sim://test-s3" and prov.flashed
    assert fake_tools.calls() == []
    # a provider flash also needs the guard's OK, and the hash must match the provider's firmware
    refused = board.flash(project, "s3", "sim://test-s3", expected_elf_sha256=bf.SHA_A,
                          guard=lambda: contracts.fail("board.flash", "not_confirmed", "no"))
    assert refused["error"]["code"] == "not_confirmed" and len(prov.flashed) == 1
    env = board.flash(project, "s3", "sim://test-s3", expected_elf_sha256="b" * 64, guard=allow)
    assert env["error"]["code"] == "elf_mismatch" and len(prov.flashed) == 1


def test_flash_tool_missing(fake_tools, project, hw_on, pty_port, monkeypatch, tmp_path):
    bf.mock_comports(monkeypatch, [])
    sha = _built(fake_tools, project)
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(tmp_path / "no" / "pio")}))
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=sha, guard=allow)
    assert env["error"]["code"] == "tool_missing"


# ------------------------------------------------------------------------------------------------ toolchain

EXAMPLE = Path(__file__).resolve().parents[1] / "circuit_bench" / "data" / "examples" / "laser-trigger"


@pytest.mark.toolchain
def test_offline_build_of_the_example(tmp_path, monkeypatch):
    """Real pio (no upload): build a copy of the example firmware into $TMPDIR, read the metadata field names."""
    real_home = storage.real_home()
    pio = real_home / ".local" / "bin" / "pio"
    core = real_home / ".platformio"
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1" or not pio.is_file() or not (core / "platforms" / "espressif32").is_dir() \
            or not EXAMPLE.is_dir():
        pytest.skip("needs CB_TOOLCHAIN_TESTS=1, ~/.local/bin/pio and espressif32")
    work = tmp_path / "example-fw"
    shutil.copytree(EXAMPLE, work)
    monkeypatch.setenv("PLATFORMIO_CORE_DIR", str(core))
    monkeypatch.setenv("PLATFORMIO_BUILD_DIR", str(tmp_path / "build"))
    monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(pio)}))
    meta = board.metadata(work, "s3")
    print("metadata:", json.dumps(meta, indent=1))
    assert meta["cc_path"].endswith("toolchain-xtensa-esp32s3/bin/xtensa-esp32s3-elf-gcc")
    assert meta["prog_path"] == str(tmp_path / "build" / "s3" / "firmware.elf")
    assert meta["toolchain_prefix"].endswith("xtensa-esp32s3-elf-")
    env = board.build(work, "s3")
    print("build:", json.dumps({k: env["result"].get(k) for k in ("ok", "duration_s", "ram_pct", "flash_pct", "elf_path",
                                                                  "elf_sha256")}, indent=1), env["summary"])
    assert env["ok"], env["error"]
    assert 0 < env["result"]["ram_pct"] < 100 and 0 < env["result"]["flash_pct"] < 100
    assert env["result"]["elf_sha256"] == board.sha256_file(meta["prog_path"])
    assert Path(env["result"]["addr2line"]).is_file()
    # the images board.flash writes come from the real metadata (S3: bootloader at 0x0000) and exist after a build
    meta = board.metadata(work, "s3")
    assert [i["offset"] for i in meta["flash_images"]] == ["0x0000", "0x8000", "0xe000"] and meta["app_offset"] == "0x10000"
    assert [Path(i["path"]).name for i in meta["flash_images"]] == ["bootloader.bin", "partitions.bin", "boot_app0.bin"]
    assert all(Path(i["path"]).is_file() for i in meta["flash_images"])
    esptool = Path.home() / ".local" / "bin" / "esptool"
    if esptool.is_file():
        monkeypatch.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(pio), "esptool_path": str(esptool)}))
        assert board.image_info(Path(meta["prog_path"]).with_suffix(".bin")) == {"chip": "esp32s3", "flash_mode": "dio",
                                                                              "flash_freq": "80m"}

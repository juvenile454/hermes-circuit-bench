"""The short log_tail of board.flash and board.detect leaves out esptool progress lines (except the last one).

Only fakes: fake esptool/pio, pty ports, mocked port lists, synthetic MACs.
"""
import re

import board_fixtures as bf
from board_fixtures import *  # noqa: F403

from circuit_bench.bench_core import board, contracts, jobs, serialport

PROGRESS = re.compile(r"^\s*(?:Writing|Reading|Erasing) at 0x[0-9a-fA-F]+\b.*?\d{1,3}(?:\.\d+)?\s*%")
IMAGES = ((0x0000, 15104), (0x8000, 3072), (0xE000, 8192), (0x10000, 263488))


def esptool5_write_flash() -> str:
    """Synthetic esptool 5 write-flash output: four images, each with progress, ``Wrote`` and the hash check."""
    out = ["esptool v5.6.0", "Connected to ESP32-S3 on {port}:", "Chip type:          ESP32-S3 (QFN56) (revision v0.2)",
           "Features:           Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz", "Crystal frequency:  40MHz",
           "MAC:                aa:bb:cc:dd:ee:ff", "", "Uploading stub flasher...", "Running stub flasher...",
           "Stub flasher running.", "Changing baud rate to 460800...", "Changed.", "", "Configuring flash size...",
           "Auto-detected flash size: 16MB"]
    out += [f"Flash will be erased from 0x{off:08x} to 0x{off + size - 1:08x}..." for off, size in IMAGES]
    for off, size in IMAGES:
        for pct in (0.0, 25.0, 50.0, 75.0, 100.0):
            bar = "=" * int(pct // 10)
            out.append(f"Writing at 0x{off + int(size * pct / 100):08x} [{bar:<10}] {pct:5.1f}% {int(size * pct / 100)}/{size} bytes...")
        out.append(f"Wrote {size} bytes ({size // 2} compressed) at 0x{off:08x} in 0.3 seconds (459.1 kbit/s).")
        out.append("Hash of data verified.")
    out += ["", "Hard resetting via RTS pin..."]
    return "\n".join(out) + "\n"


def _flash(fake_tools, project, pty_port, monkeypatch, on_line=None):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    fake_tools.scenario("board-pio-flash-ok.json", **{"write-flash": {"stdout": esptool5_write_flash(), "sleep": 0}})
    built = board.build(project, "s3")
    assert built["ok"], built["error"]
    env = board.flash(project, "s3", pty_port.name, expected_elf_sha256=built["result"]["elf_sha256"],
                      guard=lambda: None, on_line=on_line)
    assert contracts.validate_envelope(env) == [] and env["ok"], env["error"]
    return env


def _project(tmp_path):
    d = tmp_path / "fw"
    (d / "src").mkdir(parents=True)
    (d / "platformio.ini").write_text("[env:s3]\nplatform = espressif32@6.9.0\nboard = esp32-s3-devkitc-1\n"
                                      "framework = arduino\n", encoding="utf-8")
    (d / "src" / "main.cpp").write_text("void setup() {}\nvoid loop() {}\n", encoding="utf-8")
    return d


def test_flash_log_tail_shows_every_image_check(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):
    env = _flash(fake_tools, _project(tmp_path), pty_port, monkeypatch)
    tail = env["result"]["log_tail"]
    assert len(tail) <= board.LOG_TAIL_LINES
    assert sum(line == "Hash of data verified." for line in tail) == 4
    progress = [line for line in tail if PROGRESS.match(line)]
    assert progress == ["Writing at 0x00050540 [==========] 100.0% 263488/263488 bytes..."]  # only the last one
    assert tail[-1] == "Hard resetting via RTS pin..."
    assert env["result"]["verified"] is True


def test_flash_log_ref_and_job_log_keep_every_line(fake_tools, hw_on, pty_port, monkeypatch, tmp_path):
    full = esptool5_write_flash().replace("{port}", pty_port.name).splitlines()
    table = jobs.JobTable(emit=lambda *a: None)
    seen = {}

    def work(ctx):
        seen["env"] = _flash(fake_tools, _project(tmp_path), pty_port, monkeypatch, on_line=ctx.log)
        return seen["env"]

    job = table.wait(table.start("flash", work)["job_id"], 30)
    assert job is not None and job["state"] == "done", job
    assert job["log_tail"] == full[-jobs.LOG_TAIL_LINES:]  # the job (desktop progress) sees the raw lines
    assert sum(bool(PROGRESS.match(line)) for line in job["log_tail"]) > 1
    ref = seen["env"]["result"]["log_ref"]
    assert ref
    stored = serialport.artifact_path(ref).read_text(encoding="utf-8").splitlines()
    assert stored == full


def test_drop_progress_keeps_the_last_progress_line_and_the_order():
    lines = ["esptool.py v4.7.0", "Compressed 15104 bytes to 9711...", "Writing at 0x00000000... (100 %)",
             "Wrote 15104 bytes (9711 compressed) at 0x00000000 in 0.3 seconds (effective 459.1 kbit/s)...",
             "Hash of data verified.", "Compressed 263488 bytes to 169392...", "Writing at 0x00010000... (9 %)",
             "Writing at 0x00010000... (52 %)", "  Erasing at 0x00020000 (12.5 %)", "Reading at 0x00001000 [==] 40%",
             "Writing at 0x00050000... (100 %)", "Writing at 0x00010000...",
             "Wrote 263488 bytes (169392 compressed) at 0x00010000 in 3.9 seconds (effective 540.2 kbit/s)...",
             "Hash of data verified.", "", "Leaving...", "Hard resetting via RTS pin..."]
    out = board._drop_progress(lines)
    assert out == [lines[0], lines[1], lines[3], lines[4], lines[5], lines[10], lines[11], *lines[12:]]
    assert board._drop_progress([]) == []
    assert board._drop_progress(["Writing at 0x00010000... (52 %)"]) == ["Writing at 0x00010000... (52 %)"]


def test_detect_log_tail_drops_progress_lines(fake_tools, hw_on, pty_port, monkeypatch):
    bf.mock_comports(monkeypatch, [(pty_port.name, 0x303A, 0x1001, "USB JTAG/serial debug unit")])
    data = fake_tools.scenario("board-esptool-s3.json")
    noise = [f"Reading at 0x{0x1000 * i:08x} [{'=' * i:<10}] {i * 10:.1f}%" for i in range(1, 11)]
    out = data["flash-id"]["stdout"].replace("\n\nHard resetting", "\n" + "\n".join(noise) + "\n\nHard resetting")
    fake_tools.scenario(data, **{"flash-id": {"stdout": out}})
    env = board.detect(pty_port.name)
    assert env["ok"], env["error"]
    tail = env["result"]["log_tail"]
    assert [line for line in tail if PROGRESS.match(line)] == [noise[-1]]
    assert "Detected flash size: 16MB" in tail and tail[-1] == "Hard resetting via RTS pin..."

"""Findings of the hardware tests on a real ESP32-S3 on its USB-Serial/JTAG (2026-11-06), backend side."""
from circuit_bench.bench_core import project


def test_panic_time_comes_from_the_log_not_from_the_decode():
    # hardware test: a decode after the flash stored the decode time as the panic time, so the old panic counted as current
    short = project._panic({"kind": "cpu_exception", "reason": "StoreProhibited", "core": 1,
                            "log_ref": "panic-20261106-150209.log", "frames": []})
    assert short["at"] == "2026-11-06T15:02:09Z"
    assert project._panic({"reason": "x", "log_ref": "panic-20261106-150209-2.log"})["at"] == "2026-11-06T15:02:09Z"
    assert project._panic({"reason": "x", "log_ref": "panic-20261106-150209.log", "at": "2026-11-06T16:00:00Z"})["at"] \
        == "2026-11-06T16:00:00Z"  # an explicit time wins
    assert project._ref_time("panic-20261399-250000.log") is None
    assert project._ref_time(None) is None


REAL = __import__("pathlib").Path(__file__).parent / "fixtures" / "real"


def test_real_panic_parses_like_the_board_printed_it():
    from circuit_bench.bench_core import crash
    env = crash.decode((REAL / "esp32s3-panic.log").read_text())  # no ELF: parse only
    res = env["result"]
    assert env["ok"] and res["reason"] == "StoreProhibited" and res["core"] == 1 and res["arch"] == "xtensa"
    assert res["registers"]["EXCVADDR"] == "0x0000000c" and res["registers"]["PC"] == "0x420019e4"
    assert [f["pc"] for f in res["frames"]] == ["0x420019e1", "0x42001a01", "0x42001a45", "0x42003dc6"]
    assert res["elf_sha256_log"] == "cb8f614b016a44c5"  # the "ELF file SHA256:" line: 16 hex digits
    assert any(w["code"] == "elf_missing" for w in env["warnings"])


def test_real_reset_reasons_in_the_banners():
    loop = (REAL / "esp32s3-reboot-loop.log").read_text().splitlines()
    after = (REAL / "esp32s3-after-flash.log").read_text().splitlines()
    # first boot after RESET was tapped, then the panic's own reboot
    assert [ln for ln in loop if ln.startswith("rst:")] == ["rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)",
                                                             "rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)"]
    assert after[2] == "rst:0x15 (USB_UART_CHIP_RESET),boot:0x8 (SPI_FAST_FLASH_BOOT)"
    assert "[laser-trigger] boot ok" in after


def test_esp32_project_names_its_module(tmp_path, monkeypatch):
    # ESP32 variants are the module itself (ESP32-WROOM-32E, label WROOM-32E)
    monkeypatch.setenv("CIRCUIT_BENCH_DATA_DIR", str(tmp_path))
    env = project.create("esp-a", "A", "esp32", "wroom-32e", "esp32-devkitc-v4")
    assert env["ok"] and env["result"]["project"]["board"]["module"] == "wroom-32e"
    assert project.create("s3-a", "A", "esp32s3", "n16r8", "esp32-s3-devkitc-1")["result"]["project"]["board"]["module"] == "wroom-1"

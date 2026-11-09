"""Only the first boot is POWERON; after a panic the simulated board restarts with
rst:0xc (RTC_SW_CPU_RST) and the ROM's "Saved PC:" line, like the console of a real ESP32-S3 (observation, see
sim.PANIC_RESET_LINE)."""
from circuit_bench.bench_core import crash, sim


def _lines():
    return list(sim._play({"firmware": "panic", "elf_sha256": "0123456789abcdef" + "0" * 48}))


def test_first_boot_poweron_then_software_resets():
    lines = _lines()
    resets = [t for t in lines if t.startswith("rst:")]
    assert resets[0].startswith("rst:0x1 (POWERON)")
    assert resets[1:] == [sim.PANIC_RESET_LINE] * (sim.PANIC_LOOPS - 1)
    for i, t in enumerate(lines):
        if t == sim.PANIC_RESET_LINE:
            assert lines[i + 1].startswith("Saved PC:0x") and lines[i - 1].startswith("ESP-ROM:")
            assert lines[i - 2] == "Rebooting..."  # right after the panic block


def test_decoder_reads_the_reset_reason_after_the_crash():
    p = crash.parse("\n".join(_lines()))
    assert p["reset_reason"] == {"code": "0xc", "name": "RTC_SW_CPU_RST", "when": "after_crash"}


def test_fixed_firmware_boots_once_with_poweron():
    fixed = list(sim._play({"firmware": "fixed", "elf_sha256": "a" * 64}))
    assert [t for t in fixed if t.startswith("rst:")] == [next(t for t in sim._log("boot.log") if t.startswith("rst:"))]
    assert not any(t.startswith("Saved PC") for t in fixed)

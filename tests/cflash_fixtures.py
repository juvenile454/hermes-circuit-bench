"""Offline toolchain builds of synthetic minimal projects, for the cflash and cdebug tests.

Three projects, generated under a pytest temporary folder (``$TMPDIR``), never flashed:

- ``wt32``: ``board = wt32-eth01`` on ``espressif32@6.9.0`` (ESP32, Xtensa)
- ``s2``:   ``board = esp32-s2-saola-1`` on ``espressif32@6.9.0`` with ``board_upload.flash_size = 8MB``
            (ASSUMPTION: the ESP32-S2-DevKitC-1 module carries 8 MB flash; the Saola-1 manifest says 4MB)
- ``c6``:   ``board = esp32-c6-devkitc-1`` on ``espressif32@8.0.0`` (ESP32-C6, RISC-V; Arduino needs 8.0.0)

Use from a test::

    import cflash_fixtures as cf

    def test_x(tmp_path_factory, monkeypatch):
        built = cf.build_seed("c6", tmp_path_factory, monkeypatch)   # skips cleanly without toolchain/packages
        built["elf"], built["addr2line"], built["chip"], built["functions"]

or the factory fixture ``cflash_seed`` (``from cflash_fixtures import cflash_seed``): ``cflash_seed("s2")``.

Rules: only with ``CB_TOOLCHAIN_TESTS=1``; only when ``sim._offline_ready`` says every package is installed (no
download, ever); build output only in ``PLATFORMIO_BUILD_DIR`` under the temporary folder; the real ``pio`` is the
user's (``CB_PIO`` or ``~/.local/bin/pio``), the PlatformIO core ``CB_PIO_CORE_DIR`` or ``~/.platformio``. Each seed is
built at most once per test session.
"""
from __future__ import annotations

import json
import os
import pwd
from pathlib import Path
from typing import Any

import pytest

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PIO_CORE = Path(os.environ.get("CB_PIO_CORE_DIR") or REAL_HOME / ".platformio")
PIO = Path(os.environ.get("CB_PIO") or REAL_HOME / ".local" / "bin" / "pio")
ENV = "seed"
S2_FLASH_ASSUMPTION = "8MB"  # ESP32-S2-DevKitC-1 (WROVER/SOLO-2 with 8 MB flash assumed), see module docstring

SEEDS: dict[str, dict[str, str]] = {
    "wt32": {"chip": "esp32", "board": "wt32-eth01", "platform": "espressif32@6.9.0", "extra": ""},
    "s2": {"chip": "esp32s2", "board": "esp32-s2-saola-1", "platform": "espressif32@6.9.0",
           "extra": f"board_upload.flash_size = {S2_FLASH_ASSUMPTION}\n"},
    "c6": {"chip": "esp32c6", "board": "esp32-c6-devkitc-1", "platform": "espressif32@8.0.0", "extra": ""},
}
# named, not inlined functions a decoder test can look up (synthetic code, never runs on a board)
FUNCTIONS = ("cb_fixture_store(unsigned char*, unsigned int)", "cb_fixture_sample()")
MAIN_CPP = """// Synthetic Circuit Bench fixture: only built offline, never flashed.
#include <Arduino.h>

static uint8_t cb_buffer[16];

__attribute__((noinline)) void cb_fixture_store(uint8_t *buf, size_t i) {
  buf[i] = (uint8_t)millis();  // a store a decoder can point to
}

__attribute__((noinline)) uint8_t cb_fixture_sample() {
  cb_fixture_store(cb_buffer, 3);
  return cb_buffer[3];
}

void setup() {
  Serial.begin(115200);
  Serial.println(cb_fixture_sample());
}

void loop() {
  delay(1000);
}
"""
_CACHE: dict[str, dict[str, Any]] = {}


def write_seed(root: Path, seed: str) -> Path:
    s = SEEDS[seed]
    d = root / seed
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "platformio.ini").write_text(
        f"; synthetic Circuit Bench fixture ({seed})\n[env:{ENV}]\nplatform = {s['platform']}\nboard = {s['board']}\n"
        f"framework = arduino\n{s['extra']}", encoding="utf-8")
    (d / "src" / "main.cpp").write_text(MAIN_CPP, encoding="utf-8")
    return d


def pio_env(build_dir: Path) -> dict[str, str]:
    return {"PLATFORMIO_CORE_DIR": str(PIO_CORE), "PLATFORMIO_BUILD_DIR": str(build_dir),
            "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "No", "PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL": "3650"}


def skip_reason(seed: str, project_dir: Path | None = None) -> str | None:
    """Why the real build of ``seed`` cannot run here (None: it can). Reads ~/.platformio, changes nothing."""
    if os.environ.get("CB_TOOLCHAIN_TESTS") != "1":
        return "set CB_TOOLCHAIN_TESTS=1 (run: CB_TOOLCHAIN_TESTS=1 pytest -m toolchain)"
    if not PIO.exists():
        return f"no pio at {PIO} (CB_PIO)"
    if not (PIO_CORE / "platforms").is_dir():
        return f"no PlatformIO platforms in {PIO_CORE} (CB_PIO_CORE_DIR)"
    from circuit_bench.bench_core import sim
    saved = {k: os.environ.get(k) for k in ("PLATFORMIO_CORE_DIR", "PLATFORMIO_PLATFORMS_DIR", "PLATFORMIO_PACKAGES_DIR")}
    os.environ["PLATFORMIO_CORE_DIR"] = str(PIO_CORE)
    os.environ.pop("PLATFORMIO_PLATFORMS_DIR", None)
    os.environ.pop("PLATFORMIO_PACKAGES_DIR", None)
    try:
        tmp = project_dir
        if tmp is None:
            import tempfile
            with tempfile.TemporaryDirectory(prefix="cb-cflash-probe-") as t:
                ready, missing = sim._offline_ready(write_seed(Path(t), seed), ENV)
        else:
            ready, missing = sim._offline_ready(tmp, ENV)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if not ready:
        return f"offline build of {seed} needs packages that are not installed: {', '.join(missing)}"
    return None


def _elf_machine(elf: Path) -> int:
    head = elf.read_bytes()[:20]
    assert head[:4] == b"\x7fELF", elf
    return int.from_bytes(head[18:20], "little")


ELF_MACHINE = {"xtensa": 94, "riscv": 243}  # ELF e_machine: EM_XTENSA, EM_RISCV


def build_seed(seed: str, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build ``seed`` once per session with ``board.build(..., chip=)`` (pre-check included) and return
    {seed, chip, board, platform, project, env, elf, elf_sha256, addr2line, toolchain_prefix, build}. Skips with the
    reason when the toolchain or a package is missing."""
    if seed in _CACHE:
        return _CACHE[seed]
    reason = skip_reason(seed)
    if reason:
        pytest.skip(reason)
    from circuit_bench.bench_core import board
    root = tmp_path_factory.mktemp(f"cflash-{seed}")
    project = write_seed(root, seed)
    with monkeypatch.context() as m:
        m.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"pio_path": str(PIO)}))
        for key, value in pio_env(root / "build").items():
            m.setenv(key, value)
        for key in ("PLATFORMIO_PLATFORMS_DIR", "PLATFORMIO_PACKAGES_DIR", "PLATFORMIO_BOARDS_DIR"):
            m.delenv(key, raising=False)
        env = board.build(project, ENV, timeout=1200, chip=SEEDS[seed]["chip"])
    assert env["ok"], (env["error"], env["result"] and env["result"].get("log_tail"))
    r = env["result"]
    out = {"seed": seed, "chip": SEEDS[seed]["chip"], "board": SEEDS[seed]["board"],
           "platform": SEEDS[seed]["platform"], "project": project, "env": ENV, "elf": Path(r["elf_path"]),
           "elf_sha256": r["elf_sha256"], "addr2line": r["addr2line"], "toolchain_prefix": r["toolchain_prefix"],
           "functions": FUNCTIONS, "build": env}
    _CACHE[seed] = out
    return out


@pytest.fixture
def cflash_seed(tmp_path_factory, monkeypatch):
    """Factory: ``cflash_seed("wt32" | "s2" | "c6")`` -> the build_seed() dict (skips without toolchain)."""
    return lambda seed: build_seed(seed, tmp_path_factory, monkeypatch)

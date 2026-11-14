"""Simulated board ``sim://esp32s3-n16r8`` and the demo project.

Public functions:
- ``register()``: registers the provider for ``sim://`` (``board.register_provider``); ``board`` calls it lazily on
  the first port lookup.
- ``demo(project_id="laser-trigger", *, by="agent") -> envelope`` (action ``sim.demo``): creates the demo project
  through ``project.create``/``project.update``; an existing project comes back unchanged (idempotent).
- ``crash_runner(project_dir=None) -> run``: an addr2line stand-in for ``crash.decode(..., run=run)`` that answers
  from ``data/sim/esp32s3-n16r8/decode.json`` (``run.simulated`` is True); ``decode(log, ...)`` is crash.decode with
  that runner and a result marked ``simulated: true``.
- ``copy_example(name, project_id)``: copies ``data/examples/<name>`` to ``projects/<id>/firmware/``.
- ``board_state()``, ``demo_crash()``, ``source_sha256()``: helpers (tests, probe).

The simulated board (``SimBoard``, provider protocol in ``board.py``):
- ``detect`` answers from ``detect.json`` (placeholder MAC ``aa:bb:cc:dd:ee:ff``);
- ``build`` runs the real ``pio run`` (explicit build targets, board.build) when PlatformIO is found, real builds
  are wanted (``CB_TOOLCHAIN_TESTS=1``, or a product run without ``CIRCUIT_BENCH_DEV_GUARD=1``) and the platform
  plus every package the build needs is installed (``_offline_ready``: no downloads); otherwise it answers from
  ``build.json`` and the ELF hash is the SHA-256 of the project sources (no ELF exists);
- ``flash`` simulates the upload (nothing is written: ``board.flash.verified`` is ``not_checked``) and stores the
  firmware state of the board in ``<data>/sim/esp32s3-n16r8.json``. Only the demo firmware is emulated
  (``is_demo_firmware``: its source refers to ``DEMO_CRASH``, like ``data/examples/laser-trigger``): ``panic`` while
  it builds the crash (``#define DEMO_CRASH 1`` and no fix), ``fixed`` for ``0``/no define/a fix; any other
  firmware is ``unknown`` (a ``sim_not_demo_firmware`` warning says so);
- ``line_source`` plays ``boot.log`` and then ``panic.log`` (a bounded reboot loop) or ``fixed.log`` with short
  pauses, and ends with the log; ``unknown`` firmware gets the ROM boot only (never the demo firmware's lines);
- ``monitor_notes`` tells ``serialport.monitor`` where the lines come from (``lines_source``, assumptions, warnings).
Every result is marked ``simulated: true``; real ports never reach this module (only the ``sim://`` prefix does).
The logs are synthetic: register values, addresses and lines follow a real offline build of the example
``data/examples/laser-trigger`` (``tests/test_sim_toolchain.py`` checks them against the real toolchain).
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import board, calc, chips, clitools, crash, project, runtime, schematic, solder, storage
from . import settings as _settings
from .contracts import BenchError, assumption, check, envelope, fail, from_error, warning

logger = logging.getLogger(__name__)

ACTION_DEMO = "sim.demo"
PREFIX = "sim://"
SCENARIO = "esp32s3-n16r8"
PORT = PREFIX + SCENARIO
DEMO_ID = "laser-trigger"
PACKAGE_DIR = Path(__file__).resolve().parent.parent
SIM_DIR = PACKAGE_DIR / "data" / "sim" / SCENARIO
DEMO_DIR = PACKAGE_DIR / "data" / "demo"
EXAMPLES_DIR = PACKAGE_DIR / "data" / "examples"

# Timing of the simulated board, in seconds. TIME_SCALE multiplies every pause (tests and probes set it to 0).
TIME_SCALE = 1.0
LINE_DELAY_S = 0.04
APP_START_S = 0.5  # ROM boot -> first line of the app (the example waits 500 ms for the USB serial port)
REBOOT_S = 0.3
FLASH_STEP_S = 0.15
BUILD_S = 0.5
PANIC_LOOPS = 3  # bounded reboot loop: the log ends after this many panics

_DEMO_CRASH_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+DEMO_CRASH(?:[ \t]+(\S+))?", re.MULTILINE)
_ENV_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$")  # same rule as board.py
_ID_RE = re.compile(r"^[a-z0-9-]{1,48}$")  # same rule as project.py
_SOURCE_DIRS = ("src", "include", "lib")
_FALSE = frozenset({"0", "false"})
_CALCS: dict[str, Callable[..., dict[str, Any]]] = {
    "npn": calc.npn, "divider": calc.divider, "led": calc.led, "i2c_pullup": calc.i2c_pullup,
}


# --------------------------------------------------------------------------------------------- data

def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sleep(seconds: float) -> None:
    if TIME_SCALE > 0 and seconds > 0:
        time.sleep(seconds * TIME_SCALE)


@lru_cache(maxsize=16)
def _data(name: str) -> dict[str, Any]:
    """A JSON file of the scenario without its ``_about`` keys."""
    raw = json.loads((SIM_DIR / name).read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@lru_cache(maxsize=16)
def _log(name: str) -> tuple[str, ...]:
    return tuple((SIM_DIR / name).read_text(encoding="utf-8").splitlines())


def _recipe(project_id: str) -> dict[str, Any]:
    raw = json.loads((DEMO_DIR / f"{DEMO_ID}.project.json").read_text(encoding="utf-8"))
    return {**{k: v for k, v in raw.items() if not k.startswith("_")}, "id": project_id}


def _check_port(port: Any) -> str:
    if port != PORT:
        raise BenchError("port_not_found", f"{str(port)[:80]}: no such simulated board", f"the simulated board is {PORT}")
    return port


def _project_dir(project_dir: Any) -> Path:
    if not isinstance(project_dir, str | os.PathLike) or not str(project_dir).strip():
        raise BenchError("invalid_args", "project_dir must be a folder with platformio.ini")
    path = Path(project_dir).expanduser()
    if not (path / "platformio.ini").is_file():
        raise BenchError("invalid_args", f"{path} has no platformio.ini", "pass the PlatformIO project folder")
    return path.resolve()


def _env(pdir: Path, env: Any) -> str:
    if not isinstance(env, str) or not _ENV_RE.fullmatch(env):
        raise BenchError("invalid_args", f"bad PlatformIO environment name {env!r}", "use the [env:<name>] from platformio.ini")
    ini = (pdir / "platformio.ini").read_text(encoding="utf-8", errors="replace")
    if not re.search(rf"^\s*\[env:{re.escape(env)}\]", ini, re.MULTILINE):
        raise BenchError("invalid_args", f"platformio.ini has no [env:{env}]", "use the [env:<name>] from platformio.ini")
    return env


# The demo firmware (data/examples/laser-trigger and its fixes): a preprocessor line refers to DEMO_CRASH, or the code
# still has the demo's sensor frame (a fix that dropped the whole DEMO_CRASH switch).
_DEMO_MARK_RE = re.compile(r"^[ \t]*#[ \t]*(?:define|undef|if|ifdef|ifndef|elif)\b[^\n]*\bDEMO_CRASH\b", re.MULTILINE)
_DEMO_IDENTS = (re.compile(r"\bwrite_sensor_buffer\b"), re.compile(r"\bsensor_frame\b"))


def is_demo_firmware(text: str) -> bool:
    """Is this ``src/main.cpp`` text the demo firmware (the only firmware the simulated board emulates)?"""
    code = _COMMENT_RE.sub("", text)
    return bool(_DEMO_MARK_RE.search(code)) or all(r.search(code) for r in _DEMO_IDENTS)


def demo_crash(project_dir: str | Path) -> bool | None:
    """For the demo firmware (``is_demo_firmware``): True if ``src/main.cpp`` builds the deliberate crash
    (``#define DEMO_CRASH`` not 0/false and no fix), False if it does not (``DEMO_CRASH 0`` or no define: ``#if
    !DEMO_CRASH`` then holds, or a fix). None without ``src/main.cpp`` or for any other firmware (not emulated)."""
    main = Path(project_dir) / "src" / "main.cpp"
    try:
        text = main.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not is_demo_firmware(text):
        return None
    m = _DEMO_CRASH_RE.search(text)
    if m is None:
        return False
    value = (m.group(1) or "1").strip().lower()
    if value in _FALSE:
        return False
    return not _fixed_otherwise(text)


# Fixes a model or a person may write instead of DEMO_CRASH 0 (the simulated board must not keep crashing then):
# the frame gets memory outside the ``#if !DEMO_CRASH`` block, or a NULL guard protects the write.
_NOT_DEMO_BLOCK_RE = re.compile(r"^[ \t]*#[ \t]*if[ \t]+!DEMO_CRASH\b.*?^[ \t]*#[ \t]*endif\b", re.MULTILINE | re.DOTALL)
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_FIX_RES = (
    re.compile(r"\bsensor_frame\s*=\s*(?![\s=])(?!(?:nullptr|NULL|0)\b)[^;]+;"),       # memory assigned
    re.compile(r"\bif\s*\(\s*!\s*(?:buf|sensor_frame)\s*\)"),                          # if (!buf)
    re.compile(r"\b(?:buf|sensor_frame)\s*[!=]=\s*(?:nullptr|NULL|0)\b"),               # buf == nullptr / != NULL
    re.compile(r"\b(?:nullptr|NULL)\s*[!=]=\s*(?:buf|sensor_frame)\b"),
    re.compile(r"\bif\s*\(\s*(?:buf|sensor_frame)\s*\)"),                               # if (buf)
)


def _fixed_otherwise(text: str) -> bool:
    code = _COMMENT_RE.sub("", _NOT_DEMO_BLOCK_RE.sub("", text))
    return any(r.search(code) for r in _FIX_RES)


def _source_files(pdir: Path) -> list[Path]:
    files = [pdir / "platformio.ini"]
    for name in _SOURCE_DIRS:
        root = pdir / name
        if root.is_dir():
            files += sorted(p for p in root.rglob("*") if p.is_file() and not any(
                part.startswith(".") for part in p.relative_to(pdir).parts))
    return files


def source_sha256(project_dir: str | Path) -> str:
    """SHA-256 over platformio.ini and the files under src/, include/, lib/ (path and content): the "ELF hash" of a
    simulated build. Any change of the sources changes it, so a flash after an edit needs a new build."""
    pdir = Path(project_dir)
    h = hashlib.sha256()
    for path in _source_files(pdir):
        rel = path.relative_to(pdir).as_posix().encode("utf-8")
        data = path.read_bytes()
        h.update(len(rel).to_bytes(4, "big") + rel + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


# --------------------------------------------------------------------------------------------- board state

def _state_path() -> Path:
    return storage.sub_dir("sim") / f"{SCENARIO}.json"


def board_state() -> dict[str, Any]:
    """What the simulated board runs: {"firmware": None | "panic" | "fixed" | "unknown", "elf_sha256", ...}."""
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"firmware": None}
    return state if isinstance(state, dict) else {"firmware": None}


def _save_state(state: Mapping[str, Any]) -> None:
    path = _state_path()
    fd, tmp = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(state), f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _builds() -> dict[str, dict[str, Any]]:
    """Last build per (folder, env) in this process: {"kind": "pio" | "sim", "sha", "elf", "crash"}."""
    return runtime.get("sim.builds", dict)


def _key(pdir: Path, env: str) -> str:
    return f"{pdir}\0{env}"


def _real_build_wanted() -> bool:
    """Real ``pio run`` for sim builds: in toolchain tests, and in the product (tests and project scripts set the
    development guard and get the fast simulated build)."""
    if os.environ.get("CB_TOOLCHAIN_TESTS") == "1":
        return True
    return os.environ.get(storage.ENV_DEV_GUARD) != "1"


def _pio() -> str | None:
    return clitools.find("pio", _settings.load().get("pio_path") or None)


_PLATFORM_RE = re.compile(r"^[ \t]*platform[ \t]*=[ \t]*(?:platformio/)?espressif32(?:@([^\s;#]+))?", re.MULTILINE)


def _platform_installed(pdir: Path) -> tuple[bool, str]:
    """Is the PlatformIO platform of ``platformio.ini`` already installed? A sim build never makes pio download a
    platform (hundreds of MB): without it the build is simulated. Returns (installed, wanted spec)."""
    try:
        m = _PLATFORM_RE.search((pdir / "platformio.ini").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False, "espressif32"
    want = (m.group(1) if m else None) or None
    spec = f"espressif32@{want}" if want else "espressif32"
    # folders espressif32 and espressif32@<version> (several versions side by side)
    return board.installed_platform(want) is not None, spec


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
# PlatformIO MCU names per architecture from the chip register (data/chips.json pio_mcu/arch). espressif32 6.9.0
# platform.py additionally needs the RISC-V toolchain for the RISC-V ULP of the S2/S3 (pio-esp32-6.9.0-platform-py:
# 'if mcu in ("esp32s2", "esp32s3", "esp32c3", "esp32c6")').
_RISCV_ULP_MCUS = ("esp32s2", "esp32s3")
_XTENSA_MCUS = tuple(chips.get(c)["pio_mcu"] for c in chips.ids() if chips.arch(c) == "xtensa")
_RISCV_MCUS = tuple(dict.fromkeys([*_RISCV_ULP_MCUS,
                                   *(chips.get(c)["pio_mcu"] for c in chips.ids() if chips.arch(c) == "riscv")]))
_LIBS_PKG = "framework-arduinoespressif32-{mcu}-libs"  # espressif32 8.0.0: Arduino libs per MCU


def _version(text: Any) -> tuple[int, int, int] | None:
    m = _VERSION_RE.match(str(text or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _satisfies(installed: Any, spec: Any) -> bool:
    """PlatformIO package requirement as platform.json writes it: ``~X.Y.Z``, ``^X.Y.Z`` or an exact version.
    Anything else (URLs, wildcards) counts as not satisfied: the sim build then stays simulated (conservative)."""
    have, spec = _version(installed), str(spec or "").strip()
    if have is None or not spec:
        return False
    if spec[0] in "~^":
        want = _version(spec[1:])
        if want is None:
            return False
        upper = (want[0], want[1] + 1, 0) if spec[0] == "~" else (want[0] + 1, 0, 0)
        return want <= have < upper
    return str(installed).strip() == spec or (_version(spec) == have and "+" not in spec)


def _package_installed(packages_dir: Path, name: str, spec: str | None) -> bool:
    for pj in [packages_dir / name / "package.json", *packages_dir.glob(f"{name}@*/package.json")]:
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("name") == name and (spec is None or _satisfies(data.get("version"), spec)):
            return True
    return False


def _env_options(pdir: Path, env: str) -> dict[str, str] | None:
    """Options of [env:<env>] (``board.pio_env_options``: [env] and ``extends`` merged, None if not certain)."""
    return board.pio_env_options(pdir, env)


def _list(value: str | None) -> list[str]:
    return board.ini_list(value)


def _offline_ready(pdir: Path, env: str) -> tuple[bool, list[str]]:
    """Can ``pio run`` build ``env`` without downloading anything? (ready, what is missing or unclear).

    Needed besides the platform (espressif32 ``platform.json`` and ``platform.py`` ``configure_default_packages``,
    PlatformIO Core 6.2.0 ``platform/base.py`` and ``platform/_run.py``):
    - ``tool-scons`` (core package; PlatformIO installs it on the first build);
    - every package of platform.json that is not optional, and the framework package (``frameworks.<f>.package``);
    - espressif32 6.x (pio-esp32-6.9.0-platform-json/-py), arduino: ``toolchain-xtensa-<mcu>`` for the Xtensa chips
      (the other Xtensa toolchains are dropped), ``toolchain-riscv32-esp`` for esp32s2/s3/c3/c6;
    - espressif32 8.x (pio-esp32-8.0.0-platform-json/-py; recognised by its ``framework-arduinoespressif32-*-libs``
      packages): the unified toolchains ``toolchain-xtensa-esp-elf``/``toolchain-riscv32-esp`` and the GDB packages
      are not optional for every MCU, plus ``framework-arduinoespressif32-<mcu>-libs`` for arduino;
    - both: ``toolchain-esp32ulp`` with a ``ulp/`` folder, ``tool-openocd-esp32`` with ``upload_protocol``;
      ``tool-dfuutil-arduino`` only for arduino_nano_esp32.
    MCU lists come from the chip register (bench_core.chips); an MCU outside it is never ready. ESP-IDF projects,
    ``platform_packages``, ``lib_deps`` and ini files that pull in other files are never ready (their packages
    cannot be known without pio). The platform is the one pio would use: the highest installed version that
    satisfies the pin (``board.installed_platform``)."""
    installed, spec = _platform_installed(pdir)
    if not installed:
        return False, [spec]
    opts = _env_options(pdir, env)
    if opts is None:
        return False, ["platformio.ini (extra_configs, extends or PlatformIO folders)"]
    for key in ("platform_packages", "lib_deps"):
        if _list(opts.get(key)):
            return False, [f"{key} of [env:{env}]"]
    frameworks = [f.lower() for f in _list(opts.get("framework"))]
    if frameworks != ["arduino"]:
        return False, [f"framework {', '.join(frameworks) or 'none'} (only arduino is checked offline)"]
    packages = board.pio_dirs()["packages"]
    want = spec.split("@", 1)[1] if "@" in spec else None
    hit = board.installed_platform(want)
    if hit is None:
        return False, [spec]
    platform_dir, manifest = hit
    board_id = (opts.get("board") or "").strip()
    try:
        board_json = json.loads((platform_dir / "boards" / f"{board_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, [f"board {board_id or '?'} (not in the platform's boards)"]
    mcu = (opts.get("board_build.mcu") or (board_json.get("build") or {}).get("mcu") or "esp32").strip().lower()
    if mcu not in (*_XTENSA_MCUS, *_RISCV_MCUS):
        return False, [f"mcu {mcu} (not a chip of the register: {chips.ids_text()})"]
    pkgs: dict[str, dict[str, Any]] = manifest.get("packages") or {}
    need = {name for name, o in pkgs.items() if not o.get("optional")}
    fw_pkg = ((manifest.get("frameworks") or {}).get("arduino") or {}).get("package")
    if fw_pkg:
        need.add(fw_pkg)
    if any(re.fullmatch(r"framework-arduinoespressif32-[a-z0-9]+-libs", n) for n in pkgs):  # 8.x schema
        need.add(_LIBS_PKG.format(mcu=mcu))
    else:  # 6.x schema
        need -= {f"toolchain-xtensa-{m}" for m in _XTENSA_MCUS if m != mcu}
        if mcu in _XTENSA_MCUS:
            need.add(f"toolchain-xtensa-{mcu}")
        if mcu in _RISCV_MCUS:
            need.add("toolchain-riscv32-esp")
    if (pdir / "ulp").is_dir():
        need.add("toolchain-esp32ulp")
    if (opts.get("upload_protocol") or "").strip():
        need.add("tool-openocd-esp32")
    if board_id != "arduino_nano_esp32":
        need.discard("tool-dfuutil-arduino")
    missing = sorted(n for n in need if n not in pkgs or not _package_installed(packages, n, pkgs[n].get("version")))
    if not _package_installed(packages, "tool-scons", None):
        missing.append("tool-scons")
    return not missing, missing


# --------------------------------------------------------------------------------------------- provider

def _real_build_ready(pdir: Path, env: str) -> tuple[bool, list[str]]:
    """Would a sim build run ``pio`` for ``env``? (ready, what is missing or unclear). One condition for the build
    itself and for the prediction that decides whether the caller must ask first."""
    if not (_real_build_wanted() and _pio()):
        return False, []
    return _offline_ready(pdir, env)


class SimBoard:
    """Provider for ``sim://`` (protocol in board.py): one simulated ESP32-S3 N16R8 on a DevKitC-1."""

    def ports(self) -> list[dict[str, Any]]:
        return [{"device": PORT, "description": "Simulated ESP32-S3 N16R8 (DevKitC-1)", "kind": "sim",
                 "likely_esp": True, "simulated": True}]

    def detect(self, port: str) -> dict[str, Any]:
        port = _check_port(port)
        data = dict(_data("detect.json"))
        log = [line.replace("{port}", port) for line in data.pop("log_tail", [])]
        result = {"port": port, **data, "log_tail": log, "at": _now(), "simulated": True}
        summary = (f"Detected {data['chip']} on {port} (simulated): {data['flash_size']} flash, "
                   f"variant {data['variant_suggestion']} suggested.")
        return envelope("board.detect", summary, result,
                        checks=[check("board.detect", "passed", "simulated esptool flash-id answer")],
                        assumptions=[assumption("mac", data["mac"], "simulated board: placeholder MAC, not a device")],
                        simulated=True)

    def build_runs_pio(self, project_dir: str, env: str) -> bool:
        """Does ``build`` start PlatformIO (and so the project's own scripts) for this folder and env?"""
        try:
            pdir = _project_dir(project_dir)
            return _real_build_ready(pdir, _env(pdir, env))[0]
        except BenchError:
            return False  # bad folder or env: build() refuses before anything starts

    def build(self, project_dir: str, env: str) -> dict[str, Any]:
        pdir = _project_dir(project_dir)
        env = _env(pdir, env)
        crash = demo_crash(pdir)
        ready, missing = _real_build_ready(pdir, env)
        if ready:
            return self._real_build(pdir, env, crash)
        if not any(p.suffix in (".c", ".cpp", ".cc", ".ino", ".S") for p in _source_files(pdir)):
            raise BenchError("tool_failed", "simulated build: no source files in src/", "add src/main.cpp")
        data = _data("build.json")
        sha = source_sha256(pdir)
        _sleep(BUILD_S)
        elf = data["elf"].replace("{env}", env)
        result = {"ok": True, "duration_s": data["duration_s"], "ram_pct": data["ram_pct"],
                  "flash_pct": data["flash_pct"], "log_ref": None,
                  "log_tail": [line.replace("{env}", env) for line in data["log_tail"]],
                  "elf": elf, "elf_path": str(pdir / elf), "elf_sha256": sha,
                  "ram_used": data["ram_used"], "ram_total": data["ram_total"], "flash_used": data["flash_used"],
                  "flash_total": data["flash_total"], "env": env, "project_dir": str(pdir), "addr2line": None,
                  "toolchain_prefix": "xtensa-esp32s3-elf", "toolchain": "simulated", "simulated": True}
        _builds()[_key(pdir, env)] = {"kind": "sim", "sha": sha, "elf": None, "crash": crash}
        checks = [check("board.build", "passed", f"simulated build of env {env}, firmware {sha[:8]}"),
                  check("sim.build.compile", "skipped", "simulated build: no compiler ran")]
        assum = [assumption("elf_sha256", sha[:16], "simulated build: SHA-256 of the project sources, no ELF exists"),
                 assumption("sizes", f"RAM {data['ram_pct']} %, flash {data['flash_pct']} %",
                            "taken from a real offline build of the example, not from this source")]
        if missing and missing[0].startswith("espressif32"):
            assum.append(assumption("platform", missing[0], "PlatformIO is installed but this platform is not: "
                                    f"the build is simulated (`pio pkg install -p {missing[0]}` for a real one)"))
        elif missing:
            assum.append(assumption("packages", ", ".join(missing)[:200], "a real build would download or needs "
                                    "packages that are not installed: the build is simulated (`pio pkg install "
                                    f"-d <firmware folder> -e {env}` for a real one)"))
        summary = f"Build ok (simulated): RAM {data['ram_pct']:g} %, flash {data['flash_pct']:g} %, firmware {sha[:8]}…."
        warns = [] if crash is not None else [_not_demo_warning(sha)]
        return envelope("board.build", summary, result, checks=checks, warnings=warns, assumptions=assum, simulated=True)

    def _real_build(self, pdir: Path, env: str, crash: bool | None) -> dict[str, Any]:
        out = dict(board.build(pdir, env))  # real offline build (no port: never the provider again)
        out["simulated"] = True
        key = _key(pdir, env)
        if not out.get("ok"):
            _builds().pop(key, None)
            return out
        res = dict(out["result"])
        res["toolchain"] = "pio"
        res["simulated"] = True
        out["result"] = res
        _builds()[key] = {"kind": "pio", "sha": res["elf_sha256"], "elf": res.get("elf_path"), "crash": crash}
        out["checks"] = [*out.get("checks", []),
                         check("sim.build.compile", "passed", "real offline pio build; the board and the upload are simulated")]
        out["summary"] = str(out["summary"]).rstrip(".") + " (real build, simulated board)."
        return out

    def elf_sha256(self, project_dir: str, env: str) -> str:
        pdir = _project_dir(project_dir)
        rec = _builds().get(_key(pdir, env))
        if rec and rec["kind"] == "pio" and rec.get("elf") and Path(rec["elf"]).is_file():
            return board.sha256_file(rec["elf"])
        return source_sha256(pdir)

    def flash(self, project_dir: str, env: str, port: str) -> dict[str, Any]:
        port = _check_port(port)
        pdir = _project_dir(project_dir)
        env = _env(pdir, env)
        sha = self.elf_sha256(str(pdir), env)
        rec = _builds().get(_key(pdir, env))
        crash = rec["crash"] if rec and rec["sha"] == sha else demo_crash(pdir)
        mac = _data("detect.json")["mac"]
        start = time.monotonic()
        log = ["esptool.py v4.5.1 (simulated)", f"Serial port {port}", "Connecting...",
               "Chip is ESP32-S3 (revision v0.2)", f"MAC: {mac}", "Configuring flash size..."]
        for pct, addr in ((10, 0x10000), (40, 0x20000), (70, 0x30000), (100, 0x40000)):
            _sleep(FLASH_STEP_S)
            log.append(f"Writing at 0x{addr:08x}... ({pct} %)")
        log += ["Hash of data verified.", "Leaving...", "Hard resetting via RTS pin... (simulated)"]
        firmware = "unknown" if crash is None else ("panic" if crash else "fixed")
        _save_state({"firmware": firmware, "elf_sha256": sha, "project_dir": str(pdir), "env": env, "at": _now()})
        result = {"ok": True, "port": port, "mac": mac, "elf_sha256": sha,
                  "duration_s": round(time.monotonic() - start, 2), "verified": False, "log_ref": None,
                  "log_tail": log, "simulated": True}
        checks = [check("board.flash.elf_hash", "passed", f"firmware matches the approved build ({sha[:8]}…)"),
                  check("board.flash.verified", "not_checked", "simulated: nothing was written")]
        warns = [] if firmware != "unknown" else [_not_demo_warning(sha)]
        return envelope("board.flash", f"Flashed firmware ({sha[:8]}…) to {port} (simulated).", result,
                        checks=checks, warnings=warns, simulated=True)

    def line_source(self, port: str) -> Iterator[str]:
        _check_port(port)
        return _play(board_state())

    def monitor_notes(self, port: str) -> dict[str, Any]:
        """Where the monitor lines of the simulated board come from (serialport.monitor adds this to its answer):
        ``lines_source`` (``demo_firmware`` or ``rom_boot_only``), assumptions and warnings."""
        _check_port(port)
        state = board_state()
        firmware = state.get("firmware")
        sha8 = str(state.get("elf_sha256") or "")[:8]
        notes = [assumption("lines", "synthetic", "simulated board: the lines are a fixed script of the simulator, "
                            "not read from a device and not produced by running code")]
        warns: list[dict[str, Any]] = []
        if firmware in ("panic", "fixed"):
            source = "demo_firmware"
            log = "panic.log (DEMO_CRASH 1, reboot loop)" if firmware == "panic" else "fixed.log (crash fixed)"
            notes.append(assumption("lines_source", "demo firmware script", f"the flashed source ({sha8}…) is the "
                                    f"demo firmware (bench_project demo); the simulator replays {log}"))
        elif firmware == "unknown":
            source = "rom_boot_only"
            warns.append(_not_demo_warning(state.get("elf_sha256")))
        else:
            source = "rom_boot_only"
            notes.append(assumption("lines_source", "ROM boot only", "nothing was flashed to the simulated board yet; "
                                    "only the ROM boot lines appear"))
        return {"lines_source": source, "assumptions": notes, "warnings": warns}


def _not_demo_warning(sha: Any) -> dict[str, Any]:
    return warning("sim_not_demo_firmware", "caution",
                   f"The simulated board only emulates the demo firmware (bench_project demo); the flashed firmware "
                   f"({str(sha or '')[:8]}…) is not it, so the monitor shows only the ROM boot and never a panic. "
                   "The lines are not output of your code.")


def _lines(lines: tuple[str, ...] | list[str]) -> Iterator[str]:
    for line in lines:
        _sleep(LINE_DELAY_S)
        yield line


# Reboot after a panic. OBSERVATION, not backed by data/sources/crash.json: the ESP-IDF v6.1 docs there
# (fatal-errors.rst) only show ``rst:0x10`` for the RTC watchdog; that a panic restart (esp_restart from the panic
# handler) boots with ``rst:0xc (RTC_SW_CPU_RST)`` and the ROM prints ``Saved PC:`` is the usual ESP32-S3 console
# output, here with an invented address. crash.py only reads the name from the log (reset_reason, after_crash).
PANIC_RESET_LINE = "rst:0xc (RTC_SW_CPU_RST),boot:0x8 (SPI_FAST_FLASH_BOOT)"
PANIC_SAVED_PC = "Saved PC:0x40377ab6"
POWERON_PREFIX = "rst:0x1 (POWERON)"


def _reboot_after_panic(boot: tuple[str, ...]) -> list[str]:
    """The ROM boot lines after a panic restart: the POWERON reset line becomes RTC_SW_CPU_RST, followed by Saved PC.
    boot.log is a shortened ROM banner; on the reboot the Saved PC line takes the place of its ``load:`` line, so the
    reboot banner keeps the length of the first one (line numbers of the demo serial fixture stay put)."""
    out: list[str] = []
    for line in boot:
        if line.startswith(POWERON_PREFIX):
            out += [PANIC_RESET_LINE, PANIC_SAVED_PC]
        elif not line.startswith("load:"):
            out.append(line)
    return out


def _play(state: Mapping[str, Any]) -> Iterator[str]:
    """Serial output of the simulated board after a reset; ends with the log (bounded loop). Only the first boot is a
    power-on reset; every boot after a panic is a software CPU reset (``_reboot_after_panic``)."""
    boot = _log("boot.log")
    firmware = state.get("firmware")
    if firmware == "panic":
        sha16 = str(state.get("elf_sha256") or "0" * 16)[:16]
        panic = [line.replace("{elf_sha16}", sha16) for line in _log("panic.log")]
        reboot = _reboot_after_panic(boot)
        for i in range(PANIC_LOOPS):
            yield from _lines(boot if i == 0 else reboot)
            _sleep(APP_START_S)
            yield from _lines(panic)
            _sleep(REBOOT_S)
    elif firmware == "fixed":
        yield from _lines(boot)
        _sleep(APP_START_S)
        yield from _lines(_log("fixed.log"))
    else:
        yield from _lines(boot)  # nothing flashed yet, or not the demo firmware (unknown): only the ROM boot


def register() -> None:
    """Register the provider for ``sim://`` ports (called lazily by board.provider_for / board.list_ports)."""
    board.register_provider(PREFIX, SimBoard())


# --------------------------------------------------------------------------------------------- crash decoding

def _framework_dir(project_dir: str | Path | None = None, *, core: str | Path | None = None) -> str:
    """Folder of the Arduino framework package the sim firmware builds with (``{framework}`` in decode.json).

    PlatformIO keeps several versions side by side (``framework-arduinoespressif32`` and
    ``framework-arduinoespressif32@<version>``); the right one satisfies the framework requirement of the platform
    the firmware pins (platform.json ``packages.<frameworks.arduino.package>.version`` of that espressif32 folder),
    the highest such version if several do. ``project_dir``: the firmware (default: the example laser-trigger);
    ``core``: PlatformIO core folder (default: PLATFORMIO_CORE_DIR, else ~/.platformio, with
    PLATFORMIO_PLATFORMS_DIR/PACKAGES_DIR). Falls back to the folder without a version suffix."""
    if core is not None:
        core_dir = Path(core).expanduser()
        dirs = {"platforms": core_dir / "platforms", "packages": core_dir / "packages"}
    else:
        core_dir = Path(os.environ.get("PLATFORMIO_CORE_DIR")
                        or os.path.join(os.environ.get("HOME") or "~", ".platformio")).expanduser()
        dirs = {"platforms": Path(os.environ.get("PLATFORMIO_PLATFORMS_DIR") or core_dir / "platforms"),
                "packages": Path(os.environ.get("PLATFORMIO_PACKAGES_DIR") or core_dir / "packages")}
    name = "framework-arduinoespressif32"
    ini = Path(project_dir).expanduser() if project_dir else EXAMPLES_DIR / "laser-trigger"
    try:
        m = _PLATFORM_RE.search((ini / "platformio.ini").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    hit = board.installed_platform((m.group(1) if m else None) or None, platforms_dir=dirs["platforms"])
    if hit is not None:
        manifest = hit[1]
        name = ((manifest.get("frameworks") or {}).get("arduino") or {}).get("package") or name
        req = ((manifest.get("packages") or {}).get(name) or {}).get("version")
        best: tuple[tuple[int, int, int], Path] | None = None
        for pj in [dirs["packages"] / name / "package.json", *sorted(dirs["packages"].glob(f"{name}@*/package.json"))]:
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            v = board.semver(data.get("version"))
            if data.get("name") == name and v is not None and (req is None or _satisfies(data.get("version"), req)) \
                    and (best is None or v > best[0]):
                best = (v, pj.parent)
        if best is not None:
            return str(best[1])
    return str(dirs["packages"] / name)


def _project_of(project_dir: str | Path | None, elf: str) -> str | None:
    if project_dir:
        return str(Path(project_dir).expanduser())
    parts = Path(elf).parts
    if ".pio" in parts and Path(elf).is_absolute():
        return str(Path(*parts[:parts.index(".pio")]))
    return None


def crash_runner(project_dir: str | Path | None = None) -> Callable[..., dict[str, Any]]:
    """``run(argv, *, timeout, tail)`` for ``crash.decode``: answers ``<tool> -pfiaC -e ELF ADDR...`` like GNU
    addr2line (``0x%08x: FUNC at FILE:LINE``, unknown addresses ``?? ??:0``) from decode.json. ``{project}`` is
    ``project_dir`` (else the folder above ``.pio`` in the ELF path, else a relative path)."""
    table = {int(k, 16): v for k, v in _data("decode.json")["addresses"].items()}

    def run(argv: Any, *, timeout: float | None = None, tail: int = 200, **_: Any) -> dict[str, Any]:
        args = [str(a) for a in argv]
        if len(args) < 4 or args[1:3] != ["-pfiaC", "-e"]:
            return {"rc": 2, "out_tail": ["simulated addr2line: expected -pfiaC -e ELF ADDR..."], "timed_out": False,
                    "duration_s": 0.0}
        proj = _project_of(project_dir, args[3])
        fw = _framework_dir(proj if proj and (Path(proj) / "platformio.ini").is_file() else None)
        out: list[str] = []
        for raw in args[4:]:
            try:
                addr = int(raw, 16)
            except ValueError:
                out.append(f"{raw}: ?? ??:0")
                continue
            answer = table.get(addr)
            if answer is None:
                out.append(f"0x{addr:08x}: ?? ??:0")
                continue
            answer = answer.replace("{framework}", fw)
            answer = answer.replace("{project}", proj) if proj else answer.replace("{project}/", "")
            out.append(f"0x{addr:08x}: {answer}")
        return {"rc": 0, "out_tail": out[-tail:] if tail else out, "timed_out": False, "duration_s": 0.0}

    run.simulated = True  # type: ignore[attr-defined]  # lets callers mark the decode result as simulated
    return run


def decode(log: str, *, elf: str | Path | None = None, project_dir: str | Path | None = None,
           chip: str | None = "esp32s3", **kwargs: Any) -> dict[str, Any]:
    """``crash.decode`` with ``run=crash_runner(project_dir)`` for a simulated project; the envelope is marked
    ``simulated: true`` and names the simulated addr2line in its assumptions."""
    # crash.decode marks the result simulated and names the simulated addr2line (run.simulated)
    return crash.decode(log, elf=elf, chip=chip, project_dir=project_dir, run=crash_runner(project_dir), **kwargs)


# --------------------------------------------------------------------------------------------- demo project

def _calc_error(cid: str, env: Mapping[str, Any]) -> BenchError:
    err = env.get("error") or {}
    return BenchError(err.get("code", "tool_failed"), f"demo calculation {cid}: {err.get('message', 'failed')}")


def _value_of(res: Mapping[str, Any], key: str) -> float:
    q = res["inputs"][key]
    return float(q["value"] if isinstance(q, Mapping) else q)


def _prepare(recipe: Mapping[str, Any]) -> dict[str, Any]:
    """Every computed piece of the demo project (nothing is written yet)."""
    calcs: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    srcs: list[dict[str, Any]] = []
    for c in recipe["calcs"]:
        env = _CALCS[c["type"]](**c["args"])
        if not env["ok"]:
            raise _calc_error(c["id"], env)
        res = env["result"]
        # stored without the step list (keeps project.json small); the inputs reproduce it with bench_calc
        calcs.append({"id": c["id"], "type": c["type"], "inputs": dict(c["args"]),
                      "result": {"summary": env["summary"], "checks": env["checks"],
                                 **{k: v for k, v in res.items() if k not in ("inputs", "steps")}},
                      "assumptions": env["assumptions"], "sources": [s["id"] for s in env["sources"]]})
        for p in c["parts"]:
            part = {"ref": p["ref"], "kind": p["kind"], "from_calc": c["id"]}
            part["value"] = schematic.format_ohms(_value_of(res, p["ohms"])) if "ohms" in p else p["value"]
            if "package" in p:
                part["package"] = p["package"]
            parts.append(part)
        warns += env["warnings"]
        srcs += env["sources"]
    parts += [dict(p) for p in recipe["parts"]]
    plan = solder.plan([{k: p[k] for k in ("ref", "kind", "value", "package") if k in p} for p in parts])
    if not plan["ok"]:
        raise _calc_error("solder", plan)
    warns += plan["warnings"]
    srcs += plan["sources"]
    circuits: list[tuple[dict[str, Any], str | None]] = []
    for c in recipe["circuits"]:
        env = schematic.render(c["block"], c["params"], devkit=recipe["devkit"], gpio=c["gpio"])
        if not env["ok"]:
            if env["error"]["code"] != "dependency_missing":
                raise _calc_error(c["id"], env)
            warns.append(warning("schematic_missing", "info", f"schematic {c['id']} not drawn: {env['error']['message']}"))
            circuits.append(({"id": c["id"], "block": c["block"], "params": dict(c["params"]), "svg": None}, None))
            continue
        warns += env["warnings"]
        srcs += env["sources"]
        circuits.append(({"id": c["id"], "block": c["block"], "params": dict(c["params"]),
                          "svg": f"artifacts/{c['id']}.svg"}, env["result"]["svg"]))
    return {"calcs": calcs, "parts": parts, "steps": plan["result"]["steps"], "circuits": circuits,
            "warnings": _dedupe(warns, "code"), "sources": _dedupe(srcs, "id")}


def _dedupe(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    out = []
    for item in items:
        if item.get(key) not in seen:
            seen.add(item.get(key))
            out.append(item)
    return out


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def copy_example(name: str, project_id: str) -> Path:
    """Copy ``data/examples/<name>`` to ``projects/<project_id>/firmware/`` (files are overwritten, nothing else is
    removed) and return the folder."""
    if not isinstance(name, str) or not _ID_RE.fullmatch(name) or not (EXAMPLES_DIR / name).is_dir():
        raise BenchError("invalid_args", f"no example {str(name)[:40]!r}", "examples: laser-trigger")
    dest = project.path(project_id) / "firmware"
    shutil.copytree(EXAMPLES_DIR / name, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".pio", "__pycache__", ".*"))
    return dest


def _demo_result(proj: Mapping[str, Any], created: bool) -> dict[str, Any]:
    """Short form of the project (answers stay below 8 kB; the whole project comes from project.get)."""
    b = proj["board"]
    return {"id": proj["id"], "title": proj["title"], "rev": proj["rev"], "created": created, "port": PORT,
            "simulated": proj["simulated"],
            "board": {k: b[k] for k in ("chip", "module", "variant", "devkit")},
            "assignments": [{k: a[k] for k in ("role", "mode", "pin", "verdict")} for a in proj["assignments"]],
            "parts": [f"{p['ref']} {p['value']}" for p in proj["parts"]],
            "calcs": [c["id"] for c in proj["calcs"]],
            "circuits": [{"id": c["id"], "block": c["block"], "svg": c["svg"]} for c in proj["circuits"]],
            "solder_steps": len(proj["solder"]["steps"]),
            "firmware_dir": proj["firmware"]["dir"], "env": proj["firmware"]["env"]}


def _relabel(env: Mapping[str, Any]) -> dict[str, Any]:
    err = env.get("error") or {}
    return fail(ACTION_DEMO, err.get("code", "tool_failed"), f"demo project: {err.get('message', 'failed')}",
                err.get("hint"), simulated=True)


def demo(project_id: str = DEMO_ID, *, by: str = "agent") -> dict[str, Any]:
    """Action sim.demo: the simulated demo project (S3 N16R8 on a DevKitC-1, laser trigger), built from
    ``data/demo/laser-trigger.project.json`` with bench_core (calc, pins, schematic, solder) and stored only through
    project.create/project.update. An existing project with this id is returned unchanged (same rev)."""
    try:
        if not isinstance(project_id, str) or not _ID_RE.fullmatch(project_id):
            raise BenchError("invalid_args", f"bad project id {str(project_id)[:60]!r}",
                             "project ids are 1 to 48 characters a-z, 0-9 and '-', e.g. laser-trigger")
        if by not in ("agent", "ui"):
            raise BenchError("invalid_args", "by must be agent or ui")
        existing = _existing(project_id)
        if existing is not None:
            return existing
        recipe = _recipe(project_id)
        prep = _prepare(recipe)
        made = project.create(project_id, recipe["title"], recipe["chip"], recipe["variant"], recipe["devkit"],
                              simulated=True, by=by)
        if not made["ok"]:
            if made["error"]["code"] == "project_conflict":  # created meanwhile by another caller
                existing = _existing(project_id)
                if existing is not None:
                    return existing
            return _relabel(made)
        fw_dir = copy_example(recipe["example"], project_id)
        art = project.artifacts_dir(project_id)
        for circuit, svg in prep["circuits"]:
            if svg is not None:
                _write_private(art / f"{circuit['id']}.svg", svg)
        ops: list[dict[str, Any]] = [{"op": "set_board", "wifi": bool(recipe["wifi"])}]
        ops += [{"op": "assign", **a} for a in recipe["assignments"]]
        ops.append({"op": "add_parts", "parts": prep["parts"]})
        ops += [{"op": "add_calc", "calc": c} for c in prep["calcs"]]
        ops += [{"op": "add_circuit", "circuit": c} for c, _ in prep["circuits"]]
        ops.append({"op": "set_solder_plan", "steps": prep["steps"]})
        ops.append({"op": "set_firmware", "dir": str(fw_dir), "env": recipe["env"]})
        ops += [{"op": "note", "text": n} for n in recipe["notes"]]
        upd = project.update(project_id, made["result"]["rev"], ops, by=by)
        if not upd["ok"]:
            return _relabel(upd)
    except BenchError as e:
        return from_error(ACTION_DEMO, e, simulated=True)
    except Exception as e:  # an action returns an envelope, never an exception (logged)
        logger.error("circuit-bench: sim.demo failed", exc_info=e)
        return fail(ACTION_DEMO, "tool_failed", f"demo project failed ({type(e).__name__})", "see the Hermes log",
                    simulated=True)
    proj = upd["result"]["project"]
    pins_ok = sum(1 for a in proj["assignments"] if a["verdict"] == "ok")
    summary = (f"Demo project {project_id!r} created (simulated ESP32-S3 N16R8 on {PORT}): {pins_ok} of "
               f"{len(proj['assignments'])} pins ok, {len(proj['parts'])} parts, {len(proj['solder']['steps'])} "
               f"solder steps, example firmware copied to firmware/. Next: detect, build and flash on {PORT}.")
    srcs = _dedupe([*prep["sources"], *upd["sources"]], "id")
    checks = [check("sim.demo.pins", "passed" if pins_ok == len(proj["assignments"]) else "failed",
                    f"{pins_ok} of {len(proj['assignments'])} assignments ok (pins.check)")]
    return envelope(ACTION_DEMO, summary, _demo_result(proj, True), checks=checks,
                    warnings=_dedupe([*upd["warnings"], *prep["warnings"]], "code"),
                    assumptions=[assumption("board", PORT, "simulated board: no hardware is used")],
                    sources=srcs, simulated=True)


def _existing(project_id: str) -> dict[str, Any] | None:
    got = project.get(project_id)
    if got["ok"]:
        proj = got["result"]["project"]
        return envelope(ACTION_DEMO, f"Demo project {project_id!r} already exists (rev {proj['rev']}); left unchanged.",
                        _demo_result(proj, False), warnings=got["warnings"], simulated=True)
    if got["error"]["code"] == "project_not_found":
        return None
    return _relabel(got)

"""Board tools: ports, detection, build and flash, port providers.

Public action functions return the result envelope: ``ports()``, ``detect()``, ``build()``, ``flash()``.
Helpers return raw data and raise ``BenchError``: ``list_ports()``, ``metadata()``, ``classify_usb()``,
``parse_flash_id()``, ``parse_sizes()``, ``register_provider()``, ``provider_for()``.

- Tools run only through ``clitools.run``/``clitools.find`` (minimal environment, own process group, time limit).
- Hardware switch: with ``CIRCUIT_BENCH_HW=off`` or ``hardware_access=false`` only provider ports
  (``sim://``) exist; ``detect``/``flash`` of a real port end with ``sim_only`` before any tool runs.
- ``flash`` never builds and never erases: ``esptool write-flash`` writes exactly the approved images (bootloader,
  partition table, boot_app0 and the app at the offsets of ``pio project metadata``) after the ELF and image hashes
  were checked again; the approval check (``guard``) runs before any tool. Observed on a WT32-ETH01 (2026-11-07): the
  former ``pio run -t nobuild -t upload`` wrote only the app at 0x10000, because PlatformIO does not run the
  framework script under ``nobuild`` and the extra images stay unknown; a board with another partition table
  (WT32 factory app at 0x20000) then did not boot.
- Chip register: ``chip_id`` of a detection comes from the chip register
  (``chips.by_esptool_name``, ``chip_from_esptool``); ``build(..., chip=)`` checks the env's MCU and the pinned
  platform before pio starts (``build_precheck``: ``chip_mismatch``, ``platform_too_old``, ``platform_unpinned``);
  ``detect``/``flash`` take ``devkit=`` and use the board's ``flash_hint`` for connection errors.

Provider protocol (``register_provider(prefix, provider)``, used by sim.py for ``sim://``):
    ports() -> list[dict | str]          entries: device (required), description, kind, likely_esp, simulated
    detect(port) -> dict                 fields of project ``board.detected`` (or a full result envelope)
    build(project_dir, env) -> dict      fields like ``build()``'s result (or a full result envelope)
    flash(project_dir, env, port) -> dict  fields like ``flash()``'s result (or a full result envelope)
    line_source(port) -> Iterator[str]   serial lines for the broker (serialport.Broker)
    elf_sha256(project_dir, env) -> str  optional: lets ``flash`` refuse a changed firmware (elf_mismatch)
Provider results are marked ``simulated: true`` unless the provider says otherwise.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import math
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import boards, chips, clitools, runtime, serialport, sources
from . import settings as _settings
from .contracts import BenchError, check, envelope, fail, from_error, validate_envelope, warning

logger = logging.getLogger(__name__)

DETECT_TIMEOUT_S = 30.0
METADATA_TIMEOUT_S = 120.0
CONFIG_TIMEOUT_S = 60.0
FLASH_TIMEOUT_S = 300.0
IMAGE_INFO_TIMEOUT_S = 30.0
FLASH_BAUD = 460800  # PlatformIO's upload_speed of the espressif32 boards; the env's upload_speed wins
LOG_TAIL_LINES = 12
LOG_LINE_CHARS = 200  # answers stay below contracts.MAX_RESULT_BYTES
BEFORE_MODES = ("default-reset", "usb-reset", "no-reset")

NO_AUTO_RESET_HINT = ("The board runs firmware with its own USB stack and cannot be reset automatically. Hold BOOT, "
                      "tap RESET (or replug while holding BOOT), release BOOT, then retry; or use the board's "
                      "UART/COM USB port.")
BOOTLOADER_HINT = ("esptool got no answer from the ROM bootloader. Hold BOOT, tap RESET (or replug while holding "
                   "BOOT), release BOOT, then retry; check the cable and that this is the board's port.")
# Observed on an ESP32-S3 on its USB-Serial/JTAG (2026-11-06): with firmware in a panic reboot loop the automatic reset
# into the bootloader failed twice ("A serial exception error occurred: Write timeout" after ~40 s, nothing written);
# from the bootloader (BOOT held, RESET tapped) the flash went through. Board-observed.
WRITE_TIMEOUT_HINT = ("The board did not enter its bootloader (nothing was written). A firmware in a crash loop can "
                      "prevent the automatic reset: hold BOOT, tap RESET, release BOOT, then flash again.")

_SRC_USB_IDS = "board-usb-ids-2026.06.26"
_SRC_WCH = "board-wch-ch343ser-linux"
_SRC_PYLIB = "board-esp-pylib-1.2.0-usb"
_SRC_RESET = "board-esptool-5.6.0-usb-reset"
_SRC_TINYUSB = "board-esp-usb-tinyusb-pid"
_SRC_OBSERVED = "board-observed-2026-11-06-usb-cdc-app"
_SRC_BOOT = "board-esptool-boot-mode"
_SRC_ESPTOOL_OUT = "board-esptool-5.6.0-output"
_SRC_FLASH_IMAGES = "board-pio-6.2.0-flash-images"
_SRC_UPLOAD_ARGS = "board-pio-espressif32-6.9.0-upload-args"
_SRC_WRITE_FLASH = "board-esptool-5.6.0-write-flash"
_SRC_OBSERVED_WT32 = "board-observed-2026-11-07-app-only"
_SRC_METADATA = "board-pio-6.2.0-metadata"
_SRC_BOARDS_DIR = "cflash-pio-boards-dir"
_SRC_GET_PACKAGE = "cflash-pio-6.2.0-get-package"
_ESPTOOL_TARGET_SRC = "esptool-5.6.0-target-"  # + chip id (data/sources/chips.json)

_ESPRESSIF_VID = 0x303A
# (vid, pid) -> (kind, label, likely_esp, source ids). Every entry is backed by data/sources/board.json.
_USB_TABLE: dict[tuple[int, int], tuple[str, str, bool, tuple[str, ...]]] = {
    (0x303A, 0x1001): ("usb_serial_jtag", "ESP32 USB-Serial/JTAG", True, (_SRC_PYLIB, _SRC_RESET)),
    (0x10C4, 0xEA60): ("cp210x", "CP210x USB-UART", True, (_SRC_USB_IDS,)),
    (0x10C4, 0xEA61): ("cp210x", "CP210x USB-UART", True, (_SRC_USB_IDS,)),
    (0x10C4, 0xEA63): ("cp210x", "CP210x USB-UART", True, (_SRC_USB_IDS,)),
    (0x10C4, 0xEA70): ("cp210x", "CP2105 dual USB-UART", True, (_SRC_USB_IDS,)),
    (0x10C4, 0xEA71): ("cp210x", "CP2108 quad USB-UART", True, (_SRC_USB_IDS,)),
    (0x1A86, 0x7522): ("ch340", "CH340 USB-UART", True, (_SRC_USB_IDS,)),
    (0x1A86, 0x7523): ("ch340", "CH340 USB-UART", True, (_SRC_USB_IDS,)),
    (0x1A86, 0x5523): ("ch340", "CH341 USB-UART", True, (_SRC_USB_IDS,)),
    (0x1A86, 0x55D3): ("ch343", "CH343 USB-UART", True, (_SRC_WCH,)),
    (0x1A86, 0x55D4): ("ch9102", "CH9102 USB-UART", True, (_SRC_WCH,)),
    (0x0403, 0x6001): ("ftdi", "FTDI FT232 USB-UART", True, (_SRC_USB_IDS,)),
    (0x0403, 0x6010): ("ftdi", "FTDI FT2232 USB-UART", True, (_SRC_USB_IDS,)),
    (0x0403, 0x6011): ("ftdi", "FTDI FT4232H USB-UART", True, (_SRC_USB_IDS,)),
    (0x0403, 0x6014): ("ftdi", "FTDI FT232H USB-UART", True, (_SRC_USB_IDS,)),
    (0x0403, 0x6015): ("ftdi", "FTDI FT-X USB-UART", True, (_SRC_USB_IDS,)),
}
_KIND_LABELS = {"usb_cdc_app": "ESP32 firmware USB CDC, no auto-reset", "unknown": "unknown USB serial", "sim": "simulated"}

_ENV_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PSRAM_RE = re.compile(r"Embedded PSRAM (\d+)MB(?: \(([^)]*)\))?")
_EMB_FLASH_RE = re.compile(r"Embedded Flash (\d+)MB(?: \(([^)]*)\))?")
_MHZ_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MHz")
_CONNECTED_RE = re.compile(r"^Connected to (\S+) on ")
_DETECTING_RE = re.compile(r"^Detecting chip type\.*\s*(\S+)")
_MAC_RE = re.compile(r"^MAC:\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5,7})\s*$")
# esptool lines that show it started erasing or writing flash (5.6.0: "Flash will be erased ...", "Writing at ...",
# "Wrote ..."; 4.x: "Compressed ... bytes to ..."); a stop at a foreign MAC after one of them may have written
_WRITE_LINE_RE = re.compile(r"^(?:Writing at|Flash will be erased|Compressed|Wrote) ")
_USB_SERIAL_MAX = 64
_SIZE_RE = re.compile(r"^(RAM|Flash):\s*\[[^\]]*\]\s*([\d.]+)%(?:\s*\(used (\d+) bytes from (\d+) bytes\))?")
_COMPILE_ERR_RE = re.compile(r"^(.+?):(\d+)(?::(\d+))?: (?:fatal )?error: (.*)$")
_CONNECT_FAIL_RE = re.compile(r"No serial data received|Failed to connect|Wrong boot mode detected")
_WRITE_TIMEOUT_RE = re.compile(r"serial exception error occurred: Write timeout|SerialTimeoutException: Write timeout")
_OPEN_FAIL_RE = re.compile(r"Could not open .*port is busy or doesn't exist|could not open port", re.IGNORECASE)
_LABELS = ("Chip type", "Features", "Crystal frequency", "USB mode", "MAC", "BASE MAC", "MAC_EXT",
           "Manufacturer", "Device", "Detected flash size", "Flash type set in eFuse")
_ERASE_RE = re.compile(r"erase", re.IGNORECASE)
_OFFSET_RE = re.compile(r"^0x[0-9a-fA-F]{1,8}$")
# esptool 5.6.0 esptool/loader.py (connect, chip check): "This chip is ESP32-S3, not ESP32. Wrong chip argument?"
_WRONG_CHIP_RE = re.compile(r"This chip is (ESP32(?:-[A-Z0-9]+)?)[^,]*, not ESP32")
_IMAGE_INFO_RE = {"type": re.compile(r"^Detected image type:\s*(ESP32(?:-[A-Z0-9]+)?)\s*$"),
                  "flash_mode": re.compile(r"^Flash mode:\s*([A-Za-z]+)\s*$"),
                  "flash_freq": re.compile(r"^Flash freq:\s*([0-9]+m)\s*$")}


# --------------------------------------------------------------------------------------------- providers

def _providers() -> dict[str, Any]:
    return runtime.get("board.providers", dict)


def register_provider(prefix: str, provider: Any) -> None:
    """Route ports starting with ``prefix`` (e.g. ``"sim://"``) to ``provider`` (protocol: module docstring)."""
    if not isinstance(prefix, str) or not re.match(r"^[a-z][a-z0-9+.-]*://$", prefix):
        raise BenchError("invalid_args", f"bad provider prefix {prefix!r}", "use a URL scheme like 'sim://'")
    for name in ("ports", "detect", "build", "flash", "line_source"):
        if not callable(getattr(provider, name, None)):
            raise BenchError("invalid_args", f"provider for {prefix} lacks {name}()")
    _providers()[prefix] = provider


def _ensure_sim() -> None:
    """Load the sim provider once per process (lazy; no sim module -> no sim ports)."""
    state = runtime.get("board.sim_registered", lambda: {"done": False})
    if state["done"]:
        return
    state["done"] = True
    try:
        from . import sim  # simulated board, optional
    except ImportError:
        return
    try:
        sim.register()
    except Exception as e:  # noqa: BLE001 - a broken sim must not break real ports
        logger.warning("circuit-bench: sim provider registration failed (%s)", type(e).__name__)


def provider_for(port: str) -> Any | None:
    """The provider responsible for ``port`` or None (real port). A port with a provider-like prefix but no
    registered provider is ``port_not_found``."""
    _ensure_sim()
    for prefix, provider in _providers().items():
        if port.startswith(prefix):
            return provider
    if port.startswith("sim://"):
        raise BenchError("port_not_found", f"{port}: simulated ports are not available", "the sim module is missing")
    return None


def _provider_call(action: str, provider: Any, method: str, *args: Any, port: str | None = None) -> dict[str, Any]:
    try:
        res = getattr(provider, method)(*args)
    except Exception as e:  # noqa: BLE001 - provider bugs become an error envelope
        err = serialport.local_error(e)  # also a BenchError raised by another copy of the package
        if err is not None:
            return from_error(action, err, simulated=True)
        return fail(action, "tool_failed", f"simulated {method} failed: {type(e).__name__}: {e}", simulated=True)
    if isinstance(res, Mapping) and "ok" in res and "action" in res:
        out = dict(res)
        out["action"] = action
        out["simulated"] = bool(out.get("simulated", True))
        if validate_envelope(out):
            return fail(action, "tool_failed", f"simulated {method} returned an invalid result", simulated=True)
        return out
    if not isinstance(res, Mapping):
        return fail(action, "tool_failed", f"simulated {method} returned {type(res).__name__}", simulated=True)
    result = dict(res)
    simulated = bool(result.setdefault("simulated", True))
    if port is not None:
        result.setdefault("port", port)
    tag = " (simulated)" if simulated else ""
    if method == "detect":
        result.setdefault("at", _now())
        summary = f"Detected {result.get('chip') or 'board'} on {port}{tag}."
    elif method == "build":
        result.setdefault("ok", True)
        summary = f"Build ok: RAM {result.get('ram_pct')} %, flash {result.get('flash_pct')} %{tag}."
    else:
        result.setdefault("ok", True)
        sha = str(result.get("elf_sha256") or "")
        summary = f"Flashed firmware ({sha[:8]}…) to {port}{tag}." if sha else f"Flashed firmware to {port}{tag}."
    return envelope(action, summary, result, simulated=simulated)


# --------------------------------------------------------------------------------------------- helpers

def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_port(port: Any) -> str:
    """A serial device (/dev/tty*, /dev/cu.*, /dev/serial/by-id|by-path/* resolved to its device, COMn) or a provider
    URL (sim://...): ``serialport.normalize_port``. Network URLs (socket://, rfc2217://) are refused later
    (``_check_real_port``): the plugin talks only to local boards."""
    return serialport.normalize_port(port)


def normalize_port(port: Any) -> str:
    """Public alias of ``serialport.normalize_port`` (routes and tools normalise job keys and approvals with it)."""
    return serialport.normalize_port(port)


def _check_real_port(port: str) -> None:
    if "://" in port:
        raise BenchError("invalid_args", f"unsupported port URL {port!r}", "use a local device path or a sim:// port")


def _check_env(env: Any) -> str:
    if not isinstance(env, str) or not _ENV_RE.match(env):
        raise BenchError("invalid_args", f"bad PlatformIO environment name {env!r}", "use the [env:<name>] from platformio.ini")
    return env


def _check_project(project_dir: Any) -> Path:
    if not isinstance(project_dir, str | os.PathLike) or not str(project_dir).strip():
        raise BenchError("invalid_args", "project_dir must be a folder with platformio.ini")
    path = Path(project_dir).expanduser()
    if not path.is_dir():
        raise BenchError("invalid_args", f"{path} is not a folder", "pass the PlatformIO project folder")
    if not (path / "platformio.ini").is_file():
        raise BenchError("invalid_args", f"{path} has no platformio.ini", "pass the PlatformIO project folder")
    return path.resolve()


def _check_sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value.strip().lower()):
        raise BenchError("invalid_args", "expected_elf_sha256 must be the 64-digit SHA-256 of the built ELF",
                         "run build first and pass its elf_sha256")
    return value.strip().lower()


def _require_hardware() -> None:
    if not _settings.hardware_enabled():
        raise BenchError("sim_only", "hardware access is off: real boards are not reachable", _settings.sim_only_hint())


def _tool(name: str) -> str:
    cfg = _settings.load()
    override = cfg.get(f"{name}_path") or None
    path = clitools.find(name, override)
    if not path:
        where = f"the {name}_path setting ({override})" if override else "PATH"
        raise BenchError("tool_missing", f"{name} not found in {where}", _settings.tool_hint(name))
    return path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tail(lines: list[str], n: int = LOG_TAIL_LINES) -> list[str]:
    return [line[:LOG_LINE_CHARS] for line in lines[-n:]]


# esptool progress lines: 5.x "Writing at 0x00010000 [=====>     ] 52.3%", 4.x "Writing at 0x00010000... (52 %)"
_PROGRESS_RE = re.compile(r"^\s*(?:Writing|Reading|Erasing) at 0x[0-9a-fA-F]+\b.*?\d{1,3}(?:\.\d+)?\s*%")


def _drop_progress(lines: list[str]) -> list[str]:
    """``lines`` without esptool progress lines, except the last one; the order stays. The short ``log_tail`` then
    shows the result lines of every image (``Wrote ...``, ``Hash of data verified.``); the log_ref file and the job
    log keep every line."""
    hits = [i for i, line in enumerate(lines) if _PROGRESS_RE.match(line)]
    drop = set(hits[:-1])
    return [line for i, line in enumerate(lines) if i not in drop]


def _resolve_sources(ids: list[str]) -> list[dict[str, Any]]:
    try:
        return sources.resolve(ids)
    except BenchError:
        logger.warning("circuit-bench: unknown source id in %s", ids)
        return []


class _Log:
    """Full tool log as an artifact (``log_ref``); tees lines to an optional callback."""

    def __init__(self, kind: str, on_line: Callable[[str], None] | None):
        self.on_line = on_line
        self.ref: str | None = None
        self.file = None
        try:
            self.ref, self.file = serialport.open_artifact(kind)
        except (BenchError, OSError) as e:
            logger.warning("circuit-bench: no artifact log (%s)", e)

    def __call__(self, line: str) -> None:
        if self.file is not None:
            self.file.write(line + "\n")
        if self.on_line is not None:
            self.on_line(line)

    def close(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None


# --------------------------------------------------------------------------------------------- ports

def classify_usb(vid: int | None, pid: int | None) -> dict[str, Any]:
    """Kind of a USB serial port from VID:PID: {"kind", "label", "likely_esp", "auto_reset", "source_ids"}."""
    if vid is None or pid is None:
        return {"kind": "unknown", "label": _KIND_LABELS["unknown"], "likely_esp": False, "auto_reset": None,
                "source_ids": []}
    hit = _USB_TABLE.get((vid, pid))
    if hit:
        kind, label, likely, ids = hit
        return {"kind": kind, "label": label, "likely_esp": likely, "auto_reset": True, "source_ids": list(ids)}
    if vid == _ESPRESSIF_VID and 0x4000 <= pid <= 0x407F and pid & 0x1:
        # default PID of the esp_tinyusb device stack with a CDC interface (bit 0), e.g. 303a:4001
        return {"kind": "usb_cdc_app", "label": _KIND_LABELS["usb_cdc_app"], "likely_esp": True, "auto_reset": False,
                "source_ids": [_SRC_TINYUSB, _SRC_OBSERVED]}
    if vid == _ESPRESSIF_VID:
        return {"kind": "unknown", "label": "Espressif USB device", "likely_esp": True, "auto_reset": None,
                "source_ids": [_SRC_PYLIB]}
    return {"kind": "unknown", "label": _KIND_LABELS["unknown"], "likely_esp": False, "auto_reset": None,
            "source_ids": []}


def _comports() -> list[Any]:
    """pyserial's port list (reads sysfs, opens no port)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        raise BenchError("dependency_missing", "pyserial is not installed: real ports cannot be listed",
                         "install the plugin's Python dependencies (pyserial)") from None
    return list(list_ports.comports())


def _is_listable(info: Any) -> bool:
    """Hide placeholder UARTs: Linux lists /dev/ttyS0..31 with hwid 'n/a' even without hardware behind them
    (found on the test machine, 06.11.2026). USB ports and ports with a real hardware id stay."""
    if getattr(info, "vid", None) is not None:
        return True
    hwid = str(getattr(info, "hwid", "") or "").strip().lower()
    return hwid not in ("", "n/a")


def _real_entry(info: Any) -> dict[str, Any]:
    vid, pid = getattr(info, "vid", None), getattr(info, "pid", None)
    c = classify_usb(vid, pid)
    desc = getattr(info, "description", None)
    if not desc or desc == "n/a":
        desc = getattr(info, "product", None) or (c["label"] if vid is not None else "serial port")
    return {"device": str(info.device), "vid": f"{vid:04x}" if vid is not None else None,
            "pid": f"{pid:04x}" if pid is not None else None, "description": str(desc), "kind": c["kind"],
            "likely_esp": bool(c["likely_esp"]), "simulated": False}


def _provider_entry(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        item = {"device": item}
    if not isinstance(item, Mapping) or not isinstance(item.get("device"), str):
        return None
    return {"device": item["device"], "vid": item.get("vid"), "pid": item.get("pid"),
            "description": str(item.get("description") or "Simulated board"), "kind": str(item.get("kind") or "sim"),
            "likely_esp": bool(item.get("likely_esp", True)), "simulated": bool(item.get("simulated", True))}


def _scan() -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    """(ports, warnings, hardware_enabled)."""
    _ensure_sim()
    hw = _settings.hardware_enabled()
    out: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    if hw:
        try:
            real = [_real_entry(i) for i in _comports() if _is_listable(i)]
            out.extend(sorted(real, key=lambda p: (not p["likely_esp"], p["vid"] is None, p["device"])))
        except BenchError as e:
            warns.append(warning(e.code, "caution", e.message))
    for prefix, provider in list(_providers().items()):
        try:
            items = list(provider.ports() or [])
        except Exception as e:  # noqa: BLE001 - one provider must not hide the others
            logger.warning("circuit-bench: provider %s ports() failed (%s)", prefix, type(e).__name__)
            warns.append(warning("provider_failed", "info", f"{prefix} ports are unavailable ({type(e).__name__})"))
            continue
        out.extend(e for e in (_provider_entry(i) for i in items) if e is not None)
    return out, warns, hw


def list_ports() -> list[dict[str, Any]]:
    """Real ports (only with hardware access on) plus provider ports:
    [{"device", "vid", "pid", "description", "kind", "likely_esp", "simulated"}]."""
    return _scan()[0]


def _port_lookup(port: str) -> Any | None:
    """pyserial's entry of the listed real port matching ``port`` (also through /dev/serial/by-id links), or None.
    Reads the port list only (sysfs), never opens the port."""
    try:
        infos = _comports()
    except BenchError:
        return None
    want = os.path.realpath(port) if port.startswith("/") else port
    for info in infos:
        dev = str(info.device)
        if dev == port or (port.startswith("/") and os.path.realpath(dev) == want):
            return info
    return None


def _port_info(port: str) -> dict[str, Any] | None:
    """The listed real port matching ``port`` as a port-list entry, or None."""
    info = _port_lookup(port)
    return _real_entry(info) if info is not None else None


def usb_identity(info: Any) -> dict[str, str] | None:
    """USB identity of a pyserial port entry: {"vid", "pid", "serial"} with 4 lower-case hex digits and
    the USB serial number (iSerial; pyserial ``serial_number``, read from sysfs, the port is not opened). None
    without VID/PID or without a usable serial number (1-64 printable characters)."""
    if info is None:
        return None
    vid, pid, serial = getattr(info, "vid", None), getattr(info, "pid", None), getattr(info, "serial_number", None)
    if not isinstance(vid, int) or not isinstance(pid, int) or not 0 <= vid <= 0xFFFF or not 0 <= pid <= 0xFFFF:
        return None
    if not isinstance(serial, str):
        return None
    serial = serial.strip()
    if not serial or len(serial) > _USB_SERIAL_MAX or not serial.isprintable():
        return None
    return {"vid": f"{vid:04x}", "pid": f"{pid:04x}", "serial": serial}


def _usb_text(usb: Mapping[str, Any] | None) -> str:
    if not usb:
        return "no USB serial number"
    return f"{usb.get('vid')}:{usb.get('pid')} serial {str(usb.get('serial'))[:_USB_SERIAL_MAX]}"


def _expected_identity(expected_board: Any) -> dict[str, Any] | None:
    """(mac, usb_id) the flash must find, from ``expected_board`` (= project.board.detected); None without it.
    A detection without MAC refuses: the identity of the board could not be compared."""
    if expected_board is None:
        return None
    if not isinstance(expected_board, Mapping):
        raise BenchError("invalid_args", "expected_board must be the detected board (project.board.detected)")
    mac = expected_board.get("mac")
    mac = mac.strip().lower() if isinstance(mac, str) and mac.strip() else None
    if mac is None:
        raise BenchError("not_confirmed", "the detected board has no MAC address to compare", IDENTITY_HINT)
    usb = expected_board.get("usb_id")
    if usb is not None and not isinstance(usb, Mapping):
        raise BenchError("not_confirmed", "the detected USB identity is unreadable", IDENTITY_HINT)
    usb = {k: str(usb.get(k) or "").strip().lower() if k != "serial" else str(usb.get(k) or "").strip()
           for k in ("vid", "pid", "serial")} if usb else None
    return {"mac": mac, "usb_id": usb}


def _check_usb_identity(port: str, want: Mapping[str, Any] | None, info: Any) -> None:
    """The USB device on ``port`` must be the detected one (same VID, PID and serial number), checked before any
    tool runs. Detections without ``usb_id`` (no serial number, older projects) are compared by MAC only."""
    if not want or not want.get("usb_id"):
        return
    now = usb_identity(info)
    if now != want["usb_id"]:
        shown = _usb_text(now) if info is not None else "no listed device"
        raise BenchError("not_confirmed", f"the USB device on {port} is not the one detected "
                         f"({_usb_text(want['usb_id'])} → {shown}); detect again", IDENTITY_HINT)


def _check_exists(port: str) -> None:
    _check_real_port(port)
    if port.startswith("/") and not os.path.exists(port):
        raise BenchError("port_not_found", f"{port} does not exist", "replug the board and list the ports again")


IDENTITY_HINT = "detect the board again, then approve the flash for that board"


def _no_reset_warning(port: str) -> dict[str, Any]:
    return warning("no_auto_reset", "caution", f"{port}: {NO_AUTO_RESET_HINT}", [_SRC_TINYUSB, _SRC_OBSERVED, _SRC_BOOT])


def ports() -> dict[str, Any]:
    """Action board.ports: every reachable port (envelope, result {"ports": [...]})."""
    action = "board.ports"
    try:
        items, warns, hw = _scan()
    except BenchError as e:
        return from_error(action, e)
    if not hw:
        warns.insert(0, warning("hardware_off", "info", "hardware access is off: only simulated ports are listed"))
    ids: list[str] = []
    for p in items:
        if p["simulated"]:
            continue
        c = classify_usb(int(p["vid"], 16) if p["vid"] else None, int(p["pid"], 16) if p["pid"] else None)
        ids += c["source_ids"]
        if p["kind"] == "usb_cdc_app":
            warns.append(_no_reset_warning(p["device"]))
            ids.append(_SRC_BOOT)
    if not items:
        summary = "No serial ports found." if hw else "No ports: hardware access is off and no simulated board is available."
    else:
        def label(p: dict[str, Any]) -> str:
            if p["simulated"]:
                return "simulated"
            return p["description"] if p["kind"] == "unknown" else _kind_label(p)
        shown = ", ".join(f"{p['device']} ({label(p)})" for p in items[:5])
        more = f" and {len(items) - 5} more" if len(items) > 5 else ""
        summary = f"{len(items)} port{'s' if len(items) != 1 else ''}: {shown}{more}."
    simulated = bool(items) and all(p["simulated"] for p in items)
    return envelope(action, summary, {"ports": items}, warnings=warns, sources=_resolve_sources(ids), simulated=simulated)


def _kind_label(p: dict[str, Any]) -> str:
    if p["kind"] in _KIND_LABELS:
        return _KIND_LABELS[p["kind"]]
    c = classify_usb(int(p["vid"], 16) if p["vid"] else None, int(p["pid"], 16) if p["pid"] else None)
    return c["label"]


# --------------------------------------------------------------------------------------------- detect

# esptool 5.6.0 ``get_chip_description()`` names per ``CHIP_NAME`` (targets/<chip>.py, sources
# esptool-5.6.0-target-<chip>), without the " (revision vX.Y)" suffix. ``Chip type:`` shows these, not CHIP_NAME
# (e.g. "ESP32-D0WD-V3 (revision v3.1)" on an ESP32); the project stores that text as ``board.detected.chip``.
# "Unknown ESP32..." names are left out on purpose: an unknown package is no chip the bench can vouch for.
# tests/test_cflash_detect.py checks this table against the pinned esptool sources.
ESPTOOL_DESCRIPTIONS: dict[str, tuple[str, ...]] = {
    "ESP32": ("ESP32-S0WDQ6", "ESP32-D0WDQ6-V3", "ESP32-D0WDQ6", "ESP32-S0WD", "ESP32-D0WD-V3", "ESP32-D0WD",
              "ESP32-D2WD", "ESP32-U4WDH", "ESP32-PICO-V3", "ESP32-PICO-D4", "ESP32-PICO-V3-02", "ESP32-D0WDR2-V3"),
    "ESP32-S2": ("ESP32-S2", "ESP32-S2FH2", "ESP32-S2FH4", "ESP32-S2FNR2", "ESP32-S2R2"),
    "ESP32-S3": ("ESP32-S3 (QFN56)", "ESP32-S3-PICO-1 (LGA56)"),
    "ESP32-C3": ("ESP32-C3 (QFN32)", "ESP8685 (QFN28)", "ESP32-C3 AZ (QFN32)", "ESP8686 (QFN24)"),
    "ESP32-C6": ("ESP32-C6 (QFN40)", "ESP32-C6FH4 (QFN32)", "ESP32-C6FH8 (QFN32)"),
}
_REVISION_RE = re.compile(r"\s*\(revision v[^)]*\)\s*$")
_SDM_SUFFIX = " in Secure Download Mode"


def chip_from_esptool(text: Any) -> str | None:
    """Chip id (data/chips.json) for an esptool chip name or ``Chip type:`` text, else None.

    Accepts the ``CHIP_NAME`` ("ESP32-C6", from "Connected to ..."/"Detecting chip type...") and the chip
    description of ``Chip type:`` ("ESP32-D0WD-V3 (revision v3.1)", "ESP32-S3 (QFN56) (revision v0.2)",
    "ESP32-S3 in Secure Download Mode"). Exact names only, no prefix guessing: an ESP32-C61 must never pass as an
    ESP32-C6."""
    if not isinstance(text, str) or not text.strip():
        return None
    name = text.strip()
    if name.endswith(_SDM_SUFFIX):
        name = name[:-len(_SDM_SUFFIX)].strip()
    name = _REVISION_RE.sub("", name).strip()
    hit = chips.by_esptool_name(name)
    if hit:
        return hit
    for chip_name, descriptions in ESPTOOL_DESCRIPTIONS.items():
        if name in descriptions:
            return chips.by_esptool_name(chip_name)
    return None


def _chip_id(name: str | None) -> str | None:
    return chip_from_esptool(name)


def parse_flash_id(lines: list[str]) -> dict[str, Any]:
    """Fields from ``esptool ... flash-id`` output (esptool 5.6.0: labels padded to 20 characters)."""
    values: dict[str, str] = {}
    connected = detecting = None
    for raw in lines:
        line = raw.strip()
        m = _CONNECTED_RE.match(line)
        if m and connected is None:
            connected = m.group(1).rstrip(":")
        m = _DETECTING_RE.match(line)
        if m and detecting is None and not m.group(1).startswith("Autodetection"):
            detecting = m.group(1)
        for label in _LABELS:
            if line.startswith(label + ":") and label not in values:
                values[label] = line[len(label) + 1:].strip()
                break
    chip_name = connected or detecting
    chip_type = values.get("Chip type") or None
    if chip_name is None and chip_type:
        chip_name = chip_type.split(" (")[0].split(" in ")[0]
    chip_id = _chip_id(chip_name) or _chip_id(chip_type)
    features_text = values.get("Features", "")
    features = [f.strip() for f in features_text.split(",") if f.strip()]
    psram = _PSRAM_RE.search(features_text)
    emb_flash = _EMB_FLASH_RE.search(features_text)
    xtal = _MHZ_RE.search(values.get("Crystal frequency", ""))
    size = values.get("Detected flash size") or None
    if size in (None, "Unknown"):
        size = None
    ftype = (values.get("Flash type set in eFuse") or "").split(" ")[0] or None
    mac = values.get("MAC") or None
    return {
        "chip": chip_type,
        "chip_name": chip_name,
        "chip_id": chip_id,
        "features": features,
        "crystal_mhz": (float(xtal.group(1)) if "." in xtal.group(1) else int(xtal.group(1))) if xtal else None,
        "usb_mode": values.get("USB mode") or None,
        "mac": mac.lower() if mac else None,
        "base_mac": (values.get("BASE MAC") or "").lower() or None,
        "flash_size": size,
        "flash_type": ftype if ftype in ("quad", "octal") else None,
        "flash_manufacturer": values.get("Manufacturer") or None,
        "flash_device": values.get("Device") or None,
        "psram_mb": int(psram.group(1)) if psram else None,
        "psram_vendor": (psram.group(2) or None) if psram else None,
        "embedded_flash_mb": int(emb_flash.group(1)) if emb_flash else None,
    }


def variant_suggestion(parsed: Mapping[str, Any]) -> str | None:
    """ESP32-S3 module variant guess ("n16r8?"). Only a suggestion: esptool does not report octal/quad PSRAM."""
    if parsed.get("chip_id") != "esp32s3":
        return None
    m = re.match(r"^(\d+)MB$", str(parsed.get("flash_size") or ""))
    if not m:
        return None
    psram = parsed.get("psram_mb")
    return f"n{m.group(1)}" + (f"r{psram}" if psram else "") + "?"


def flash_hint(devkit: Any) -> tuple[str | None, list[str]]:
    """The board's own hint for entering the bootloader (``flash_hint`` of data/boards/<devkit>.json,
    e.g. a board without buttons or auto-reset) and its source ids; (None, []) without
    one. ``flash_hint`` is a text or ``{text, source_id(s)}``; unknown boards count as none."""
    if not isinstance(devkit, str) or not devkit:
        return None, []
    try:
        hint = boards.load(devkit).get("flash_hint")
    except BenchError:
        return None, []
    ids: list[str] = []
    if isinstance(hint, Mapping):
        ids = [str(i) for i in ([hint.get("source_id")] if hint.get("source_id") else []) + list(hint.get("source_ids") or [])]
        hint = hint.get("text") or hint.get("message")
    if not isinstance(hint, str) or not hint.strip():
        return None, []
    return hint.strip(), ids


def _esptool_failure(lines: list[str], port: str, kind: str | None, rc: int | None,
                     board_hint: str | None = None) -> BenchError:
    """``board_hint``: the project board's ``flash_hint``; it replaces the generic BOOT/RESET hints."""
    text = "\n".join(lines)
    fatal = next((ln.strip() for ln in reversed(lines) if "fatal error occurred" in ln.lower()), None)
    detail = fatal.split(":", 1)[1].strip() if fatal and ":" in fatal else (fatal or "")
    if _WRITE_TIMEOUT_RE.search(text) and not re.search(r"Writing at 0x", text):
        return BenchError("tool_failed", f"esptool could not reach the bootloader on {port} (write timeout)",
                          board_hint or WRITE_TIMEOUT_HINT)
    if _CONNECT_FAIL_RE.search(text):
        hint = board_hint or (NO_AUTO_RESET_HINT if kind in (None, "unknown", "usb_cdc_app") else BOOTLOADER_HINT)
        return BenchError("tool_failed", f"esptool could not connect to the board on {port}: {(detail or 'no answer')[:200]}", hint)
    if _OPEN_FAIL_RE.search(text):
        if re.search(r"Permission denied", text):
            return BenchError("tool_failed", f"no permission to open {port}", _settings.SERIAL_GROUP_HINT)
        if re.search(r"No such file or directory|\[Errno 2\]", text):
            return BenchError("port_not_found", f"{port} does not exist", "replug the board and list the ports again")
        return BenchError("port_busy", f"{port} is busy (another program has it open)",
                          "close serial monitors (Arduino IDE, pio device monitor, screen) and retry")
    last = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    return BenchError("tool_failed", f"esptool failed (exit {rc}): {(detail or last)[:200]}",
                      "see log_tail; check the cable and the port")


def detect(port: str, *, before: str = "default-reset", on_line: Callable[[str], None] | None = None,
           devkit: str | None = None) -> dict[str, Any]:
    """Action board.detect: ``esptool --port P --before <before> --after hard-reset flash-id`` (resets the board).

    ``devkit``: the project's board (data/boards id); its ``flash_hint`` replaces the generic hints of connection
    errors. ``chip_id`` comes from the chip register (None for chips the bench does not know)."""
    action = "board.detect"
    warns: list[dict[str, Any]] = []
    ids: list[str] = [_SRC_ESPTOOL_OUT]
    result: dict[str, Any] | None = None
    board_hint, hint_ids = flash_hint(devkit)
    try:
        port = _check_port(port)
        if before not in BEFORE_MODES:
            raise BenchError("invalid_args", f"before must be one of {', '.join(BEFORE_MODES)}")
        provider = provider_for(port)
        if provider is not None:
            return _provider_call(action, provider, "detect", port, port=port)
        _check_real_port(port)
        _require_hardware()
        raw = _port_lookup(port)
        info = _real_entry(raw) if raw is not None else None
        usb_id = usb_identity(raw)
        _check_exists(port)
        kind = info["kind"] if info else None
        if info:
            ids += classify_usb(int(info["vid"], 16) if info["vid"] else None,
                                int(info["pid"], 16) if info["pid"] else None)["source_ids"]
        if kind == "usb_cdc_app":
            warns.append(_no_reset_warning(port))
            ids.append(_SRC_BOOT)
            if on_line is not None:
                on_line(f"warning: {NO_AUTO_RESET_HINT}")
        exe = _tool("esptool")
        argv = [exe, "--port", port, "--before", before, "--after", "hard-reset", "flash-id"]
        # the port's flock for the whole esptool run (a monitor in this or another Circuit Bench process lets go
        # and reopens afterwards; a holder that does not yield within PAUSE_LOCK_WAIT_S -> port_busy)
        with serialport.pause(port), tempfile.TemporaryDirectory(prefix="cb-esptool-") as tmp:
            serialport.check_port_free(port)  # a program outside Circuit Bench still reading the port -> port_busy
            # empty cwd and HOME: no esptool.cfg/setup.cfg/tox.ini from the user's folders applies
            res = clitools.run(argv, timeout=DETECT_TIMEOUT_S, cwd=tmp, env_extra={"HOME": tmp}, tail=400,
                               on_line=on_line, hardware=True)
        lines = res["out_tail"]
        result = {"port": port, "port_kind": kind, "log_tail": _tail(_drop_progress(lines)), "reset_happened": True}
        if res["timed_out"]:
            ids += hint_ids
            raise BenchError("timeout", f"esptool did not finish within {DETECT_TIMEOUT_S:g} s on {port}",
                             board_hint or (NO_AUTO_RESET_HINT if kind == "usb_cdc_app" else BOOTLOADER_HINT))
        if res["rc"] != 0:
            ids += hint_ids
            raise _esptool_failure(lines, port, kind, res["rc"], board_hint)
        parsed = parse_flash_id(lines)
        if not parsed["chip"]:
            raise BenchError("tool_failed", "esptool output has no 'Chip type:' line", "see log_tail")
        suggestion = variant_suggestion(parsed)
        result = {
            "port": port, "mac": parsed["mac"], "chip": parsed["chip"], "description": (info or {}).get("description")
            or parsed["chip"], "features": parsed["features"], "flash_size": parsed["flash_size"],
            "variant_suggestion": suggestion, "at": _now(), "simulated": False,
            "chip_id": parsed["chip_id"], "crystal_mhz": parsed["crystal_mhz"], "usb_mode": parsed["usb_mode"],
            "base_mac": parsed["base_mac"], "flash_type": parsed["flash_type"], "psram_mb": parsed["psram_mb"],
            "psram_vendor": parsed["psram_vendor"], "embedded_flash_mb": parsed["embedded_flash_mb"],
            "port_kind": kind, "reset_happened": True, "usb_id": usb_id, "log_tail": _tail(_drop_progress(lines)),
        }
    except BenchError as e:
        return from_error(action, e, result=result, warnings=warns, sources=_resolve_sources(ids))
    warns.append(warning("board_reset", "info", f"esptool reset the board (--before {before}, --after hard-reset); "
                         "the running firmware restarted"))
    if suggestion:
        warns.append(warning("variant_unverified", "info", f"variant_suggestion {suggestion!r} is an unverified mapping: "
                             "esptool does not report octal/quad PSRAM; confirm the module marking", [_SRC_ESPTOOL_OUT]))
    bits = [f"{parsed['flash_size'] or 'unknown'} flash"]
    if parsed["psram_mb"]:
        bits.append(f"{parsed['psram_mb']} MB PSRAM")
    if parsed["mac"]:
        bits.append(f"MAC {parsed['mac']}")
    summary = f"{parsed['chip']} on {port}: {', '.join(bits)}" + (f"; variant {suggestion} (unverified)." if suggestion else ".")
    checks = [check("board.detect.chip", "passed", f"esptool read {parsed['chip_name'] or parsed['chip']}")]
    if parsed["chip_id"] is None:
        warns.append(warning("chip_unknown", "caution", f"{parsed['chip_name'] or parsed['chip']} is not a chip "
                             f"Circuit Bench supports ({chips.ids_text()}): flashing it is refused"))
    else:
        ids.append(_ESPTOOL_TARGET_SRC + parsed["chip_id"])
    return envelope(action, summary, result, checks=checks, warnings=warns, sources=_resolve_sources(ids))


# --------------------------------------------------------------------------------------------- pio

def _pio_failure(lines: list[str], what: str, rc: int | None) -> BenchError:
    text = "\n".join(lines)
    m = re.search(r"UnknownEnvNamesError: (.*)", text)
    if m:
        return BenchError("invalid_args", m.group(1).strip()[:200], "use an [env:<name>] from platformio.ini")
    if re.search(r"HTTPClientError|Could not resolve|Max retries exceeded|Connection refused|InternetConnectionError", text):
        return BenchError("tool_failed", f"{what}: PlatformIO needs packages it cannot download",
                          "install the platform/toolchain once with network access (pio pkg install), then retry")
    errors = [ln.strip() for ln in lines if _COMPILE_ERR_RE.match(ln.strip())]
    if errors:
        return BenchError("tool_failed", f"{what} failed: {errors[0][:200]}", "fix the compiler error and build again")
    err = next((ln.strip() for ln in lines if ln.strip().startswith("Error:")), None)
    last = next((ln.strip() for ln in reversed(lines) if ln.strip() and not ln.strip().startswith("=")), "")
    return BenchError("tool_failed", f"{what} failed (exit {rc}): {(err or last)[:200]}", "see log_tail / log_ref")


def metadata(project_dir: str | Path, env: str, *, timeout: float = METADATA_TIMEOUT_S) -> dict[str, Any]:
    """``pio project metadata`` for ``env``: {"env", "cc_path", "prog_path" (ELF), "toolchain_prefix",
    "addr2line", "gdb_path", "build_type"}. Field names checked against PlatformIO Core 6.2.0 (source board-pio-6.2.0-metadata).

    PlatformIO runs it as ``pio run --target __idedata`` (project/helpers.py ``_load_build_metadata``): an explicit
    target, so the ``targets`` option of platformio.ini does not run (the project's extra_scripts do)."""
    pdir = _check_project(project_dir)
    env = _check_env(env)
    exe = _tool("pio")
    with tempfile.TemporaryDirectory(prefix="cb-pio-meta-") as tmp:
        out = Path(tmp) / "metadata.json"
        res = clitools.run([exe, "project", "metadata", "-d", str(pdir), "-e", env, "--json-output-path", str(out)],
                           timeout=timeout, cwd=str(pdir), tail=100)
        if res["timed_out"]:
            raise BenchError("timeout", f"pio project metadata did not finish within {timeout:g} s")
        if res["rc"] != 0:
            raise _pio_failure(res["out_tail"], "pio project metadata", res["rc"])
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise BenchError("tool_failed", "pio project metadata wrote no readable JSON") from None
    entry = data.get(env) if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        raise BenchError("tool_failed", f"pio project metadata has no entry for env {env!r}")
    cc = entry.get("cc_path") or None
    prefix = cc[:-3] if isinstance(cc, str) and cc.endswith("gcc") else None
    extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
    images = []
    for item in extra.get("flash_images") or []:
        if isinstance(item, dict) and _OFFSET_RE.match(str(item.get("offset") or "")) and item.get("path"):
            images.append({"offset": str(item["offset"]).lower(), "path": str(item["path"])})
    app_offset = str(extra.get("application_offset") or "")
    return {"env": env, "cc_path": cc, "prog_path": entry.get("prog_path") or None, "toolchain_prefix": prefix,
            "addr2line": prefix + "addr2line" if prefix else None, "gdb_path": entry.get("gdb_path") or None,
            "build_type": entry.get("build_type"), "flash_images": images,
            "app_offset": app_offset.lower() if _OFFSET_RE.match(app_offset) else None}


def parse_sizes(lines: list[str]) -> dict[str, Any]:
    """RAM/flash usage from ``pio run``: {"ram_pct", "flash_pct", "ram_used", "ram_total", "flash_used", "flash_total"}."""
    out: dict[str, Any] = {"ram_pct": None, "flash_pct": None, "ram_used": None, "ram_total": None,
                           "flash_used": None, "flash_total": None}
    for raw in lines:
        m = _SIZE_RE.match(raw.strip())
        if not m:
            continue
        key = m.group(1).lower()
        pct = float(m.group(2))
        if not math.isfinite(pct):
            continue
        out[f"{key}_pct"] = pct
        if m.group(3):
            out[f"{key}_used"], out[f"{key}_total"] = int(m.group(3)), int(m.group(4))
    return out


EXTRA_IMAGES = ("bootloader.bin", "partitions.bin")  # written by `-t upload` from the build folder with the app


def image_names(elf: Path) -> tuple[str, ...]:
    """The flash images of a build: the app image next to the ELF (firmware.bin) plus bootloader and partitions."""
    return (elf.with_suffix(".bin").name, *EXTRA_IMAGES)


def image_hashes(elf: str | Path) -> dict[str, str]:
    """SHA-256 of the flash images next to the ELF that exist ({name: sha256}); stored in last_build.images."""
    elf = Path(elf)
    out: dict[str, str] = {}
    for name in image_names(elf):
        path = elf.parent / name
        if path.is_file():
            out[name] = sha256_file(path)
    return out


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------------------------- build pre-check

# PlatformIO folders (PLATFORMIO_CORE_DIR, _PLATFORMS_DIR, _PACKAGES_DIR, _BOARDS_DIR as PlatformIO reads them)
def pio_dirs() -> dict[str, Path]:
    core = Path(os.environ.get("PLATFORMIO_CORE_DIR") or Path.home() / ".platformio")
    return {"core": core, "platforms": Path(os.environ.get("PLATFORMIO_PLATFORMS_DIR") or core / "platforms"),
            "packages": Path(os.environ.get("PLATFORMIO_PACKAGES_DIR") or core / "packages")}


_SEMVER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")
_REQ_PART_RE = re.compile(r"^(>=|<=|==|!=|>|<|=|\^|~)?\s*(\S+)$")


def semver(text: Any) -> tuple[int, int, int] | None:
    """(major, minor, patch) of '8.0.0', '3.20017.241212+sha.x', '6.9' (missing parts 0), else None."""
    m = _SEMVER_RE.match(str(text or "").strip())
    return (int(m[1]), int(m[2] or 0), int(m[3] or 0)) if m else None


def _req_bounds(requirements: str) -> list[tuple[str, tuple[int, int, int]]] | None:
    """A PlatformIO version requirement (semantic_version SimpleSpec: '8.0.0', '~6.9.0', '^6.9.0', '>=7,<9') as
    [(op, version)], None if it is anything else (then nothing is certain)."""
    out: list[tuple[str, tuple[int, int, int]]] = []
    for part in [x.strip() for x in requirements.split(",") if x.strip()]:
        m = _REQ_PART_RE.match(part)
        v = semver(m[2]) if m else None
        if v is None:
            return None
        op = m[1] or "=="
        if op == "~":
            out += [(">=", v), ("<", (v[0], v[1] + 1, 0))]
        elif op == "^":
            out += [(">=", v), ("<", (v[0] + 1, 0, 0) if v[0] else (0, v[1] + 1, 0))]
        else:
            out.append(("==" if op == "=" else op, v))
    return out or None


def version_matches(version: Any, requirements: str | None) -> bool:
    """Does an installed version satisfy the requirement? No requirement: any version. Unknown forms: False."""
    v = semver(version)
    if v is None:
        return False
    if not requirements:
        return True
    bounds = _req_bounds(requirements)
    if bounds is None:
        return False
    ops = {">=": v.__ge__, "<=": v.__le__, ">": v.__gt__, "<": v.__lt__, "==": v.__eq__, "!=": v.__ne__}
    return all(ops[op](b) for op, b in bounds)


def _req_upper(requirements: str) -> tuple[tuple[int, int, int], bool] | None:
    """Highest version the requirement allows: (version, inclusive), None if unbounded or unknown."""
    bounds = _req_bounds(requirements) or []
    best: tuple[tuple[int, int, int], bool] | None = None
    for op, b in bounds:
        if op in ("<", "<=", "=="):
            cand = (b, op != "<")
            if best is None or cand[0] < best[0] or (cand[0] == best[0] and not cand[1]):
                best = cand
    return best


def parse_platform(value: Any) -> dict[str, Any]:
    """``platform =`` of an env: {raw, name, requirements, external}. ``espressif32``, ``espressif32@8.0.0``,
    ``platformio/espressif32 @ ^6.9.0``; URLs and paths are ``external`` (their version cannot be known)."""
    raw = str(value or "").strip()
    if not raw:
        return {"raw": raw, "name": None, "requirements": None, "external": False}
    if "://" in raw or raw.startswith(("/", ".", "~", "file:")) or raw.endswith((".zip", ".git", ".tar.gz")):
        return {"raw": raw, "name": None, "requirements": None, "external": True}
    name, _, req = raw.partition("@")
    name = name.strip().split("/")[-1].strip().lower()
    return {"raw": raw, "name": name or None, "requirements": req.strip() or None, "external": False}


def installed_platforms(name: str = "espressif32", *, platforms_dir: Path | None = None,
                        ) -> list[tuple[tuple[int, int, int], Path, dict[str, Any]]]:
    """Installed PlatformIO platforms ``name`` (folders ``<name>`` and ``<name>@<version>``) as
    [(version, folder, platform.json)], highest version first. ``platforms_dir``: default ``pio_dirs()``."""
    out = []
    for pj in (platforms_dir or pio_dirs()["platforms"]).glob(f"{name}*/platform.json"):
        if pj.parent.name != name and not pj.parent.name.startswith(f"{name}@"):
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        v = semver(data.get("version"))
        if data.get("name", name) == name and v is not None:
            out.append((v, pj.parent, data))
    return sorted(out, key=lambda t: t[0], reverse=True)


def installed_platform(requirements: str | None, name: str = "espressif32", *, platforms_dir: Path | None = None,
                       ) -> tuple[Path, dict[str, Any]] | None:
    """The installed platform PlatformIO uses for ``name@requirements``: the highest installed version that
    satisfies the requirement (PlatformIO Core 6.2.0 ``BasePackageManager.get_package``), None if none does."""
    for _v, folder, data in installed_platforms(name, platforms_dir=platforms_dir):
        if version_matches(data.get("version"), requirements):
            return folder, data
    return None


def pio_env_options(project_dir: str | Path, env: str) -> dict[str, str] | None:
    """Options of [env:<env>] with [env] and ``extends`` merged (no interpolation); None if the ini cannot be read or
    pulls in other files or folders (extra_configs, core_dir, packages_dir, platforms_dir, boards_dir): then nothing
    is certain."""
    import configparser
    pdir = Path(project_dir)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(pdir / "platformio.ini", encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        return None
    if parser.has_section("platformio") and any(parser.has_option("platformio", k) for k in (
            "extra_configs", "core_dir", "packages_dir", "platforms_dir", "boards_dir")):
        return None
    if not parser.has_section(f"env:{env}"):
        return None
    opts = dict(parser.items("env")) if parser.has_section("env") else {}
    own = dict(parser.items(f"env:{env}"))
    for base in [x.strip() for x in own.get("extends", "").replace("\n", ",").split(",") if x.strip()]:
        if not parser.has_section(base):
            return None
        opts.update(dict(parser.items(base)))
    opts.update(own)
    return opts


def ini_list(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").replace("\n", ",").split(",") if x.strip()]


def board_json(project_dir: str | Path, board_id: str, platform_dir: Path | None) -> tuple[dict[str, Any], Path] | None:
    """The board manifest PlatformIO uses: project ``boards/``, then ``<core>/boards``, then the platform's
    ``boards/`` (PlatformIO docs, boards_dir). None if not found."""
    if not board_id or "/" in board_id or board_id.startswith("."):
        return None
    dirs = [Path(project_dir) / "boards", pio_dirs()["core"] / "boards"]
    if os.environ.get("PLATFORMIO_BOARDS_DIR"):
        dirs[0] = Path(os.environ["PLATFORMIO_BOARDS_DIR"])
    if platform_dir is not None:
        dirs.append(platform_dir / "boards")
    for d in dirs:
        f = d / f"{board_id}.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")), f
        except (OSError, ValueError):
            continue
    return None


def _vtext(v: tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in v)


def build_precheck(project_dir: str | Path, env: str, chip: str) -> dict[str, Any]:
    """Checks before ``pio run`` for a project chip ``chip``.

    Raises ``chip_mismatch`` if the env builds for another MCU (``board_build.mcu`` or ``build.mcu`` of the board
    manifest of the installed platform version) and ``platform_too_old`` if the env uses the Arduino framework, the
    chip has ``arduino_platform_min`` (data/chips.json) and the pinned espressif32 version is older. An unpinned
    platform only warns (``platform_unpinned``, caution); what cannot be read is reported as an ``info`` warning
    (``chip_unchecked``), never refused. Returns {warnings, source_ids, mcu, platform}."""
    spec = chips.get(chip)  # unknown_chip for a broken project
    warns: list[dict[str, Any]] = []
    ids: list[str] = []
    out: dict[str, Any] = {"warnings": warns, "source_ids": ids, "mcu": None, "platform": None}
    opts = pio_env_options(project_dir, env)
    if opts is None:
        warns.append(warning("chip_unchecked", "info", f"platformio.ini of env {env} could not be read completely "
                             "(extra_configs, extends or PlatformIO folders): the board's MCU was not checked"))
        return out
    if any("${" in str(opts.get(k) or "") for k in ("platform", "board", "board_build.mcu", "framework")):
        warns.append(warning("chip_unchecked", "info", f"env {env} uses ${{...}} variables for platform, board or "
                             "framework: the board's MCU and the platform were not checked"))
        return out
    plat = parse_platform(opts.get("platform"))
    out["platform"] = plat["raw"] or None
    platform_dir = None
    if plat["name"] == "espressif32":
        hit = installed_platform(plat["requirements"])
        platform_dir = hit[0] if hit else None
        if hit:
            ids.append(_SRC_GET_PACKAGE)
    board_id = (opts.get("board") or "").strip()
    mcu = (opts.get("board_build.mcu") or "").strip().lower() or None
    where = "board_build.mcu"
    if mcu is None and board_id:
        found = board_json(project_dir, board_id, platform_dir)
        if found is not None:
            mcu = str((found[0].get("build") or {}).get("mcu") or "esp32").strip().lower()  # platform.py default
            where = f"board {board_id}"
    out["mcu"] = mcu
    if mcu is None:
        warns.append(warning("chip_unchecked", "info", f"the MCU of env {env} is unknown (board "
                             f"{board_id or '?'} is not in an installed platform): it was not checked against "
                             f"{spec['id']}"))
    elif mcu != spec["pio_mcu"]:
        other = chips.by_pio_mcu(mcu)
        raise BenchError("chip_mismatch", f"env {env} builds for {other or mcu} ({where}), but the project chip is "
                         f"{spec['id']}", f"use an env whose board has an {spec['id']} (build.mcu {spec['pio_mcu']}), "
                         f"or change the project chip to {other or mcu} with set_board")
    else:
        ids.append(_SRC_BOARDS_DIR)
    floor = spec.get("arduino_platform_min")
    frameworks = [f.lower() for f in ini_list(opts.get("framework"))]
    if not floor or "arduino" not in frameworks:
        return out
    floor_v = semver(floor)
    pin_hint = f"pin platform = espressif32@{floor} (or newer)"
    ids += list((spec.get("source_ids") or {}).get("arduino_platform_min") or [])
    if plat["external"] or plat["name"] != "espressif32" or not plat["requirements"]:
        installed = installed_platform(None) if plat["name"] == "espressif32" and not plat["external"] else None
        have = f" (installed: espressif32 {installed[1].get('version')})" if installed else ""
        what = (f"platform = {plat['raw']} has no version the bench can compare" if plat["raw"]
                else f"env {env} names no platform")
        warns.append(warning("platform_unpinned", "caution", f"{what}{have}: {spec['title']} with Arduino needs "
                             f"espressif32 {floor} or newer; {pin_hint}", ids))
        return out
    if _req_bounds(plat["requirements"]) is None:
        warns.append(warning("platform_unpinned", "caution", f"platform = {plat['raw']}: the version requirement "
                             f"cannot be compared; {spec['title']} with Arduino needs espressif32 {floor} or newer; "
                             f"{pin_hint}", ids))
        return out
    upper = _req_upper(plat["requirements"])
    too_old = None
    if floor_v is not None and upper is not None and (upper[0] < floor_v or (upper[0] == floor_v and not upper[1])):
        too_old = f"espressif32@{plat['requirements']}"  # every version it allows is older than the floor
    elif floor_v is not None and platform_dir is not None:
        hit = installed_platform(plat["requirements"])
        used = semver(hit[1].get("version")) if hit else None
        if used is not None and used < floor_v:  # pio would build with this installed, older version
            too_old = f"espressif32@{plat['requirements']} (installed match: {_vtext(used)})"
    if too_old:
        raise BenchError("platform_too_old", f"env {env} pins {too_old}: {spec['title']} with the Arduino framework "
                         f"needs espressif32 {floor} or newer", pin_hint)
    return out


def build_runs_pio(project_dir: str | Path, env: str, port: str | None = None) -> bool:
    """Does ``build(project_dir, env, port=port)`` start PlatformIO? True for no port or a real port. A provider port
    asks the provider (``build_runs_pio`` is optional there: without it the build is taken as not starting pio); a
    provider that raises counts as True (when in doubt the caller asks)."""
    try:
        provider = provider_for(_check_port(port)) if port is not None else None
        if provider is None:
            return True
        predict = getattr(provider, "build_runs_pio", None)
        if not callable(predict):
            return False
        return bool(predict(str(project_dir), env))
    except Exception:  # noqa: BLE001 - a prediction that fails must not skip the question
        return True


def build(project_dir: str | Path, env: str, *, timeout: float | None = None, port: str | None = None,
          on_line: Callable[[str], None] | None = None, chip: str | None = None) -> dict[str, Any]:
    """Action board.build: ``pio run -d <dir> -e <env> -t checkprogsize -t buildprog`` (build, no upload; the
    explicit targets replace the ``targets`` option of platformio.ini).

    ``port``: optional target port; a provider port (sim://) lets the provider build (simulated).
    ``chip``: the project chip (data/chips.json id). With it ``build_precheck`` runs before pio starts and refuses
    a wrong MCU (``chip_mismatch``) or a too old pinned platform (``platform_too_old``); without it (offline builds
    of a bare folder) nothing is compared."""
    action = "board.build"
    result: dict[str, Any] | None = None
    pre: dict[str, Any] = {"warnings": [], "source_ids": [], "mcu": None}
    try:
        if chip is not None:
            pre = build_precheck(_check_project(project_dir), _check_env(env), chip)
        if port is not None:
            provider = provider_for(_check_port(port))
            if provider is not None:
                return _with_precheck(_provider_call(action, provider, "build", str(project_dir), env), pre, chip)
        pdir = _check_project(project_dir)
        env = _check_env(env)
        if timeout is None:
            timeout = float(_settings.load()["build_timeout_seconds"])
        exe = _tool("pio")
        log = _Log("build", on_line)
        try:
            # explicit targets: without -t PlatformIO would run the `targets` of platformio.ini (upload, monitor)
            argv = [exe, "run", "-d", str(pdir), "-e", env]
            for target in clitools.PIO_BUILD_TARGETS:
                argv += ["-t", target]
            res = clitools.run(argv, timeout=timeout, cwd=str(pdir), tail=200, on_line=log)
        finally:
            log.close()
        lines = res["out_tail"]
        sizes = parse_sizes(lines)
        result = {"ok": False, "duration_s": res["duration_s"], "ram_pct": sizes["ram_pct"],
                  "flash_pct": sizes["flash_pct"], "log_ref": log.ref, "log_tail": _tail(lines)}
        if res["timed_out"]:
            raise BenchError("timeout", f"build did not finish within {timeout:g} s",
                             "raise build_timeout_seconds in the plugin settings")
        if res["rc"] != 0:
            result["errors"] = [ln.strip()[:LOG_LINE_CHARS] for ln in lines if _COMPILE_ERR_RE.match(ln.strip())][:5]
            raise _pio_failure(lines, "build", res["rc"])
        meta = metadata(pdir, env)
        elf = Path(meta["prog_path"]) if meta["prog_path"] else None
        if elf is None or not elf.is_file():
            raise BenchError("elf_missing", f"build finished but the ELF is missing ({elf})", "build again")
        sha = sha256_file(elf)
        images = image_hashes(elf)
    except BenchError as e:
        return _with_precheck(from_error(action, e, result=result), pre, chip)
    result.update({"ok": True, "elf": _rel(elf, pdir), "elf_path": str(elf), "elf_sha256": sha, "images": images,
                   "ram_used": sizes["ram_used"], "ram_total": sizes["ram_total"], "flash_used": sizes["flash_used"],
                   "flash_total": sizes["flash_total"], "env": env, "project_dir": str(pdir),
                   "addr2line": meta["addr2line"], "toolchain_prefix": meta["toolchain_prefix"]})
    ram = "?" if sizes["ram_pct"] is None else f"{sizes['ram_pct']:g}"
    fl = "?" if sizes["flash_pct"] is None else f"{sizes['flash_pct']:g}"
    summary = f"Build ok in {res['duration_s']:.1f} s: RAM {ram} %, flash {fl} %."
    checks = [check("board.build", "passed", f"pio run -e {env} -t checkprogsize -t buildprog exit 0, ELF {sha[:8]}")]
    return _with_precheck(envelope(action, summary, result, checks=checks, sources=_resolve_sources([_SRC_METADATA])),
                          pre, chip)


def _with_precheck(env: dict[str, Any], pre: Mapping[str, Any], chip: str | None) -> dict[str, Any]:
    """The build answer plus the pre-check's warnings, sources and (when the MCU was compared) a passed check."""
    if chip is None or not isinstance(env, dict):
        return env
    out = dict(env)
    out["warnings"] = [*pre.get("warnings", []), *env.get("warnings", [])]
    have = {s.get("id") for s in env.get("sources", [])}
    out["sources"] = [*env.get("sources", []),
                      *[s for s in _resolve_sources(list(dict.fromkeys(pre.get("source_ids", [])))) if s["id"] not in have]]
    if pre.get("mcu") is not None:
        out["checks"] = [check("board.build.chip", "passed", f"env builds for {pre['mcu']}, the project chip {chip}"),
                         *env.get("checks", [])]
        res = out.get("result")
        if out.get("ok") is True and isinstance(res, dict):
            out["result"] = {**res, "chip": chip}  # stored in last_build; the flash check compares it
    return out


# --------------------------------------------------------------------------------------------- flash

def _guard_verdict(action: str, guard: Any) -> dict[str, Any] | None:
    """None if the approval check (``guard()``, e.g. functools.partial(guard.check_flash, ...)) says OK, otherwise an
    error envelope. Fails closed: missing guard, exceptions and unexpected values refuse the flash."""
    if guard is None or not callable(guard):
        return fail(action, "not_confirmed", "flash needs an approval check", "the caller must pass guard=check_flash")
    try:
        verdict = guard()
    except BenchError as e:
        return from_error(action, e)
    except Exception as e:  # noqa: BLE001 - a broken approval check refuses the flash
        return fail(action, "not_confirmed", f"approval check failed ({type(e).__name__})")
    if verdict is None:
        return None
    if isinstance(verdict, Mapping) and verdict.get("ok") is True and verdict.get("error") is None:
        return None
    if isinstance(verdict, Mapping) and verdict.get("ok") is False:
        out = dict(verdict)
        out["action"] = action
        if not validate_envelope(out):
            return out
    return fail(action, "not_confirmed", "approval check returned an unexpected value")


def project_config(project_dir: str | Path, *, timeout: float = CONFIG_TIMEOUT_S) -> list[Any]:
    """``pio project config --json-output -d <dir>``: the computed configuration ([[section, [[option, value], ...]],
    ...]) with ``extra_configs``, ``extends`` and ``[env]`` resolved. Reads only: PlatformIO Core 6.2.0
    (project/commands/config.py) parses the ini with ProjectConfig and prints ``to_json()``; the builder (SCons) and
    with it the project's extra_scripts do not run (checked offline with a marker script)."""
    pdir = Path(project_dir)
    exe = _tool("pio")
    res = clitools.run([exe, "project", "config", "--json-output", "-d", str(pdir)], timeout=timeout, cwd=str(pdir),
                       tail=400)
    lines = res["out_tail"]
    if res["timed_out"]:
        raise BenchError("timeout", f"pio project config did not finish within {timeout:g} s")
    if res["rc"] != 0:
        raise _pio_failure(lines, "project config", res["rc"])
    for line in reversed(lines):
        if line.lstrip().startswith("[["):
            try:
                data = json.loads(line)
            except ValueError:
                break
            if isinstance(data, list):
                return data
    raise BenchError("tool_failed", "pio project config printed no configuration", "check platformio.ini with pio")


def _env_options(config: list[Any], env: str) -> dict[str, Any]:
    """Options of ``[env:<env>]`` in the computed configuration (``project_config``); {} without that env."""
    opts: dict[str, Any] = {}
    for item in config:
        if isinstance(item, list | tuple) and len(item) == 2 and item[0] == f"env:{env}" and isinstance(item[1], list):
            opts = {str(o[0]): o[1] for o in item[1] if isinstance(o, list | tuple) and len(o) == 2}
    return opts


def _upload_baud(opts: Mapping[str, Any]) -> int:
    """The env's ``upload_speed`` (9600..4000000), else FLASH_BAUD."""
    try:
        baud = int(str(opts.get("upload_speed") or "").strip())
    except ValueError:
        return FLASH_BAUD
    return baud if 9600 <= baud <= 4_000_000 else FLASH_BAUD


def _upload_config_refusal(config: list[Any], env: str) -> BenchError | None:
    """Refuse uploads the project itself redirects or extends with an erase (computed configuration)."""
    opts = _env_options(config, env)
    if not opts:
        return BenchError("invalid_args", f"the PlatformIO configuration has no [env:{env}]",
                          "use the [env:<name>] from platformio.ini")
    hint = ("Circuit Bench writes the built images itself with esptool and never runs the project's own upload: "
            "remove upload_protocol = custom, upload_command and erase flags (also in extra_configs/extends)")
    if str(opts.get("upload_protocol") or "").strip().lower() == "custom":
        return BenchError("invalid_args", f"[env:{env}] sets upload_protocol = custom (the project's own upload command)",
                          hint)
    if str(opts.get("upload_command") or "").strip() not in ("", "[]"):
        return BenchError("invalid_args", f"[env:{env}] sets upload_command (the project's own upload command)", hint)
    flags = opts.get("upload_flags") or []
    flags = [str(f) for f in (flags if isinstance(flags, list) else [flags])]
    if any(_ERASE_RE.search(f) or f.strip() == "-e" for f in flags):
        return BenchError("invalid_args", f"[env:{env}] upload_flags ask for a flash erase; Circuit Bench never erases",
                          hint)
    return None


def _ini_requests_erase(pdir: Path) -> bool:
    try:
        text = (pdir / "platformio.ini").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        code = re.split(r"[;#]", line, maxsplit=1)[0]
        if _ERASE_RE.search(code):
            return True
    return False


def _check_images(expected: Any, elf: Path) -> None:
    """The flash images must be the ones of the approved build. ``expected``: last_build.images
    ({name: sha256}); without it (projects built before images were recorded) only the age check of firmware.bin."""
    build_dir = elf.parent
    image = elf.with_suffix(".bin")
    if not image.is_file():
        raise BenchError("elf_missing", f"no firmware image {image.name} next to {elf.name}", "run build first")
    if not isinstance(expected, Mapping) or not expected:
        if image.stat().st_mtime_ns < elf.stat().st_mtime_ns:
            raise BenchError("elf_mismatch", f"{image.name} is older than {elf.name}: the image does not belong to the "
                             "approved ELF", "build again and approve the new firmware")
        return
    if image.name not in expected:
        raise BenchError("elf_mismatch", f"the approved build has no hash of {image.name}",
                         "rebuild (bench_board build) and approve the new firmware")
    for name, want in sorted(expected.items()):
        if name not in image_names(elf):
            continue
        path = build_dir / name
        actual = sha256_file(path) if path.is_file() else None
        if actual != str(want).lower():
            what = "is missing" if actual is None else f"changed after the build ({actual[:8]}… != {str(want)[:8]}…)"
            raise BenchError("elf_mismatch", f"{name} {what}", "rebuild (bench_board build) and approve the new firmware")


def image_info(image: str | Path) -> dict[str, str]:
    """``esptool image-info <image>`` (reads the file, opens no port): {"chip", "flash_mode", "flash_freq"} of the app
    image header that ``pio run`` wrote with the board's settings (platform-espressif32 6.9.0 builder/main.py:
    ``elf2image --flash_mode ${__get_board_flash_mode} --flash_freq ${__get_board_f_image}``). ``flash`` passes the
    same values to ``write-flash`` as PlatformIO's upload does, so the bootloader header gets them, too."""
    exe = _tool("esptool")
    with tempfile.TemporaryDirectory(prefix="cb-esptool-") as tmp:
        res = clitools.run([exe, "image-info", str(image)], timeout=IMAGE_INFO_TIMEOUT_S, cwd=tmp,
                           env_extra={"HOME": tmp}, tail=200)
    found: dict[str, str] = {}
    for line in res["out_tail"]:
        for key, rx in _IMAGE_INFO_RE.items():
            m = rx.match(line.strip())
            if m and key not in found:
                found[key] = m.group(1)
    if res["timed_out"] or res["rc"] != 0 or len(found) != len(_IMAGE_INFO_RE):
        raise BenchError("tool_failed", f"esptool image-info could not read {Path(image).name}",
                         "build again; check that esptool works (esptool version)")
    return {"chip": found["type"].lower().replace("-", ""), "flash_mode": found["flash_mode"].lower(),
            "flash_freq": found["flash_freq"].lower()}


def _write_list(meta: Mapping[str, Any], elf: Path, expected: Any) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    """(offset, file) pairs for ``write-flash`` and their description for the result. Images from the build folder
    were checked against ``expected`` (``_check_images``); others (boot_app0.bin of the framework) are hashed here."""
    pairs: list[tuple[str, Path]] = []
    for item in meta.get("flash_images") or []:
        path = Path(item["path"])
        if not path.is_file():
            raise BenchError("elf_missing", f"flash image {path.name} is missing ({path})", "run build first")
        pairs.append((item["offset"], path))
    pairs.append((meta.get("app_offset") or "0x10000", elf.with_suffix(".bin")))
    offsets = [int(o, 16) for o, _ in pairs]
    if len(set(offsets)) != len(offsets):
        raise BenchError("tool_failed", "pio project metadata lists two images at the same offset",
                         "check platformio.ini (board_build.partitions, extra images)")
    known = expected if isinstance(expected, Mapping) else {}
    described = [{"offset": o, "name": f.name, "sha256": known.get(f.name) if f.parent == elf.parent and f.name in known
                  else sha256_file(f)} for o, f in pairs]
    return pairs, described


class _MacWatch:
    """``stop_when`` of the flash run: true at the first ``MAC:`` line other than ``want``. Remembers the first
    MAC esptool printed and whether an erase/write line came before the stop."""

    def __init__(self, want: str | None):
        self.want = want
        self.mac: str | None = None
        self.foreign: str | None = None
        self.write_seen = False
        self.written_before_stop = False

    def __call__(self, line: str) -> bool:
        text = line.strip()
        if _WRITE_LINE_RE.match(text):
            self.write_seen = True
        m = _MAC_RE.match(text)
        if m is None:
            return False
        mac = m.group(1).lower()
        if self.mac is None:
            self.mac = mac
        if self.want is not None and mac != self.want and self.foreign is None:
            self.foreign = mac
            self.written_before_stop = self.write_seen
            return True
        return False


def _identity_refusal(port: str, identity: Mapping[str, Any] | None, watch: _MacWatch, result: dict[str, Any],
                      warns: list[dict[str, Any]]) -> BenchError:
    """The board answering on ``port`` is not the approved one; ``result``/``warns`` are updated in place."""
    want = (identity or {}).get("mac")
    got = watch.foreign or watch.mac
    written = watch.written_before_stop or (watch.foreign is None and watch.write_seen)
    result.update({"ok": False, "mac": got, "written": written})
    if written:
        warns.append(warning("board_identity", "danger", f"esptool reported MAC {got} only after it had started to "
                             f"erase or write flash on {port}: the board there (not the approved {want}) may now hold "
                             "part of this firmware"))
        return BenchError("not_confirmed", f"esptool reported MAC {got}, the approved board is {want}; stopped after "
                          "writing had started", IDENTITY_HINT)
    return BenchError("not_confirmed", f"esptool reported MAC {got}, the approved board is {want}; stopped before "
                      "writing", IDENTITY_HINT)


def flash(project_dir: str | Path, env: str, port: str, *, expected_elf_sha256: str, guard: Callable[[], Any] | None,
          timeout: float = FLASH_TIMEOUT_S, on_line: Callable[[str], None] | None = None,
          expected_images: Mapping[str, str] | None = None, devkit: str | None = None,
          expected_board: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Action board.flash: write the already built firmware with ``esptool --chip C --port P --baud B write-flash -z
    --flash-mode M --flash-freq F --flash-size detect <offset image>...`` (bootloader, partition table, boot_app0 and
    the app at the offsets of ``pio project metadata`` ``extra.flash_images``/``application_offset``, the same set
    PlatformIO's ``-t upload`` writes after a build). ``--chip`` is the chip of the app image: esptool stops before
    writing if the connected chip is another one.

    ``devkit``: the project's board; its ``flash_hint`` replaces the generic BOOT/RESET
    hints of connection errors. The chip of the detected board is checked by ``guard`` (``chip_mismatch``).

    ``guard``: zero-argument approval check, e.g. ``functools.partial(guard.check_flash, via="tool", settings=...,
    project=..., port=..., cron=False)``; it returns None (OK) or an error envelope. Anything else refuses.

    Order: inputs -> hardware switch -> ``guard()`` (no tool runs without its OK) -> the computed PlatformIO
    configuration (``pio project config``: no upload_protocol = custom, no upload_command, no erase flags)
    -> ELF hash against
    ``expected_elf_sha256`` and the image hashes against ``expected_images`` (last_build.images; ``elf_mismatch``)
    -> image header (``image_info``) -> broker pauses the port -> write. Never erases (beyond the sectors written),
    never builds.

    ``expected_board``: ``project.board.detected``. Real ports only:
    - before any tool, the USB identity on the port (VID, PID, serial number) must equal ``usb_id``;
    - esptool is stopped at a ``MAC:`` line other than ``mac`` (``clitools.run(stop_when=...)``; esptool prints
      it before the stub upload, so before any write) -> ``not_confirmed``, ``result.written`` tells whether an erase
      or write line came first (then also the warning ``board_identity``, danger);
    - check ``board.flash.board_identity``: passed (same MAC), not_checked (no ``MAC:`` line, e.g. Secure
      Download Mode; warning ``board_identity_unchecked``). Only the ``MAC:`` line counts, not ``BASE MAC``."""
    action = "board.flash"
    warns: list[dict[str, Any]] = []
    ids: list[str] = [_SRC_FLASH_IMAGES, _SRC_UPLOAD_ARGS, _SRC_WRITE_FLASH, _SRC_OBSERVED_WT32]
    result: dict[str, Any] | None = None
    refusal_checks: list[dict[str, Any]] = []
    provider = None
    try:
        port = _check_port(port)
        sha = _check_sha(expected_elf_sha256)
        provider = provider_for(port)
        pdir = Path(str(project_dir))
        if provider is None:
            pdir = _check_project(project_dir)
            env = _check_env(env)
            _check_real_port(port)
            _require_hardware()
        refused = _guard_verdict(action, guard)
        if refused is not None:
            return refused
        if provider is not None:
            check_hash = getattr(provider, "elf_sha256", None)
            if callable(check_hash):
                try:
                    actual = check_hash(str(project_dir), env)
                except Exception as e:  # noqa: BLE001 - provider bugs become an error envelope
                    err = serialport.local_error(e)
                    raise err or BenchError("tool_failed", f"simulated elf_sha256 failed: {type(e).__name__}") from None
                if actual and str(actual).lower() != sha:
                    raise BenchError("elf_mismatch", "the firmware changed after the approved build",
                                     "build again and approve the new firmware")
            with serialport.pause(port):
                return _provider_call(action, provider, "flash", str(project_dir), env, port, port=port)
        identity = _expected_identity(expected_board)
        raw = _port_lookup(port)
        try:
            _check_usb_identity(port, identity, raw)
        except BenchError as e:
            refusal_checks.append(check("board.flash.board_identity", "failed", e.message))
            raise
        if _ini_requests_erase(pdir):
            raise BenchError("invalid_args", "platformio.ini asks for a flash erase; Circuit Bench never erases flash",
                             "remove the erase option from platformio.ini (upload_flags) and retry")
        config = project_config(pdir)
        refused_cfg = _upload_config_refusal(config, env)
        if refused_cfg is not None:
            raise refused_cfg
        baud = _upload_baud(_env_options(config, env))
        info = _real_entry(raw) if raw is not None else None
        _check_exists(port)
        kind = info["kind"] if info else None
        if kind == "usb_cdc_app":
            warns.append(_no_reset_warning(port))
            ids += [_SRC_TINYUSB, _SRC_OBSERVED, _SRC_BOOT]
            if on_line is not None:
                on_line(f"warning: {NO_AUTO_RESET_HINT}")
        meta = metadata(pdir, env)
        elf = Path(meta["prog_path"]) if meta["prog_path"] else None
        if elf is None or not elf.is_file():
            raise BenchError("elf_missing", f"no built firmware for env {env} ({elf})", "run build first")
        actual = sha256_file(elf)
        if actual != sha:
            raise BenchError("elf_mismatch", f"{elf.name} changed after the approved build ({actual[:8]}… != {sha[:8]}…)",
                             "build again and approve the new firmware")
        if not meta.get("flash_images"):  # never the app alone onto an unknown bootloader/partition table
            raise BenchError("elf_missing", "pio project metadata lists no bootloader or partition table; "
                             "Circuit Bench writes only complete image sets",
                             "check board_build.partitions in platformio.ini and the platform version (pio project "
                             "metadata must list bootloader.bin and partitions.bin), then build again")
        _check_images(expected_images, elf)
        pairs, written = _write_list(meta, elf, expected_images)
        header = image_info(elf.with_suffix(".bin"))
        exe = _tool("esptool")
        log = _Log("flash", on_line)
        argv = [exe, "--chip", header["chip"], "--port", port, "--baud", str(baud), "--before", "default-reset",
                "--after", "hard-reset", "write-flash", "-z", "--flash-mode", header["flash_mode"],
                "--flash-freq", header["flash_freq"], "--flash-size", "detect"]
        for offset, path in pairs:
            argv += [offset, str(path)]
        watch = _MacWatch(identity["mac"] if identity else None)
        try:
            with serialport.pause(port), tempfile.TemporaryDirectory(prefix="cb-esptool-") as tmp:
                # another reader swallows esptool's replies and leaves the board half-written -> port_busy first
                serialport.check_port_free(port)
                # empty cwd and HOME (as in detect): no esptool.cfg/setup.cfg/tox.ini from the user's folders applies
                res = clitools.run(argv, timeout=timeout, cwd=tmp, env_extra={"HOME": tmp}, tail=300, on_line=log,
                                   hardware=True, stop_when=watch if identity else None)
        finally:
            log.close()
        lines = res["out_tail"]
        result = {"ok": False, "port": port, "elf_sha256": sha, "duration_s": res["duration_s"], "log_ref": log.ref,
                  "log_tail": _tail(_drop_progress(lines)), "images": written}
        board_hint, hint_ids = flash_hint(devkit)
        if res.get("stopped") or (identity and watch.mac is not None and watch.mac != identity["mac"]):
            refusal_checks.append(check("board.flash.board_identity", "failed",
                                        f"esptool read MAC {watch.foreign or watch.mac}, the detected board is "
                                        f"{(identity or {}).get('mac')}"))
            raise _identity_refusal(port, identity, watch, result, warns)
        if res["timed_out"]:
            ids += hint_ids
            raise BenchError("timeout", f"upload did not finish within {timeout:g} s", board_hint or BOOTLOADER_HINT)
        if res["rc"] != 0:
            wrong = next((m for m in (_WRONG_CHIP_RE.search(ln) for ln in lines) if m), None)
            if wrong:
                raise BenchError("chip_mismatch", f"the connected board is an {wrong.group(1)}, the firmware is built "
                                 f"for {header['chip']}: nothing was written", "detect the board again and build for its "
                                 "chip")
            ids += hint_ids
            raise _esptool_failure(lines, port, kind, res["rc"], board_hint)
    except BenchError as e:
        return from_error(action, e, result=result, warnings=warns, sources=_resolve_sources(ids),
                          checks=refusal_checks, simulated=provider is not None)
    mac = watch.mac or next((m.group(1).lower() for m in (_MAC_RE.match(ln.strip()) for ln in lines) if m), None)
    verified = sum("Hash of data verified" in ln for ln in lines) >= len(pairs)
    result.update({"ok": True, "mac": mac, "verified": verified, "elf": str(elf)})
    summary = f"Flashed {elf.name} ({sha[:8]}…) to {port} in {res['duration_s']:.1f} s."
    checks = [check("board.flash.elf_hash", "passed", f"ELF matches the approved build ({sha[:8]}…)")]
    if identity is None:
        pass  # no expected_board (direct callers of the helper): the identity check is not part of this flash
    elif mac is None:
        checks.append(check("board.flash.board_identity", "not_checked", "esptool printed no MAC: line"))
        warns.append(warning("board_identity_unchecked", "caution", f"esptool printed no MAC address (e.g. Secure "
                             f"Download Mode): Circuit Bench could not confirm that the board on {port} is the "
                             f"detected one ({identity['mac']})"))
    else:
        checks.append(check("board.flash.board_identity", "passed", f"esptool read MAC {mac}, the detected board"))
    checks.append(check("board.flash.verified", "passed" if verified else "not_checked",
                        f"esptool verified all {len(pairs)} written images" if verified
                        else f"fewer than {len(pairs)} 'Hash of data verified' lines in the log"))
    return envelope(action, summary, result, checks=checks, warnings=warns, sources=_resolve_sources(ids))

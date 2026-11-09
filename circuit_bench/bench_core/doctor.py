"""Doctor (action ``doctor.run``): what the bench can reach on this machine.

Checks: pio / esptool / addr2line found (+ versions), serial port group (dialout or uucp), visible ports (hardware
switch respected: with hardware off only sim:// ports), Python dependencies importable, data folder
writable, hardware switch and approval state. Runs only ``--version``-style commands, never touches a board.

The toolchain of every chip in the register: ``tools.toolchains`` =
``{<chip>: {"addr2line": bool, "prefix": "<toolchain prefix>"}}``; ``toolchains()`` is shared with ``GET /health``.
"""
from __future__ import annotations

import importlib.metadata
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from . import chips, clitools, crash, guard, storage
from . import settings as _settings
from .contracts import BenchError, check, envelope, fail, warning

logger = logging.getLogger(__name__)
ACTION = "doctor.run"
SERIAL_GROUPS = ("dialout", "uucp")  # Debian/Ubuntu/Fedora, Arch
DEPENDENCIES = (("schemdraw", "schemdraw"), ("serial", "pyserial"))
TOOL_IDS = ("pio", "esptool", "addr2line")  # command line tools: a missing one is "not found", not a failure
NO_TOOLS_NOTE = "The simulation, pin checks, calculators and schematics work without these tools; real boards need them."
TOOLCHAIN_MISSING_HINT = "build once for this chip; pio installs its toolchain"


def _pio_packages() -> Path:
    core = os.environ.get("PLATFORMIO_CORE_DIR")
    base = Path(core).expanduser() if core else Path(os.environ.get("HOME") or Path.home()) / ".platformio"
    return base / "packages"


def _addr2line_by_prefix(prefix: str) -> str | None:
    """``<prefix>-addr2line`` on PATH, else in a PlatformIO toolchain package (same search as crash.find_addr2line:
    ``packages/toolchain-*/bin/``; the glob also matches the unified ``toolchain-xtensa-esp-elf`` of espressif32
    8.0.0 and versioned ``toolchain-…@<version>`` folders)."""
    name = f"{prefix}-addr2line"
    hit = clitools.find(name)
    if hit:
        return hit
    for candidate in sorted(_pio_packages().glob(f"toolchain-*/bin/{name}")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_addr2line(chip: str) -> str | None:
    """The chip's addr2line: crash.find_addr2line for the chips the decoder knows, else the register prefix."""
    try:
        path = crash.find_addr2line(chip)
    except BenchError:  # a chip of the register the decoder does not know (yet)
        path = None
    return path or _addr2line_by_prefix(chips.toolchain_prefix(chip))


def toolchains() -> dict[str, dict[str, Any]]:
    """``{<chip>: {"addr2line": bool, "prefix": str}}`` for every chip of the register, in register order."""
    return {chip: {"addr2line": find_addr2line(chip) is not None, "prefix": chips.toolchain_prefix(chip)}
            for chip in chips.ids()}


def toolchain_warning(tc: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """One ``info`` warning naming the chips without a toolchain (None if none or all are missing)."""
    missing = [f"{c} ({v['prefix']})" for c, v in tc.items() if not v["addr2line"]]
    if not missing or len(missing) == len(tc):
        return None
    return warning("toolchain_missing", "info", f"no addr2line for {', '.join(missing)}: {TOOLCHAIN_MISSING_HINT}")


def _tool(name: str, override: str, version_args: tuple[str, ...]) -> dict[str, Any]:
    path = clitools.find(name, override or None)
    return {"path": path, "version": clitools.version(path, version_args) if path else None,
            "override": bool(override)}


def _groups() -> dict[str, Any]:
    try:
        import grp
    except ImportError:  # not POSIX
        return {"group": None, "member": None, "reason": "no POSIX groups on this system"}
    mine = set(os.getgroups()) | {os.getgid()}
    for name in SERIAL_GROUPS:
        try:
            gid = grp.getgrnam(name).gr_gid
        except KeyError:
            continue
        return {"group": name, "member": gid in mine}
    return {"group": None, "member": None, "reason": f"none of {', '.join(SERIAL_GROUPS)} exists"}


def _dependencies() -> dict[str, Any]:
    """Importable (not only installed): Hermes does not install missing plugin dependencies, it only warns."""
    out = {}
    for module, dist in DEPENDENCIES:
        try:
            __import__(module)  # like the lazy `import` statements of the tools
            found = True
        except Exception:  # noqa: BLE001 - ImportError or a broken install: either way not usable
            found = False
        version = None
        if found:
            try:
                version = importlib.metadata.version(dist)
            except importlib.metadata.PackageNotFoundError:
                version = "unknown"
        out[dist] = {"installed": found, "version": version}
    return out


def _data_dir() -> dict[str, Any]:
    try:
        path = storage.data_dir()
    except BenchError as e:
        return {"path": None, "writable": False, "reason": e.message}
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".doctor-", delete=True) as f:
            f.write(b"ok")
        return {"path": str(path), "writable": True}
    except OSError as e:
        return {"path": str(path), "writable": False, "reason": type(e).__name__}


def _ports() -> dict[str, Any]:
    from . import board  # imports serialport; pyserial itself stays lazy
    env = board.ports()
    if not env["ok"]:
        return {"ok": False, "error": (env.get("error") or {}).get("message"), "ports": []}
    items = env["result"]["ports"]
    return {"ok": True, "ports": [{k: p.get(k) for k in ("device", "kind", "description", "simulated")} for p in items],
            "warnings": [w["message"] for w in env.get("warnings", [])][:5]}


def run() -> dict[str, Any]:
    """Action doctor.run: result envelope, never raises."""
    try:
        return _run()
    except Exception as e:  # noqa: BLE001 - an action returns an envelope
        logger.warning("circuit-bench: doctor failed (%s)", type(e).__name__)
        return fail(ACTION, "tool_failed", f"doctor failed ({type(e).__name__})")


def _run() -> dict[str, Any]:
    cfg = _settings.load()
    checks: list[dict[str, Any]] = []
    warns: list[dict[str, Any]] = []
    hw = _settings.hardware_enabled(cfg)

    pio = _tool("pio", cfg.get("pio_path") or "", ("--version",))
    esptool = _tool("esptool", cfg.get("esptool_path") or "", ("version",))
    for name, info, hint in (("pio", pio, _settings.tool_hint("pio")), ("esptool", esptool, _settings.tool_hint("esptool"))):
        if info["path"]:
            checks.append(check(f"doctor.{name}", "passed", f"{info['path']} ({info['version'] or 'version unknown'})"))
        else:
            checks.append(check(f"doctor.{name}", "failed", f"{name} not found"))
            warns.append(warning(f"{name}_missing", "caution", f"{name} not found: {hint}"))
    addr2line = {}
    versions: dict[str, str | None] = {}  # esp32c3 and esp32c6 share one riscv32-esp-elf binary
    for chip in chips.ids():
        path = find_addr2line(chip)
        if path and path not in versions:
            versions[path] = clitools.version(path)
        addr2line[chip] = {"path": path, "version": versions.get(path) if path else None}
    toolchain = {c: {"addr2line": v["path"] is not None, "prefix": chips.toolchain_prefix(c)}
                 for c, v in addr2line.items()}
    found = [c for c, v in addr2line.items() if v["path"]]
    checks.append(check("doctor.addr2line", "passed" if found else "failed",
                        f"found for {', '.join(found)}" if found else "no ESP toolchain addr2line found"))
    if not found:
        warns.append(warning("addr2line_missing", "info", "crash frames need the toolchain addr2line: build the "
                             "project once with PlatformIO (it installs the toolchain)"))
    tc_warning = toolchain_warning(toolchain)
    if tc_warning is not None:
        warns.append(tc_warning)

    groups = _groups()
    if groups["group"] is None:
        checks.append(check("doctor.serial_group", "skipped", groups.get("reason", "")))
    elif groups["member"]:
        checks.append(check("doctor.serial_group", "passed", f"member of {groups['group']}"))
    else:
        checks.append(check("doctor.serial_group", "failed", f"not a member of {groups['group']}"))
        warns.append(warning("serial_group", "caution", f"add your user to the {groups['group']} group "
                             f"to open serial ports: as administrator usermod -aG {groups['group']} $USER, then log in again"))

    ports = _ports()
    deps = _dependencies()
    missing = [d for d, v in deps.items() if not v["installed"]]
    checks.append(check("doctor.dependencies", "failed" if missing else "passed",
                        f"missing: {', '.join(missing)}" if missing else
                        ", ".join(f"{d} {v['version']}" for d, v in deps.items())))
    for dist in missing:
        warns.append(warning("dependency_missing", "caution", f"{dist} is not installed: "
                             + ("schematics cannot be drawn" if dist == "schemdraw" else "real serial ports are unavailable")))

    data = _data_dir()
    checks.append(check("doctor.data_dir", "passed" if data["writable"] else "failed",
                        data["path"] or data.get("reason", "")))
    if not data["writable"]:
        warns.append(warning("data_dir", "danger", f"the data folder is not writable: {data.get('reason', '')}"))

    invalid = _settings.invalid_keys()
    checks.append(check("doctor.settings", "failed" if invalid else "passed",
                        f"unreadable: {', '.join(invalid)}" if invalid else "all settings readable"))
    if invalid:
        warns.append(warning("settings_invalid", "caution", f"unreadable plugin settings ({', '.join(invalid)}) use a "
                             "safe value instead (switches: real hardware and flashing off, port approval on; numbers "
                             f"and paths: the default): check them in {_settings.SETTINGS_PATH}"))

    bypassed = guard.approvals_bypassed()
    if not hw:
        warns.append(warning("hardware_off", "info", "hardware access is off: only simulated boards (sim://) are "
                             "reachable" + (" (CIRCUIT_BENCH_HW=off)" if os.environ.get(_settings.ENV_HW, "").lower() == "off"
                                            else " (setting hardware_access)")))
    if bypassed:
        warns.append(warning("approvals_bypassed", "caution", "approvals are off, YOLO is on or Hermes may "
                             "auto-approve (approvals.single_query_mode / unattended_mode): the agent cannot "
                             "flash real boards or open their ports; use the Bench UI"))
    if _settings.env_settings_ignored():
        warns.append(warning("settings_env_ignored", "caution", f"{_settings.ENV_SETTINGS} is set in Hermes' "
                             "environment but ignored (test switch, needs CIRCUIT_BENCH_DEV_GUARD=1): the plugin "
                             "settings from Hermes' config apply; unset the variable"))

    result = {
        "tools": {"pio": pio, "esptool": esptool, "addr2line": addr2line, "toolchains": toolchain},
        "serial_group": groups,
        "ports": ports,
        "dependencies": deps,
        "data_dir": data,
        "hardware": {"enabled": hw, "env": os.environ.get(_settings.ENV_HW) or None,
                     "hardware_access": bool(cfg.get("hardware_access", True))},  # effective value
        "settings": {k: cfg.get(k) for k in ("allow_flash", "approve_serial", "default_baud", "monitor_max_seconds",
                                             "build_timeout_seconds")},
        "approvals_bypassed": bypassed,
    }
    failed = [c["id"].split(".", 1)[1] for c in checks if c["status"] == "failed"]
    n_ports = len(ports.get("ports") or [])
    absent = [f for f in failed if f in TOOL_IDS]
    broken = [f for f in failed if f not in TOOL_IDS]
    parts = ([f"not found: {', '.join(absent)}"] if absent else []) + ([f"failed: {', '.join(broken)}"] if broken else [])
    summary = (f"Doctor: {len(checks) - len(failed)}/{len(checks)} checks passed"
               + (f" ({'; '.join(parts)})" if parts else "")
               + f"; {n_ports} port{'s' if n_ports != 1 else ''} visible; hardware {'on' if hw else 'off'}."
               + (f" {NO_TOOLS_NOTE}" if absent else ""))
    return envelope(ACTION, summary, result, checks=checks, warnings=warns)

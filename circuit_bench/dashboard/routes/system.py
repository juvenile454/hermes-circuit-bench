"""GET /health, GET /doctor."""
import importlib.metadata
import re
import threading
import time
from typing import Any

from fastapi import APIRouter

from .common import PLUGIN_ID, Core, guarded, respond, threaded

TOOL_VERSION_TTL_S = 600.0
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def dist_version(name: str) -> str | None:
    """Installed version of a distribution, without importing it (schemdraw/pyserial stay lazy)."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - broken metadata counts as missing
        return None


def plugin_version(core: Core) -> str | None:
    manifest = core.package_dir / "plugin.yaml"
    try:
        m = re.search(r"^version:\s*['\"]?([^'\"\s]+)", manifest.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        return None
    return m.group(1) if m else None


def _tool_versions(core: Core, cfg: dict[str, Any]) -> dict[str, Any]:
    """{"pio": "6.2.0"|None, "esptool": "5.6.0"|None, "addr2line": bool, "toolchains": {<chip>: {addr2line, prefix}}};
    versions cached per process and path. ``addr2line``: any chip's toolchain found."""
    cache = core.runtime.get("api.tool_versions", lambda: {"lock": threading.Lock(), "entries": {}})
    out: dict[str, Any] = {}
    for name, args in (("pio", ("--version",)), ("esptool", ("version",))):
        path = core.clitools.find(name, cfg.get(f"{name}_path") or None)
        if not path:
            out[name] = None
            continue
        with cache["lock"]:
            hit = cache["entries"].get(path)
        if hit is None or time.monotonic() - hit[1] > TOOL_VERSION_TTL_S:
            line = core.clitools.version(path, args)
            m = _VERSION_RE.search(line or "")
            # found but silent or without a version number: "unknown" (None means: not found)
            hit = (m.group(1) if m else (line or "unknown")[:40], time.monotonic())
            with cache["lock"]:
                cache["entries"][path] = hit
        out[name] = hit[0]
    toolchains = core.doctor.toolchains()
    out["addr2line"] = any(v["addr2line"] for v in toolchains.values())
    out["toolchains"] = toolchains
    return out


def health_envelope(core: Core) -> dict[str, Any]:
    from .serial_stream import epoch

    cfg = core.settings.load()
    hw = core.settings.hardware_enabled(cfg)
    deps = {"schemdraw": dist_version("schemdraw"), "pyserial": dist_version("pyserial")}
    tools = _tool_versions(core, cfg)
    version = plugin_version(core)
    result = {"plugin": PLUGIN_ID, "version": version, "hermes": dist_version("hermes-agent"), "dependencies": deps,
              "tools": tools, "hardware_access": hw, "allow_flash": cfg.get("allow_flash") is True,
              "epoch": epoch(core)}
    warn = core.contracts.warning
    warns = [warn("dependency_missing", "caution", f"{dist} is not installed: {what} is not available",
                  [])
             for dist, what in (("schemdraw", "schematics"), ("pyserial", "real serial ports")) if deps[dist] is None]
    if not hw:
        warns.append(warn("hardware_off", "info", "hardware access is off: only simulated boards (sim://) are reachable"))
    tc_warning = core.doctor.toolchain_warning(tools["toolchains"])
    if tc_warning is not None:
        warns.append(tc_warning)
    bits = [f"pio {tools['pio']}" if tools["pio"] else "pio missing",
            f"esptool {tools['esptool']}" if tools["esptool"] else "esptool missing",
            "hardware access on" if hw else "hardware access off (simulated boards only)"]
    summary = f"Circuit Bench {version or '?'} ready: {', '.join(bits)}."
    return core.contracts.envelope("health", summary, result, warnings=warns, simulated=not hw)


def register(router: APIRouter, core: Core) -> None:
    @router.get("/health")
    @guarded(core, "health")
    async def health():
        return respond(await threaded(health_envelope, core))

    @router.get("/doctor")
    @guarded(core, "doctor.run")
    async def doctor():
        mod = core.optional("doctor")
        run = getattr(mod, "run", None) if mod is not None else None
        if not callable(run):
            return respond(core.contracts.fail("doctor.run", "dependency_missing",
                                               "the bench doctor is not part of this installation (bench_core/doctor.py)",
                                               "update Circuit Bench; GET /health shows tools and dependencies"))
        env = await threaded(run)
        return respond(env)

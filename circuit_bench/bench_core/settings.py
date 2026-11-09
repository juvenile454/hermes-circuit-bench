"""Plugin settings: defaults overlaid with plugins.entries.circuit-bench.settings.

Tests and scripts pass settings as JSON in CIRCUIT_BENCH_SETTINGS_JSON (then Hermes' config is not read). That test
switch counts only with CIRCUIT_BENCH_DEV_GUARD=1 or outside Hermes (``hermes_cli.config`` not importable): a
leftover from a developer shell must not replace the user's settings (allow_flash, hardware_access) in a real Hermes;
there it is ignored and the doctor warns (``env_settings_ignored``).
The hardware switch CIRCUIT_BENCH_HW=off overrides hardware_access.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
PLUGIN_ID = "circuit-bench"
ENV_SETTINGS = "CIRCUIT_BENCH_SETTINGS_JSON"
ENV_HW = "CIRCUIT_BENCH_HW"
ENV_DEV_GUARD = "CIRCUIT_BENCH_DEV_GUARD"  # same name as storage.ENV_DEV_GUARD

DEFAULTS: dict[str, Any] = {
    "allow_flash": False,
    "approve_serial": True,
    "hardware_access": True,
    "default_baud": 115200,
    "monitor_max_seconds": 120,
    "build_timeout_seconds": 900,
    "pio_path": "",
    "esptool_path": "",
}
_INT_RANGES = {"default_baud": (300, 5_000_000), "monitor_max_seconds": (1, 3600), "build_timeout_seconds": (30, 7200)}
# an unreadable switch takes the safe value, not the default (hardware_access defaults to true, so a typo
# such as "of" would otherwise open real boards). approve_serial true = ask before opening a port.
SAFE_BOOLS = {"allow_flash": False, "approve_serial": True, "hardware_access": False}
_TRUE_WORDS = frozenset({"true", "on", "yes", "1"})
_FALSE_WORDS = frozenset({"false", "off", "no", "0"})
_INVALID = object()


def _coerce(key: str, value: Any) -> Any:
    """The setting value, or ``_INVALID`` (the caller then uses the safe value or the default)."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return value == 1
        if isinstance(value, str):
            word = value.strip().lower()
            if word in _TRUE_WORDS:
                return True
            if word in _FALSE_WORDS:
                return False
        return _INVALID
    if isinstance(default, int):
        if isinstance(value, bool):
            return _INVALID
        try:
            n = int(value)
        except (TypeError, ValueError):
            return _INVALID
        lo, hi = _INT_RANGES[key]
        return n if lo <= n <= hi else _INVALID
    return value.strip() if isinstance(value, str) else _INVALID


def _from_hermes() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config  # read only; the public config path
    except ImportError:
        return {}
    try:
        cfg = load_config() or {}
        entry = ((cfg.get("plugins") or {}).get("entries") or {}).get(PLUGIN_ID) or {}
        values = entry.get("settings") or {}
        return values if isinstance(values, dict) else {}
    except Exception as e:  # noqa: BLE001 - settings must never break a tool
        logger.warning("circuit-bench: could not read plugin settings (%s), using defaults", type(e).__name__)
        return {}


def _hermes_present() -> bool:
    try:
        import hermes_cli.config  # noqa: F401 - read only; the same public module _from_hermes uses
    except ImportError:
        return False
    except Exception:  # noqa: BLE001 - a broken Hermes import still means: running next to Hermes
        return True
    return True


def env_settings_allowed() -> bool:
    """CIRCUIT_BENCH_SETTINGS_JSON counts only for development (CIRCUIT_BENCH_DEV_GUARD=1) or outside Hermes."""
    return os.environ.get(ENV_DEV_GUARD) == "1" or not _hermes_present()


def env_settings_ignored() -> bool:
    """True when CIRCUIT_BENCH_SETTINGS_JSON is set but ignored (inside Hermes without the development guard)."""
    return os.environ.get(ENV_SETTINGS) is not None and not env_settings_allowed()


def _raw_values() -> dict[str, Any]:
    raw = os.environ.get(ENV_SETTINGS)
    if raw is not None and not env_settings_allowed():
        raw = None  # a test switch left in a real Hermes: the user's settings win (doctor warns)
    if raw is not None:
        try:
            values = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            values = {}
    else:
        values = _from_hermes()
    return values if isinstance(values, dict) else {}


def _resolve() -> tuple[dict[str, Any], list[str]]:
    out = dict(DEFAULTS)
    invalid: list[str] = []
    for key, value in _raw_values().items():
        if key not in DEFAULTS or value is None:  # None: key present but empty in config.yaml = not set
            continue
        v = _coerce(key, value)
        if v is _INVALID:
            invalid.append(key)
            v = SAFE_BOOLS.get(key, DEFAULTS[key])
        out[key] = v
    if os.environ.get(ENV_HW, "").strip().lower() == "off":
        out["hardware_access"] = False
    return out, sorted(invalid)


def load() -> dict[str, Any]:
    return _resolve()[0]


def invalid_keys() -> list[str]:
    """Settings whose value could not be read (they use the safe value or the default); the doctor lists them."""
    return _resolve()[1]


# Hints with the labels of plugin.yaml config_schema: the user finds the switch by its name in the app.
SETTINGS_PATH = "Settings → Plugins → Circuit Bench → Agent settings"
FLASH_DISABLED_HINT = f"turn on 'Allow flashing real boards' in {SETTINGS_PATH}"
PROJECT_LIST_HINT = "list the projects with bench_project action=list, or create one"
SERIAL_GROUP_HINT = ("add your user to the dialout group as administrator (usermod -aG dialout $USER), then log in "
                     "again (Arch Linux: group uucp)")
_TOOL_HINTS = {"pio": "install PlatformIO Core (e.g. pipx install platformio)",
               "platformio": "install PlatformIO Core (e.g. pipx install platformio)",
               "esptool": "pipx install esptool", "esptool.py": "pipx install esptool"}


def sim_only_hint() -> str:
    """Why real boards are off and how to switch them on: names CIRCUIT_BENCH_HW only when it is set."""
    value = os.environ.get(ENV_HW)
    if value is not None and value.strip().lower() == "off":
        return (f"hardware access is switched off by {ENV_HW}={value.strip()} in Hermes' environment: unset it to use "
                "real boards; sim:// ports work without hardware")
    return (f"turn on 'Access real hardware' (hardware_access) in {SETTINGS_PATH} to use real boards; sim:// ports "
            "work without hardware")


def tool_hint(name: str) -> str:
    """How to get a missing command line tool (pio, esptool), or name its path setting."""
    base = os.path.basename(str(name))
    setting = "PlatformIO executable" if base in ("pio", "platformio") else (
        "esptool executable" if base in ("esptool", "esptool.py") else None)
    install = _TOOL_HINTS.get(base, f"install {base}")
    return f"{install}, or set '{setting}' in {SETTINGS_PATH}" if setting else install


def hardware_enabled(settings: dict[str, Any] | None = None) -> bool:
    """False when CIRCUIT_BENCH_HW=off or hardware_access is false: only sim:// ports are reachable."""
    if os.environ.get(ENV_HW, "").strip().lower() == "off":
        return False
    return bool((settings if settings is not None else load()).get("hardware_access", True))

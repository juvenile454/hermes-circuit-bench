"""Plugin settings: defaults overlaid with plugins.entries.circuit-bench.settings.

Tests and scripts pass settings as JSON in CIRCUIT_BENCH_SETTINGS_JSON (then Hermes' config is not read). That test
switch counts only with CIRCUIT_BENCH_DEV_GUARD=1 or outside Hermes (``hermes_cli.config`` not importable): a
leftover from a developer shell must not replace the user's settings (allow_flash, hardware_access) in a real Hermes;
there it is ignored and the doctor warns (``env_settings_ignored``).
The hardware switch CIRCUIT_BENCH_HW=off overrides hardware_access.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
from collections.abc import Mapping
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


_ABSENT = "absent"  # no Hermes in the process: the package hermes_cli itself is missing
_ERROR = "error"  # Hermes is there, but its configuration could not be read
_OK = "ok"


def _no_hermes(e: BaseException) -> bool:
    """True only for a missing package ``hermes_cli`` (tests, any run outside Hermes).

    A missing package is a ModuleNotFoundError named ``hermes_cli``. A package blocked with
    ``sys.modules["hermes_cli"] = None`` (Python's marker for "not importable") is missing too; Python names the
    submodule in that error. A missing submodule ``hermes_cli.config`` of a package that is there, a missing name
    ``load_config``, an ImportError of a dependency or any other exception means: Hermes is there and its
    configuration cannot be read (the safe values). A renamed or broken Hermes must never silently fall back to the
    defaults, which leave real hardware on.
    """
    if not isinstance(e, ModuleNotFoundError):
        return False
    if e.name == "hermes_cli":
        return True
    return e.name == "hermes_cli.config" and "hermes_cli" in sys.modules and sys.modules["hermes_cli"] is None


def _read_hermes_config(last_known_good: bool = False) -> tuple[str, Any]:
    """Hermes' configuration, read only: ``(_OK, mapping)``, ``(_ABSENT, None)`` or ``(_ERROR, "<reason>")``.

    Never raises: only a missing package ``hermes_cli`` is ``_ABSENT``; any other exception of the import (a missing
    ``hermes_cli.config`` or ``load_config``, an ImportError of a dependency) and of ``load_config()`` itself is
    ``_ERROR``. SystemExit counts too (a config reader must not end a tool call); KeyboardInterrupt does not. A
    config with ``read_error`` set and a config that is not a mapping are ``_ERROR`` as well; with
    ``last_known_good=True`` a mapping with ``read_error`` set (the fallback Hermes itself keeps using: the last
    known good config, its defaults or empty) is ``_OK``.
    """
    try:
        from hermes_cli.config import load_config  # read only; the public config path
    except (Exception, SystemExit) as e:  # noqa: BLE001 - a broken Hermes import: Hermes is there, config unreadable
        if _no_hermes(e):
            return _ABSENT, None
        return _ERROR, (f"Hermes' config reader could not be imported ({type(e).__name__})"
                        if isinstance(e, ImportError) else type(e).__name__)
    try:
        cfg = load_config()  # a copy; never load_config_readonly (its result must not be touched)
        # Hermes does not raise on a broken config.yaml: it returns a dict with ``read_error`` set (the last known
        # good config or its defaults). Checked by attribute, the class is not imported.
        failed = getattr(cfg, "read_error", None)
    except (Exception, SystemExit) as e:  # noqa: BLE001 - whatever the reader raises: unreadable
        return _ERROR, type(e).__name__
    if failed is not None and not (last_known_good and isinstance(cfg, Mapping)):
        return _ERROR, (f"config.yaml could not be read ({type(failed).__name__})" if isinstance(failed, BaseException)
                        else "config.yaml could not be read")
    if not isinstance(cfg, Mapping):
        return _ERROR, f"config is {type(cfg).__name__}"
    return _OK, cfg


def hermes_value(*path: str, default: Any = None, last_known_good: bool = False) -> Any:
    """A value of Hermes' configuration, e.g. ``hermes_value("approvals", "timeout", default=300)``.

    No Hermes (the package hermes_cli is missing), a Hermes whose config reader cannot be imported, any exception
    while reading, a config that Hermes could not read (``read_error`` set; its last known
    good values are not used), a missing key, a key whose value is empty (YAML null) or a path through a value that
    is not a mapping: ``default``. Never raises and never writes the configuration; the value comes back raw (no
    type check, the caller checks it), a mapping or list as a copy. 0 and false are values, not missing.

    ``last_known_good=True`` is for values that must match what Hermes itself uses in this process (the tool
    deadline): a config that Hermes could not read but still serves as a mapping (``read_error`` set: the last
    known good config, Hermes' defaults or empty) is read like a readable one. Every other case above still gives
    ``default``. Safety switches must not use it: for them an unreadable config means the safe value.
    """
    if not path or not all(isinstance(key, str) for key in path):
        return default
    status, cfg = _read_hermes_config(last_known_good=last_known_good is True)
    if status != _OK:
        return default
    try:
        node: Any = cfg
        for key in path:
            if not isinstance(node, Mapping) or key not in node:
                return default
            node = node[key]
        return default if node is None else copy.deepcopy(node)
    except (Exception, SystemExit):  # noqa: BLE001 - an odd mapping or an uncopyable value: not readable
        return default


_SETTINGS_PATH_KEYS = ("plugins", "entries", PLUGIN_ID, "settings")


def _from_hermes() -> tuple[dict[str, Any], str | None]:
    """``(values, None)``, or ``({}, reason)`` when Hermes is there but its configuration cannot be read.

    No Hermes (the package hermes_cli is missing): ``({}, None)``, the defaults. Any other import failure:
    unreadable. A missing or empty (null) level of
    ``plugins.entries.circuit-bench.settings`` means "not set" (the defaults); a level that is not a mapping cannot
    be read (the safe values): a mistyped settings block must not leave real boards switched on.
    """
    status, cfg = _read_hermes_config()
    if status == _ABSENT:
        return {}, None
    if status == _ERROR:
        return {}, cfg
    try:
        node: Any = cfg
        for key in _SETTINGS_PATH_KEYS:
            node = node.get(key)
            if node is None:
                return {}, None
            if not isinstance(node, Mapping):
                return {}, f"{key} is {type(node).__name__}"
        return dict(node), None
    except (Exception, SystemExit) as e:  # noqa: BLE001 - an odd mapping: not readable
        return {}, type(e).__name__


def _hermes_present() -> bool:
    """False only when the package hermes_cli is missing; a broken or renamed Hermes import still means: Hermes."""
    try:
        import hermes_cli.config  # noqa: F401 - read only; the same public module _from_hermes uses
    except (Exception, SystemExit) as e:  # noqa: BLE001 - a broken Hermes import still means: running next to Hermes
        return not _no_hermes(e)
    return True


def env_settings_allowed() -> bool:
    """CIRCUIT_BENCH_SETTINGS_JSON counts only for development (CIRCUIT_BENCH_DEV_GUARD=1) or outside Hermes."""
    return os.environ.get(ENV_DEV_GUARD) == "1" or not _hermes_present()


def env_settings_ignored() -> bool:
    """True when CIRCUIT_BENCH_SETTINGS_JSON is set but ignored (inside Hermes without the development guard)."""
    return os.environ.get(ENV_SETTINGS) is not None and not env_settings_allowed()


def _raw_values() -> tuple[dict[str, Any], str | None]:
    """``(values, None)``, or ``({}, reason)`` when the settings exist but cannot be read."""
    raw = os.environ.get(ENV_SETTINGS)
    if raw is not None and not env_settings_allowed():
        raw = None  # a test switch left in a real Hermes: the user's settings win (doctor warns)
    if raw is None:
        return _from_hermes()
    if not raw.strip():
        return {}, None
    try:
        values = json.loads(raw)
    except ValueError:  # JSONDecodeError, or a number too long to convert
        return {}, f"{ENV_SETTINGS} is not valid JSON"
    except RecursionError:
        return {}, f"{ENV_SETTINGS} is nested too deeply"
    if not isinstance(values, dict):
        return {}, f"{ENV_SETTINGS} is not a JSON object"
    return values, None


# The unreadable-settings warning is logged once per process: settings are read on every tool call.
_unreadable_logged = False


def _log_unreadable(reason: str) -> None:
    global _unreadable_logged
    if _unreadable_logged:
        return
    _unreadable_logged = True
    logger.warning("circuit-bench: the plugin settings could not be read (%s): real hardware and flashing stay off, "
                   "port approval stays on, numbers and paths use their defaults (logged once)", reason)


def _resolve() -> tuple[dict[str, Any], list[str], str | None]:
    out = dict(DEFAULTS)
    invalid: list[str] = []
    values, error = _raw_values()
    if error is not None:
        # settings that exist but cannot be read: the safe switches, not the defaults (hardware_access defaults to
        # true, so a broken config.yaml would otherwise switch real boards on)
        _log_unreadable(error)
        out.update(SAFE_BOOLS)
    for key, value in values.items():
        if key not in DEFAULTS or value is None:  # None: key present but empty in config.yaml = not set
            continue
        v = _coerce(key, value)
        if v is _INVALID:
            invalid.append(key)
            v = SAFE_BOOLS.get(key, DEFAULTS[key])
        out[key] = v
    if os.environ.get(ENV_HW, "").strip().lower() == "off":
        out["hardware_access"] = False
    return out, sorted(invalid), error


def load() -> dict[str, Any]:
    return _resolve()[0]


def invalid_keys() -> list[str]:
    """Settings whose value could not be read (they use the safe value or the default); the doctor lists them."""
    return _resolve()[1]


def read_error() -> str | None:
    """Why the plugin settings as a whole could not be read (exception type or a short reason), or None.

    Then the switches use their safe values (real hardware and flashing off, port approval on) and numbers and paths
    their defaults. No Hermes in the process is not an error (the defaults apply)."""
    return _resolve()[2]


# Hints with the labels of plugin.yaml config_schema: the user finds the switch by its name in the app.
SETTINGS_PATH = "Settings → Plugins → Circuit Bench → Agent settings"
FLASH_DISABLED_HINT = f"turn on 'Allow flashing real boards' in {SETTINGS_PATH}"
PROJECT_LIST_HINT = "list the projects with bench_project action=list, or create one"
SERIAL_GROUP_HINT = ("add your user to the dialout group as administrator (usermod -aG dialout $USER), then log in "
                     "again (Arch Linux: group uucp)")
_TOOL_HINTS = {"pio": "install PlatformIO Core (e.g. pipx install platformio)",
               "platformio": "install PlatformIO Core (e.g. pipx install platformio)",
               "esptool": "pipx install esptool", "esptool.py": "pipx install esptool"}


UNREADABLE_SENTENCE = "the plugin settings could not be read from Hermes' configuration, so real boards stay off"


def unreadable_hint(reason: str | None = None) -> str:
    """What to do when the plugin settings cannot be read (``read_error()`` is set)."""
    where = ENV_SETTINGS if reason is not None and reason.startswith(ENV_SETTINGS) else "Hermes' config.yaml"
    return (f"{UNREADABLE_SENTENCE}: check {where}, then run the bench doctor again; sim:// ports work without "
            "hardware")


def sim_only_hint() -> str:
    """Why real boards are off and how to switch them on: names CIRCUIT_BENCH_HW only when it is set."""
    value = os.environ.get(ENV_HW)
    error = read_error()
    if error is not None:
        also = (f" ({ENV_HW}={value.strip()} is set as well)" if value is not None and value.strip().lower() == "off"
                else "")
        return unreadable_hint(error) + also
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

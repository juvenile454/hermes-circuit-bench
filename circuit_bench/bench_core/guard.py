"""Approval logic for real boards.

``check_flash`` and ``check_serial`` return ``None`` (OK) or an error envelope; they never raise for a refusal and
fail closed: unexpected input refuses. ``board.flash`` takes ``check_flash`` as a zero-argument callable::

    functools.partial(guard.check_flash, via="tool", settings=cfg, project=proj, port=port, cron=False)

Order in ``check_flash`` (first match wins):

1. ``cron`` (anything but ``False``)            -> ``unattended_blocked``
2. ``sim://`` port                              -> OK (nothing physical is written)
3. hardware switch off                          -> ``sim_only``
4. ``via="tool"`` and approvals bypassed        -> ``unattended_blocked`` (YOLO / ``approvals.mode: off`` /
                                                  approve-like ``single_query_mode`` or ``unattended_mode``)
5. ``allow_flash`` not true                     -> ``flash_disabled``
6. no detection, other port, no MAC             -> ``not_confirmed`` ("run detect and build first")
7. no successful build with ``elf_sha256``      -> ``not_confirmed`` ("run detect and build first")
8. ``via="route"``: ``confirm`` differs from ``{port, mac, elf_sha256}`` of the project -> ``not_confirmed``
9. detected chip is not the project chip        -> ``chip_mismatch`` (``board.detected.chip``
   through the chip register; an unknown or missing name refuses with "detect again"; the ``sim://`` port is
   exempt in step 2, it reports an ESP32-S3). Last on purpose: the earlier refusals keep their codes.

``check_serial``: steps 1-3, then step 4 only while ``approve_serial`` is on. ``approve_serial`` itself is the
hook's business (it asks before a tool opens a port), not the guard's.

Only public Hermes APIs (catalog rule 9): ``HERMES_YOLO_MODE`` from the environment and
``hermes_cli.config.load_config`` (read only: ``approvals.mode``, ``single_query_mode``, ``unattended_mode``).
A session-scoped ``/yolo`` and one-shot runs (``hermes -z``, which bypass approvals by design) are not visible to
plugins: there Hermes passes agent builds, flashes and port openings without asking. The hard lock against agent
flashes stays ``allow_flash`` (default off); keep it off while they are in use.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from . import settings as _settings
from .contracts import BenchError, fail

logger = logging.getLogger(__name__)

SIM_PREFIX = "sim://"
VIA = ("tool", "route")
FLASH_ACTION = "board.flash"
SERIAL_ACTION = "serial.open"
TRUTHY = frozenset({"1", "true", "yes", "on"})  # Hermes' truthy strings
# approvals.single_query_mode / approvals.unattended_mode: Hermes reads these as "approve" for the values below
# (tools/approval_context.py ``_binary_approval_mode``), and then approves plugin approvals without asking anyone.
AUTO_APPROVE_KEYS = ("single_query_mode", "unattended_mode")
AUTO_APPROVE_VALUES = frozenset({"approve", "off", "allow", "yes"})

DETECT_HINT = "run detect and build first"
BYPASS_FLASH_MSG = ("approvals are off, YOLO is active or Hermes may auto-approve (approvals.single_query_mode / "
                    "unattended_mode): the agent cannot flash real boards")
BYPASS_FLASH_HINT = "flash from the Bench UI (it always asks) or turn approvals on"
BYPASS_SERIAL_MSG = ("approvals are off, YOLO is active or Hermes may auto-approve (approvals.single_query_mode / "
                     "unattended_mode): the agent cannot open real serial ports")
BYPASS_SERIAL_HINT = "open the port from the Bench UI (it always asks) or turn approvals on"


def is_sim(port: Any) -> bool:
    """True for a simulated port (``sim://...``); such ports never reach hardware."""
    return isinstance(port, str) and port.strip().startswith(SIM_PREFIX)


def _auto_approve(value: Any) -> bool:
    """An approve-like value of ``approvals.single_query_mode``/``unattended_mode``, read exactly like Hermes does:
    ``tools/approval_context.py:347-354`` ``_binary_approval_mode`` (Hermes ``bf0203a7``/``a9ff9799``)
    computes ``str(value).lower().strip() in {"approve", "off", "allow", "yes"}``. A YAML bool
    (``yes`` -> True -> "true") therefore means deny. An exception from ``str()`` propagates: approvals_bypassed
    then fails closed (unreadable config)."""
    return str(value).strip().lower() in AUTO_APPROVE_VALUES


def approvals_bypassed(settings_cfg: Mapping[str, Any] | None = None) -> bool:
    """True if Hermes may run without approval prompts: ``HERMES_YOLO_MODE`` truthy, ``approvals.mode: off``, or an
    approve-like ``approvals.single_query_mode``/``approvals.unattended_mode`` (``-q`` runs, webhooks and API
    sessions approve without a human). Plugins cannot see which kind of session runs a tool, so the last two count
    for every session (conservative); the Bench UI routes are not affected (they always ask in the dialog).

    ``settings_cfg``: an already loaded Hermes config (the dict of ``hermes_cli.config.load_config()``); without it
    the config is loaded here. No Hermes in the process (ImportError) -> False. Any other problem reading the
    config -> True (fail closed)."""
    if os.environ.get("HERMES_YOLO_MODE", "").strip().lower() in TRUTHY:
        return True
    try:
        if settings_cfg is None:
            try:
                from hermes_cli.config import load_config  # public plugin API (allowlist of plugins validate)
            except ImportError:
                return False
            settings_cfg = load_config()
        if not isinstance(settings_cfg, Mapping):
            raise TypeError(f"config is {type(settings_cfg).__name__}")
        approvals = settings_cfg.get("approvals")
        if approvals is None:
            return False
        if not isinstance(approvals, Mapping):
            raise TypeError(f"approvals is {type(approvals).__name__}")
        mode = approvals.get("mode", "manual")
        if mode is False:  # YAML 1.1 reads a bare `mode: off` as false; Hermes treats it as off
            return True
        if isinstance(mode, str) and mode.strip().lower() == "off":
            return True
        return any(key in approvals and _auto_approve(approvals.get(key)) for key in AUTO_APPROVE_KEYS)
    except Exception as e:  # noqa: BLE001 - unreadable approval state counts as bypassed (fail closed)
        logger.warning("circuit-bench: approval mode unreadable (%s), treating approvals as off", type(e).__name__)
        return True


def _refuse(action: str, code: str, message: str, hint: str | None = None) -> dict[str, Any]:
    return fail(action, code, message, hint)


def _settings_of(settings: Any) -> Mapping[str, Any] | None:
    if settings is None:
        return _settings.load()
    return settings if isinstance(settings, Mapping) else None


def normalize_port(port: Any) -> str:
    """``serialport.normalize_port`` (realpath of /dev links; raises BenchError for anything but a serial device)."""
    from . import serialport  # lazy: serialport pulls in the broker
    return serialport.normalize_port(port)


def _same_port(a: Any, b: Any) -> bool:
    try:
        return normalize_port(a) == normalize_port(b)
    except BenchError:
        return False


def _common(action: str, via: Any, settings: Any, port: Any, cron: Any) -> tuple[dict[str, Any] | None, Mapping | None]:
    """Steps 1-3. Returns (refusal or None, settings); (None, None) means: simulated port, OK."""
    if via not in VIA:
        return _refuse(action, "invalid_args", f"unknown approval path {str(via)[:20]!r}", "via is tool or route"), None
    if cron is not False:
        what = "flash boards" if action == FLASH_ACTION else "open serial ports"
        return _refuse(action, "unattended_blocked", f"scheduled jobs (cron) cannot {what}",
                       "run it in a chat or from the Bench UI"), None
    if not isinstance(port, str) or not port.strip():
        return _refuse(action, "invalid_args", "port must be a device path like /dev/ttyACM0 or a sim:// port"), None
    if is_sim(port):
        return None, None
    try:
        normalize_port(port)
    except BenchError as e:
        return _refuse(action, e.code, e.message, e.hint), None
    cfg = _settings_of(settings)
    if cfg is None:
        return _refuse(action, "invalid_args", "settings must be the plugin settings object"), None
    if not _settings.hardware_enabled(dict(cfg)):
        return _refuse(action, "sim_only", "hardware access is off: real boards are not reachable",
                       _settings.sim_only_hint()), None
    return None, cfg


def _project_of(project: Any) -> Mapping[str, Any] | None:
    if isinstance(project, Mapping) and project.get("action") == "project.get":  # a whole project.get envelope
        result = project.get("result") if project.get("ok") is True else None
        project = result.get("project") if isinstance(result, Mapping) else None
    return project if isinstance(project, Mapping) else None


def _get(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, Mapping):
            return None
        obj = obj.get(key)
    return obj


def _norm(value: Any) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _chip_refusal(action: str, proj: Mapping[str, Any], detected: Mapping[str, Any]) -> dict[str, Any] | None:
    """Step 9: ``chip_mismatch`` unless the detected chip (esptool name -> chip register) is the project chip."""
    from .board import chip_from_esptool  # lazy: board pulls in serialport
    want = _get(proj, "board", "chip")
    name = detected.get("chip")
    got = chip_from_esptool(name)
    shown = str(name)[:60] if isinstance(name, str) and name.strip() else "no chip name"
    if got is None:
        return _refuse(action, "chip_mismatch", f"the detected chip ({shown}) is unknown, the project chip is "
                       f"{str(want)[:20]}: nothing is flashed", "connect the board and detect again")
    if got != want:
        return _refuse(action, "chip_mismatch", f"the detected board is an {got} ({shown}), but project "
                       f"{str(proj.get('id'))[:40]} is set to {str(want)[:20]}: nothing is flashed",
                       f"connect the {str(want)[:20]} board and detect again, or set the project chip to {got} "
                       "(set_board)")
    return None


def check_flash(*, via: str, settings: Mapping[str, Any] | None, project: Mapping[str, Any] | None, port: str,
                confirm: Mapping[str, Any] | None = None, cron: bool, precheck: bool = False) -> dict[str, Any] | None:
    """Approval check before ``board.flash``: None (OK) or an error envelope with action ``board.flash``.

    ``via``: ``tool`` (agent; the pre_tool_call hook asked the user) or ``route`` (Bench UI; its dialog sends
    ``confirm = {port, mac, elf_sha256}``). ``settings``: ``settings.load()`` (None loads it). ``project``: the
    project object (or its ``project.get`` envelope). ``cron``: True inside a scheduled job. ``precheck``
    (``GET /board/flash/check``): skip only step 8, the comparison with ``confirm`` (the dialog has not
    asked yet); every other step runs as for the flash."""
    action = FLASH_ACTION
    try:
        refused, cfg = _common(action, via, settings, port, cron)
        if refused is not None or cfg is None:
            return refused  # refusal, or a simulated port (OK)
        if via == "tool" and approvals_bypassed():
            return _refuse(action, "unattended_blocked", BYPASS_FLASH_MSG, BYPASS_FLASH_HINT)
        if cfg.get("allow_flash") is not True:
            return _refuse(action, "flash_disabled", "flashing real boards is off (setting allow_flash is false)",
                           _settings.FLASH_DISABLED_HINT + ", then try again")
        proj = _project_of(project)
        if proj is None:
            return _refuse(action, "not_confirmed", "no bench project to check the board against", DETECT_HINT)
        detected = _get(proj, "board", "detected")
        if not isinstance(detected, Mapping):
            return _refuse(action, "not_confirmed", "the board was not detected yet", DETECT_HINT)
        if not _same_port(detected.get("port"), port):
            return _refuse(action, "not_confirmed",
                           f"the detected board is on {str(detected.get('port'))[:60]}, not on {port.strip()[:60]}",
                           DETECT_HINT)
        mac = _norm(detected.get("mac"))
        if mac is None:
            return _refuse(action, "not_confirmed", "the detected board has no MAC address", DETECT_HINT)
        build = _get(proj, "firmware", "last_build")
        sha = _norm(build.get("elf_sha256")) if isinstance(build, Mapping) and build.get("ok") is True else None
        if sha is None:
            return _refuse(action, "not_confirmed", "no successful build with an ELF hash", DETECT_HINT)
        if via == "route" and not precheck:
            if not isinstance(confirm, Mapping):
                return _refuse(action, "not_confirmed", "the flash was not confirmed in the Bench UI",
                               "confirm port, MAC and firmware in the flash dialog")
            given = (_norm(confirm.get("mac")), _norm(confirm.get("elf_sha256")))
            if not _same_port(confirm.get("port"), port) or given != (mac, sha):
                return _refuse(action, "not_confirmed",
                               "the confirmation does not match the detected board and the last build",
                               "detect and build again, then confirm the new values")
        refused = _chip_refusal(action, proj, detected)
        if refused is not None:
            return refused
        built_for = build.get("chip") if isinstance(build, Mapping) else None
        want = _get(proj, "board", "chip")
        if built_for is not None and built_for != want:  # the ELF was checked for another chip
            return _refuse(action, "chip_mismatch", f"the last build was made for an {str(built_for)[:20]}, but project "
                           f"{str(proj.get('id'))[:40]} is set to {str(want)[:20]}: nothing is flashed",
                           "build again for the project chip, then flash")
        return None
    except Exception as e:  # a broken check refuses (logged)
        logger.exception("circuit-bench: flash approval check failed")
        return _refuse(action, "not_confirmed", f"approval check failed ({type(e).__name__})")


def check_serial(*, via: str, settings: Mapping[str, Any] | None, port: str, cron: bool,
                 action: str = SERIAL_ACTION) -> dict[str, Any] | None:
    """Approval check before a real serial port is opened (detect, monitor, serial.open): None (OK) or an error
    envelope with ``action`` (default ``serial.open``; detect/monitor pass ``board.detect``/``serial.monitor``)."""
    try:
        refused, cfg = _common(action, via, settings, port, cron)
        if refused is not None or cfg is None:
            return refused
        if via == "tool" and cfg.get("approve_serial") is not False and approvals_bypassed():
            return _refuse(action, "unattended_blocked", BYPASS_SERIAL_MSG, BYPASS_SERIAL_HINT)
        return None
    except Exception as e:
        logger.exception("circuit-bench: serial approval check failed")
        return _refuse(action, "not_confirmed", f"approval check failed ({type(e).__name__})")

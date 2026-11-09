"""pre_tool_call hook for ``bench_board``: approval directives for builds that start PlatformIO and board access.

Decisions (``None`` = no directive):

| call                               | decision                                                             |
|------------------------------------|----------------------------------------------------------------------|
| other tools, ports                 | None                                                                 |
| detect/monitor/flash on ``sim://`` | None (nothing physical; the handler still refuses cron flashes)      |
| build: PlatformIO does not start   | None (a ``sim://`` build without pio or without all packages is      |
|                                    | simulated: no project script runs)                                   |
| build: ``build_target`` error      | sim port: None (the handler answers); real target: block             |
| build: PlatformIO starts           | (a real target, or a ``sim://`` build with pio and all packages)     |
|   in cron                          | block ("scheduled jobs (cron) cannot run real builds ...")           |
|   OK                               | approve, ``rule_key = circuit-bench:build:sha256(dir|env)`` (dir     |
|                                    | resolved: a symlink or ``..`` to the same folder shares the key);    |
|                                    | a ``sim://`` port adds that the build is a real offline build        |
| flash/detect/monitor in cron       | block                                                                |
| flash: ``guard.check_flash`` error | block (allow_flash off, hardware off, approvals bypassed, no detect/build) |
| flash without ``elf_sha256`` arg   | block ("pass elf_sha256 from the last bench_board build")             |
| flash: ``elf_sha256`` not last build | block (elf_mismatch)                                                 |
| flash: OK                          | approve, ``rule_key = circuit-bench:flash:sha256(port|mac|elf_sha256 arg)``; |
|                                    | stores (project, port, mac, sha) in the Host for the handler         |
| detect/monitor: ``check_serial`` error | block (hardware off, approvals bypassed)                         |
| detect/monitor, ``approve_serial`` | approve, ``rule_key = circuit-bench:detect|monitor:sha256(port)``    |
| detect/monitor, approve_serial off | None                                                                 |
| internal error (real port, build)  | block (fail closed)                                                  |

The handlers repeat every check themselves (``tools``), so a missing hook or an approval bypass never lets a real
flash through; a real build without the hook or in cron is refused by the handler too. ``approve`` is answered by
Hermes' approval gate (once/session/always/deny); with ``approvals.mode: off`` or YOLO the gate would pass silently,
which is why ``guard`` blocks those cases first for flash/detect/monitor. A build touches no board, so it only asks.
A session-scoped ``/yolo`` and one-shot runs (``hermes -z``, which bypass approvals by design) are not visible to
plugins: there Hermes passes agent builds, flashes and port openings without asking; ``allow_flash`` (default off)
stays the hard lock against agent flashes.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
from collections.abc import Callable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

TOOL = "bench_board"
HOOK_ACTIVE = False  # True once register() registered the hook (tools read Host.hook_active of that registration)
FLASH_KEY = "circuit-bench:flash:"
# one key per serial action: "always" for the monitor (opens the port) must not cover detect (esptool resets the
# board into the bootloader), and the other way round
BUILD_KEY = "circuit-bench:build:"
SERIAL_KEYS = {"detect": "circuit-bench:detect:", "monitor": "circuit-bench:monitor:"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def flash_rule_key(port: str, mac: str, elf_sha256: str) -> str:
    return FLASH_KEY + _sha(f"{port}|{mac}|{elf_sha256}")


def build_rule_key(folder: str, env: str) -> str:
    """``circuit-bench:build:<sha256(dir|env)>``: "always" covers exactly this folder and env."""
    return BUILD_KEY + _sha(f"{folder}|{env}")


def serial_rule_key(action: str, port: str) -> str:
    """``circuit-bench:detect:<sha256(port)>`` or ``circuit-bench:monitor:<sha256(port)>``."""
    return SERIAL_KEYS[action] + _sha(port)


def _block(what: str, env_or_text: Mapping[str, Any] | str) -> dict[str, str]:
    if isinstance(env_or_text, str):
        text = env_or_text
    else:
        err = env_or_text.get("error") or {}
        text = f"{err.get('message') or env_or_text.get('summary') or 'refused'} ({err.get('code', 'refused')})"
        if err.get("hint"):
            text += f"; {err['hint']}"
    return {"action": "block", "message": f"Circuit Bench blocked {what}: {text}."}


def _flash(host: Any, args: Mapping[str, Any]) -> dict[str, str] | None:
    from . import tools
    from .bench_core import guard
    port = args.get("port")
    if isinstance(port, str) and guard.is_sim(port):
        return None
    try:
        proj, port = tools.flash_target(args)
    except tools._Return as r:
        return _block("the flash", r.env)
    if guard.is_sim(port):
        return None
    if host.cron():
        return _block("the flash", "scheduled jobs (cron) cannot flash boards")
    refusal = guard.check_flash(via="tool", settings=None, project=proj, port=port, cron=False)
    if refusal is not None:
        return _block("the flash", refusal)
    try:
        given = tools.flash_sha_arg(args)
    except tools._Return as r:
        return _block("the flash", r.env)
    if given is None:
        return _block("the flash", "pass elf_sha256 from the last bench_board build (the approval names exactly that "
                      "firmware)")
    det = (proj.get("board") or {}).get("detected") or {}
    fw = proj.get("firmware") or {}
    sha = str((fw.get("last_build") or {}).get("elf_sha256") or "").lower()
    mac = str(det.get("mac") or "").lower()
    if not sha.startswith(given):
        return _block("the flash", f"elf_sha256 {given[:16]}… is not the last build ({sha[:12]}…) (elf_mismatch); "
                      f"run bench_board build with project {proj['id']} again, then flash with its elf_sha256")
    host.remember_flash(proj["id"], port, mac, sha)  # the handler flashes only exactly this
    message = (f"Flash firmware {fw.get('env')} from {fw.get('dir')} to {det.get('chip') or 'the board'} "
               f"(MAC {mac}) on {port}? ELF {given} (exactly the last build, not rebuilt; Circuit Bench adds no "
               "erase; project scripts (extra_scripts) still run)")
    return {"action": "approve", "message": message, "rule_key": flash_rule_key(port, mac, given)}


SIM_BUILD_NOTE = " The board is simulated; the build is a real offline build."


def _build(host: Any, args: Mapping[str, Any]) -> dict[str, str] | None:
    from . import tools
    from .bench_core import guard
    sim_port = guard.is_sim(args.get("port"))
    try:
        target = tools.build_target(args)
    except tools._Return as r:
        if sim_port:
            return None  # the handler answers bad arguments itself
        return _block("the build", r.env)
    if not tools.build_asks(target):
        return None
    if not (target.dir / "platformio.ini").is_file():
        return None  # nothing can build here: the handler refuses (no platformio.ini) before pio starts, ask nothing
    if host.cron():
        return _block("the build", tools.BUILD_CRON_MSG)
    message = (f"Build {target.dir} (env {target.env}) with PlatformIO? This runs the project's own build scripts "
               "(platformio.ini, extra_scripts) with your user rights. Nothing is uploaded to a board.")
    if target.simulated:
        message += SIM_BUILD_NOTE
    return {"action": "approve", "message": message, "rule_key": build_rule_key(str(target.dir), target.env)}


def _serial(host: Any, args: Mapping[str, Any], action: str) -> dict[str, str] | None:
    from .bench_core import guard
    from .bench_core import settings as S
    port = args.get("port")
    if not isinstance(port, str) or not port.strip() or guard.is_sim(port):
        return None  # the handler answers bad ports itself; sim ports are harmless
    port = port.strip()
    with contextlib.suppress(Exception):  # a bad port is refused by check_serial below (block)
        port = guard.normalize_port(port)  # aliases (/dev/serial/by-id/...) share the device's rule_key
    what = "board detection" if action == "detect" else "the serial monitor"
    if host.cron():
        return _block(what, "scheduled jobs (cron) cannot open serial ports")
    refusal = guard.check_serial(via="tool", settings=None, port=port, cron=False,
                                 action="board.detect" if action == "detect" else "serial.monitor")
    if refusal is not None:
        return _block(what, refusal)
    if S.load().get("approve_serial") is False:
        return None
    if action == "detect":
        message = f"Detect the board on {port} with esptool? This resets the board (the running firmware restarts)."
    else:
        message = f"Open {port} for the serial monitor? Opening the port can reset the board (DTR/RTS)."
    return {"action": "approve", "message": message, "rule_key": serial_rule_key(action, port)}


def decide(host: Any, tool_name: str, args: Any) -> dict[str, str] | None:
    """The directive for one call (see the module table). Never raises."""
    if tool_name != TOOL:
        return None
    args = args if isinstance(args, Mapping) else {}
    action = args.get("action")
    if action not in ("flash", "detect", "monitor", "build"):
        return None
    try:
        if action == "flash":
            return _flash(host, args)
        if action == "build":
            return _build(host, args)
        return _serial(host, args, action)
    except Exception as e:  # noqa: BLE001 - fail closed for calls that may touch hardware or run project scripts
        logger.warning("circuit-bench: approval hook failed (%s)", type(e).__name__)
        return {"action": "block", "message": f"Circuit Bench blocked bench_board {action}: the approval check failed "
                f"({type(e).__name__}); nothing was run."}


def make_pre_tool_call(host: Any) -> Callable[..., dict[str, str] | None]:
    def on_pre_tool_call(tool_name: str = "", args: Any = None, **kwargs: Any) -> dict[str, str] | None:
        return decide(host, tool_name, args)

    return on_pre_tool_call

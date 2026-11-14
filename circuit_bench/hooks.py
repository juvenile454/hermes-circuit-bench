"""pre_tool_call hook for ``bench_board``: approval directives for builds that start PlatformIO and board access.

Decisions (``None`` = no directive):

| call                               | decision                                                             |
|------------------------------------|----------------------------------------------------------------------|
| other tools, ports                 | None                                                                 |
| every flash/build/detect/monitor   | first removes every unused grant of its task (any action, target)    |
| detect/monitor/flash on ``sim://`` | None (nothing physical; the handler still refuses cron flashes)      |
| build: PlatformIO does not start   | None (a ``sim://`` build without pio or without all packages is      |
|                                    | simulated: no project script runs)                                   |
| build: no ``platformio.ini``       | None (nothing can build there; the handler names that error)         |
| build: ``build_target`` error      | sim port: None (the handler answers); real target: block             |
| build: env is no PlatformIO name   | sim port: None (the handler answers); real target: block             |
| build: PlatformIO starts           | (a real target, or a ``sim://`` build with pio and all packages)     |
|   in cron                          | block ("scheduled jobs (cron) cannot run real builds ...")           |
|   OK                               | approve, ``rule_key = circuit-bench:build:sha256(dir|env)`` (dir     |
|                                    | resolved: a symlink or ``..`` to the same folder shares the key);    |
|                                    | a ``sim://`` port adds that the build is a real offline build;       |
|                                    | grant (dir, env, port)                                               |
| flash/detect/monitor in cron       | block                                                                |
| flash: ``guard.check_flash`` error | block (allow_flash off, hardware off, approvals bypassed, no detect/build) |
| flash without ``elf_sha256`` arg   | block ("pass elf_sha256 from the last bench_board build")             |
| flash: ``elf_sha256`` not last build | block (elf_mismatch)                                                 |
| flash: port URL without provider  | block (invalid_args, the handler's "unsupported port URL")           |
| flash: OK                          | approve, ``rule_key = circuit-bench:flash:sha256(port|mac|elf_sha256 arg)``; |
|                                    | grant (project, port) naming mac, sha, firmware folder, env and the  |
|                                    | last build's images and time (``at``)                                |
| detect/monitor: ``check_serial`` error | block (hardware off, approvals bypassed)                         |
| detect/monitor: port URL without provider | block (invalid_args, the handler's "unsupported port URL")    |
| detect/monitor, ``approve_serial`` | approve, ``rule_key = circuit-bench:detect|monitor:sha256(port)``; grant (port) |
| detect/monitor, approve_serial off | None; grant (port)                                                   |
| internal error (real port, build)  | block (fail closed); no grant of the task is left                    |

Grants: every pass for flash, build, detect or monitor first removes all unused grants of its ``task_id`` (every
action, every target). Only a call the hook lets through on a real port, or a build that starts PlatformIO, then
leaves one grant in the ``Host``, stored as the very last step right before the hook answers (approve or None). A
pass that blocks, lets a call through that needs no grant (``sim://``, a folder without ``platformio.ini``) or fails
inside leaves no grant of its task, so a task has at most one unused grant. Hermes runs the hook and then the handler
for each call, one call after another (plugin tools never run in parallel), so this never locks out a proper call.
The key is the ``task_id`` Hermes passes to hook and handler alike, the action and the target. The handler takes the
grant when it starts; without one it answers ``not_confirmed``. One grant serves exactly one handler run. Without a
``task_id`` nothing is stored or found, so a handler reached without the hook (``ctx.dispatch_tool``) finds none. A
grant lives for ``approvals.timeout`` + 60 s (120-3600 s; 360 s when the value is not a whole number). After "deny"
or a timeout Hermes does not start the handler; the grant stays unused until it expires or the next pass of the task
removes it, and a new call passes the hook and its question again. Limits: code in the same process that fakes the
arguments or calls the plugin internals directly is not stopped, and the binding holds per task, action and target,
not per single call.

Approval questions name the checked values first (env, chip, MAC, port, ELF) and the firmware folder, the one free
text, last and quoted (``Firmware folder: "<path>"`` / ``Folder: "<path>"``), so a folder name cannot read like the
rest of the question. Paths are shown through ``approval_path``: ``"`` and every quotation mark or look-alike of it
(the Unicode Quotation_Mark characters but the apostrophe U+0027, the primes), control characters, line breaks, Unicode
direction marks, space variants other than U+0020, some blank letters (U+2800 and others) and every Unicode
Default_Ignorable_Code_Point (variation selectors, zero-width characters, ...) become ``\\uXXXX``
(``bench_core.shown``; look-alike letters stay as they are). The chip shows only the esptool name the flash check
accepted and a ``(revision vX.Y)``; in the port every character but letters, digits and ``._:/-`` becomes an
escape. A path longer than 120 characters is shortened in the middle to at most 120 characters (its last part stays
whole unless it is too long itself; then start and end of that name stay), and the question then ends with
"(path shortened)". Rule keys always use the full path.

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
import re
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


APPROVAL_PATH_MAX = 120  # characters of a path in an approval text
PATH_SHORTENED = " (path shortened)"
APPROVAL_DIR_KEEP = 40  # characters of the folders in front of a last part that is shortened itself


def _visible(text: str) -> list[str]:
    """One display token per character: characters that could hide or reorder text become ``\\uXXXX``
    (``shown.approval_hidden``: controls, format characters, separators, spaces other than U+0020, blank letters and
    every Default_Ignorable_Code_Point)."""
    from .bench_core import shown
    return shown.approval_tokens(text)


def _width(tokens: list[str]) -> int:
    return sum(map(len, tokens))


def _head(tokens: list[str], budget: int) -> list[str]:
    """The first tokens of ``tokens``, together at most ``budget`` characters; an escape is never cut in half."""
    out: list[str] = []
    for t in tokens:
        if len(t) > budget:
            break
        out.append(t)
        budget -= len(t)
    return out


def _middle_cut(tokens: list[str], budget: int) -> list[str]:
    """Start and end of ``tokens`` with ``…`` between them, together at most ``budget`` characters plus the ``…``;
    the start gets the larger half. An escape is never cut in half."""
    head = _head(tokens, budget - budget // 2)
    tail = _head(tokens[len(head):][::-1], budget - _width(head))[::-1]
    return [*head, "…", *tail]


def approval_path(path: Any) -> tuple[str, bool]:
    """``(text, changed)``: a path for an approval question, never longer than ``APPROVAL_PATH_MAX`` characters.
    Hidden characters, ``"`` (the question quotes the path) and every other quotation mark or look-alike of ``"``
    (``shown.FIELD_QUOTES``: the Unicode Quotation_Mark characters but the apostrophe U+0027, and the primes) are shown
    as ``\\uXXXX``. A longer text is shortened
    in the middle (``…``) and keeps its last part whole; a last part that is too long itself is shortened in the
    middle as well, so start and end of its name stay visible (the folders in front of it then keep at most
    ``APPROVAL_DIR_KEEP`` characters). An escape is never cut in half. ``changed`` is true when anything was replaced
    or shortened (the question then ends with ``(path shortened)``). Rule keys use the full path, never this text."""
    from .bench_core import shown
    raw = str(path)
    # one token per character of raw; '"' and everything that looks like it would end the quoted field
    tokens = shown.approval_tokens(raw, extra=shown.FIELD_QUOTES)
    changed = any(len(t) > 1 for t in tokens)
    if _width(tokens) <= APPROVAL_PATH_MAX:
        return "".join(tokens), changed
    cut = max(raw.rstrip("/").rfind("/"), 0)  # the separator in front of the last part (0: one part only)
    dirs, tail = tokens[:cut], tokens[cut:]  # tail: "/last" (the separator included)
    if dirs and _width(tail) < APPROVAL_PATH_MAX:  # the last part fits whole: only the folders are shortened
        return "".join([*_head(dirs, APPROVAL_PATH_MAX - 1 - _width(tail)), "…", *tail]), True
    prefix = dirs if _width(dirs) <= APPROVAL_DIR_KEEP else [*_head(dirs, APPROVAL_DIR_KEEP - 1), "…"]
    return "".join([*prefix, *_middle_cut(tail, APPROVAL_PATH_MAX - 1 - _width(prefix))]), True


def _shown(value: Any) -> str:
    """A short value of an approval question (env, chip, MAC, port) with hidden characters shown as ``\\uXXXX``."""
    return "".join(_visible(str(value)))


_PORT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/-")
_STRICT_REVISION = re.compile(r"\(revision v\d{1,3}\.\d{1,3}\)")


def _port_shown(port: Any) -> str:
    """The port of a flash, detect or monitor question. Serial device names use letters, digits and ``._:/-``
    (/dev/ttyACM0, /dev/cu.usbmodem1101, COM3); every other character is shown as ``\\uXXXX``, so a device name cannot
    read like more of the question."""
    from .bench_core import shown
    return "".join(ch if ch in _PORT_CHARS else shown.escape(ch) for ch in str(port))


def _chip_shown(chip: Any) -> str:
    """The detected chip of a flash question: the esptool chip description the flash check accepted (a fixed name
    such as ``ESP32-S3 (QFN56)``), its revision only in the form ``(revision vX.Y)`` and the Secure Download Mode
    suffix. Any other text after the name (a hand-edited project file) is left out."""
    from .bench_core import board
    if not isinstance(chip, str) or not chip.strip():
        return "the board"
    name = chip.strip()
    sdm = name.endswith(board._SDM_SUFFIX)
    if sdm:
        name = name[:-len(board._SDM_SUFFIX)].strip()
    rev = board._REVISION_RE.search(name)
    base = name[:rev.start()].strip() if rev else name
    revision = rev.group(0).strip() if rev else ""
    text = base + (f" {revision}" if _STRICT_REVISION.fullmatch(revision) else "") + (board._SDM_SUFFIX if sdm else "")
    return _shown(text)


def _url_port_refusal(port: str, action: str) -> dict[str, Any] | None:
    """The handler's refusal of a port URL without a provider (``rfc2217://``, ``socket://``, any text with ``://``
    that is no ``sim://`` port), or None. Same check as the handlers (``board._check_real_port``; the serial monitor
    refuses such a port with the same words), asked before the question so the user never sees one."""
    from .bench_core import board
    from .bench_core.contracts import BenchError, fail
    try:
        if board.provider_for(port) is None:
            board._check_real_port(port)
    except BenchError as e:
        return fail(action, e.code, e.message[:200], e.hint)
    return None


def _block(what: str, env_or_text: Mapping[str, Any] | str) -> dict[str, str]:
    """A block directive; its message goes to the model, so hidden characters are shown as ``\\uXXXX``
    (``shown.for_model``)."""
    from .bench_core import shown
    if isinstance(env_or_text, str):
        text = env_or_text
    else:
        err = env_or_text.get("error") or {}
        text = f"{err.get('message') or env_or_text.get('summary') or 'refused'} ({err.get('code', 'refused')})"
        if err.get("hint"):
            text += f"; {err['hint']}"
    return {"action": "block", "message": shown.for_model(f"Circuit Bench blocked {what}: {text}.")}


def _flash(host: Any, args: Mapping[str, Any], task_id: Any) -> dict[str, str] | None:
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
    if (refusal := _url_port_refusal(port, "board.flash")) is not None:
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
    build = fw.get("last_build") or {}
    sha = str(build.get("elf_sha256") or "").lower()
    mac = str(det.get("mac") or "").lower()
    if not sha.startswith(given):
        return _block("the flash", f"elf_sha256 {given[:16]}… is not the last build ({sha[:12]}…) (elf_mismatch); "
                      f"run bench_board build with project {proj['id']} again, then flash with its elf_sha256")
    folder, changed = approval_path(fw.get("dir"))
    # the fixed wording with the checked values first; the folder (free text) is the last field, quoted
    message = (f"Flash firmware {_shown(fw.get('env'))} to {_chip_shown(det.get('chip'))} (MAC {_shown(mac)}) on "
               f"{_port_shown(port)}? ELF {given} (exactly the last build, not rebuilt; Circuit Bench adds no erase; "
               f'project scripts (extra_scripts) still run). Firmware folder: "{folder}"')
    if changed:
        message += PATH_SHORTENED
    directive = {"action": "approve", "message": message, "rule_key": flash_rule_key(port, mac, given)}
    # the last step before the answer: the handler of this task flashes only exactly this, once
    host.grant(task_id, "flash", tools.flash_grant_target(proj["id"], port), port=port, mac=mac, elf_sha256=sha,
               dir=fw.get("dir"), env=fw.get("env"), images=build.get("images"), at=build.get("at"))
    return directive


SIM_BUILD_NOTE = " The board is simulated; the build is a real offline build."


def _build(host: Any, args: Mapping[str, Any], task_id: Any) -> dict[str, str] | None:
    from . import tools
    from .bench_core import board, guard
    from .bench_core.contracts import BenchError, fail
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
    try:
        board._check_env(target.env)  # with project_dir, env is the model's own text: never put it to the user as is
    except BenchError as e:  # the handler refuses it too, before PlatformIO starts
        return None if sim_port else _block("the build", fail("board.build", e.code, e.message[:200], e.hint))
    if host.cron():
        return _block("the build", tools.BUILD_CRON_MSG)
    folder, changed = approval_path(target.dir)
    # the fixed wording with the checked values first; the folder (free text) is the last field, quoted
    message = (f"Build env {_shown(target.env)} with PlatformIO? This runs the project's own build scripts "
               "(platformio.ini, extra_scripts) with your user rights. Nothing is uploaded to a board.")
    if target.simulated:
        message += SIM_BUILD_NOTE
    message += f' Folder: "{folder}"'
    if changed:
        message += PATH_SHORTENED
    directive = {"action": "approve", "message": message, "rule_key": build_rule_key(str(target.dir), target.env)}
    host.grant(task_id, "build", tools.Host.build_grant_target(target))  # the last step: one handler run
    return directive


def _serial(host: Any, args: Mapping[str, Any], action: str, task_id: Any) -> dict[str, str] | None:
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
    if (refusal := _url_port_refusal(port, "board.detect" if action == "detect" else "serial.monitor")) is not None:
        return _block(what, refusal)
    directive: dict[str, str] | None = None
    if S.load().get("approve_serial") is not False:
        if action == "detect":
            message = (f"Detect the board on {_port_shown(port)} with esptool? This resets the board (the running "
                       "firmware restarts).")
        else:
            message = f"Open {_port_shown(port)} for the serial monitor? Opening the port can reset the board (DTR/RTS)."
        directive = {"action": "approve", "message": message, "rule_key": serial_rule_key(action, port)}
    host.grant(task_id, action, port)  # the last step, also when nothing is asked: one handler run
    return directive


def decide(host: Any, tool_name: str, args: Any, task_id: Any = "") -> dict[str, str] | None:
    """The directive for one call (see the module table). Never raises. Every pass for flash, build, detect or monitor
    first removes the unused grants of task ``task_id``; a call it lets through (approve or None) on a real port, or a
    build that starts PlatformIO, then leaves one grant for the handler of that task as its last step."""
    if tool_name != TOOL:
        return None
    args = args if isinstance(args, Mapping) else {}
    action = args.get("action")
    if action not in ("flash", "detect", "monitor", "build"):
        return None
    try:
        host.clear(task_id)  # nothing left from an earlier pass of this task, whatever this pass answers
        if action == "flash":
            return _flash(host, args, task_id)
        if action == "build":
            return _build(host, args, task_id)
        return _serial(host, args, action, task_id)
    except Exception as e:  # noqa: BLE001 - fail closed for calls that may touch hardware or run project scripts
        logger.warning("circuit-bench: approval hook failed (%s)", type(e).__name__)
        with contextlib.suppress(Exception):
            host.clear(task_id)  # the grant is stored last, so none is there; this only makes sure
        return {"action": "block", "message": f"Circuit Bench blocked bench_board {action}: the approval check failed "
                f"({type(e).__name__}); nothing was run."}


def make_pre_tool_call(host: Any) -> Callable[..., dict[str, str] | None]:
    def on_pre_tool_call(tool_name: str = "", args: Any = None, **kwargs: Any) -> dict[str, str] | None:
        return decide(host, tool_name, args, kwargs.get("task_id"))

    return on_pre_tool_call

"""Tool handlers on top of bench_core.

- Handlers are ``h(args, **kw) -> str`` (JSON result envelope) and never raise: every handler runs inside
  ``_guarded`` (non-object arguments -> ``invalid_args``, unexpected exceptions -> ``tool_failed`` naming only the
  exception type).
- Answers stay below ``MAX_BYTES`` (``fit``); project answers are compact views (rev, changed, affected
  assignments), the full project stays in its file.
- Writes go only through ``project.update`` (which emits ``project.updated``).
- Real boards: ``bench_board flash/detect/monitor`` check the approval rules themselves (``guard``), independent of
  the ``pre_tool_call`` hook, and refuse real ports while the hook is not registered (``Host.hook_active``).
- bench_core modules are imported inside the handlers (light plugin load; schemdraw/pyserial stay lazy).
- Calculators and modules come from their registers: ``CALC_KINDS`` is the live
  ``calckit.kinds()``; ``bench_pins modules/module`` read ``modules.catalog()``.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from .bench_core.contracts import MAX_RESULT_BYTES, WARNING_SEVERITIES, BenchError, envelope, fail, from_error, warning
from .bench_core.modspec import MODULE_OPS

logger = logging.getLogger(__name__)

MAX_BYTES = MAX_RESULT_BYTES
# result keys fit() keeps even in its last stage: the model needs them for the next call
FIT_KEEP_KEYS = ("ok", "rev", "port", "mac", "elf_sha256", "log_ref", "svg_path", "calc_id", "job_id")
TRUTHY = frozenset({"1", "true", "yes", "on"})
MONITOR_DEFAULT_S = 10.0
LOG_MAX_CHARS = 200_000
DEFAULT_ACTION = {"bench_project": "project.get", "bench_pins": "pins.check", "bench_calc": "calc.led",
                  "bench_schematic": "schematic.render", "bench_solder": "solder.plan", "bench_board": "board.ports",
                  "bench_crash": "crash.decode"}
PROJECT_ACTIONS = ("create", "get", "list", "set_board", "assign", "unassign", "set_firmware", "add_parts",
                   "remove_parts", "note", *MODULE_OPS, "demo")
PINS_ACTIONS = ("check", "suggest", "info", "modules", "module")
BOARD_ACTIONS = ("ports", "detect", "build", "flash", "monitor")
CALC_LIST = "list"  # bench_calc action=list: every calculator with its inputs (calckit.meta)
# module catalog answers (bench_pins modules/module)
MODULES_LIMIT_DEFAULT = 20
MODULES_LIMIT_MAX = 100
MODULE_Q_MAX = 64
MODULE_VIEW_KEYS = ("id", "title", "category", "manufacturer", "kind", "aliases", "pins", "interfaces", "supplies",
                    "io", "current", "requires", "hazards", "notes")
HAZARD_DANGER = frozenset({"mains", "laser", "li_ion"})  # the rest of modspec hazard codes -> caution
F_TOOL_KEYS = ("value", "unit", "rel", "rel_offset", "of", "conditions", "source_id")  # evidence/page stay in the data
CONN_VIEW_MAX = 12  # project_view: at most this many conn entries per part
ADDED_VIEW_MAX = 12  # add_parts answer: at most this many added parts listed (result.added)
NO_HOOK_MSG = "the Circuit Bench approval hook is not active, so the agent cannot use real boards"
NO_HOOK_HINT = "reload the plugin (it registers the hook) or use the Bench UI; sim:// ports still work"
FLASH_APPROVAL_TTL_S = 3600.0  # an approval card may stay open for a while; older hook entries are void
SHA_ARG_RE = re.compile(r"^[0-9a-f]{12,64}$")
SHA_ARG_HINT = "pass elf_sha256 from the last bench_board build (the full hash or its first 12+ hex digits)"


def __getattr__(name: str) -> Any:
    """``CALC_KINDS``: the calculator kinds in register order (calckit), read live so new calculators need no edit."""
    if name == "CALC_KINDS":
        from .bench_core import calckit
        return calckit.kinds()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class Host:
    """What a handler needs from Hermes: cron detection, whether the approval hook is registered, and the flashes
    the hook put to the user (the handler flashes only the exact project, port, MAC and ELF the user saw)."""

    def __init__(self, cron: Callable[[], bool] | None = None, hook_active: bool = False):
        self._cron = cron
        self.hook_active = hook_active
        self._flash_lock = threading.Lock()
        self._flash_approvals: dict[tuple[str, str], dict[str, Any]] = {}

    def remember_flash(self, project: str, port: str, mac: str, elf_sha256: str) -> None:
        """The pre_tool_call hook stores what its approval question names (one entry per project and port)."""
        with self._flash_lock:
            now = time.monotonic()
            for key in [k for k, v in self._flash_approvals.items() if now - v["at"] > FLASH_APPROVAL_TTL_S]:
                del self._flash_approvals[key]
            self._flash_approvals[(project, port)] = {"project": project, "port": port, "mac": mac,
                                                      "elf_sha256": elf_sha256, "at": now}

    def take_flash(self, project: str, port: str) -> dict[str, Any] | None:
        """The entry the hook stored for this flash, removed (one approval, one flash); None if none or expired."""
        with self._flash_lock:
            entry = self._flash_approvals.pop((project, port), None)
        if entry is None or time.monotonic() - entry["at"] > FLASH_APPROVAL_TTL_S:
            return None
        return entry

    def cron(self) -> bool:
        """True inside a scheduled job. Fails closed: a failing probe counts as cron."""
        if os.environ.get("HERMES_CRON_SESSION", "").strip().lower() in TRUTHY:
            return True
        if self._cron is None:
            return False
        try:
            return bool(self._cron())
        except Exception:  # noqa: BLE001 - unknown state refuses unattended actions
            return True


class _Return(Exception):
    def __init__(self, env: dict[str, Any]):
        super().__init__(env.get("summary", ""))
        self.env = env


# --------------------------------------------------------------------------------------------- output

def _dump(env: Any) -> str:
    return json.dumps(env, ensure_ascii=False, default=str)


def _size(env: Any) -> int:
    return len(_dump(env).encode("utf-8"))


def _shrink(obj: Any, max_list: int, max_str: int) -> Any:
    if isinstance(obj, str):
        return obj if len(obj) <= max_str else obj[:max_str] + "…"
    if isinstance(obj, list):
        return [_shrink(x, max_list, max_str) for x in obj[:max_list]]
    if isinstance(obj, dict):
        return {k: _shrink(v, max_list, max_str) for k, v in obj.items()}
    return obj


def _slim_sources(items: list[Any], n: int) -> list[Any]:
    out = []
    for s in items[:n]:
        out.append({k: s[k] for k in ("id", "title", "url", "retrieved") if k in s} if isinstance(s, dict) else s)
    return out


def _drop_source_notes(items: list[Any]) -> list[Any]:
    return [{k: v for k, v in s.items() if k != "note"} if isinstance(s, dict) else s for s in items]


def _cut_warnings(items: list[Any], max_list: int, max_str: int, keep: int = 600) -> list[Any]:
    """danger and caution warnings all stay, complete (a message is cut only beyond ``keep`` chars); info warnings
    are cut like the other lists (at most ``max_list`` of them, texts to ``max_str``). Order unchanged."""
    out, infos = [], 0
    for w in items:
        if isinstance(w, dict) and w.get("severity") in ("danger", "caution"):
            msg = w.get("message")
            out.append({**w, "message": _shrink(msg, 1, keep)} if isinstance(msg, str) else w)
        elif infos < max_list:
            out.append(_shrink(w, max_list, max_str))
            infos += 1
    return out


def fit(env: dict[str, Any], limit: int = MAX_BYTES) -> dict[str, Any]:
    """``env`` itself if its JSON fits ``limit`` bytes. Else first without the source notes (nothing else changes);
    if that still does not fit, a shortened copy (lists and texts cut, marked with ``result.truncated`` and the
    warning ``result_truncated``). danger and caution warnings are never dropped. The envelope shape stays valid."""
    if not isinstance(env, dict) or _size(env) <= limit:
        return env
    srcs = env.get("sources")
    if isinstance(srcs, list) and any(isinstance(x, dict) and "note" in x for x in srcs):
        out = {**env, "sources": _drop_source_notes(srcs)}
        if _size(out) <= limit:
            return out
    note = warning("result_truncated", "info", "answer shortened to stay below 8 kB; the full data is in the "
                   "project file or the log artifact (log_ref)")
    for max_list, max_str in ((40, 600), (20, 300), (8, 160), (3, 80)):
        out = dict(env)
        out["result"] = _shrink(env.get("result"), max_list, max_str)
        if isinstance(out["result"], dict):
            out["result"]["truncated"] = True
        for key in ("checks", "assumptions"):
            out[key] = _shrink(list(env.get(key) or []), max_list, max_str)
        out["warnings"] = [*_cut_warnings(list(env.get("warnings") or []), max_list, max_str), note]
        out["sources"] = _slim_sources(list(env.get("sources") or []), max_list)
        if _size(out) <= limit:
            return out
    out = dict(env)
    out["summary"] = _shrink(env.get("summary") or "", 1, 300)
    res = env.get("result") if isinstance(env.get("result"), dict) else {}
    # the keys a follow-up call needs survive the last stage (scalars only, texts cut like the summary)
    out["result"] = {**{k: _shrink(res[k], 1, 300) for k in FIT_KEEP_KEYS
                        if k in res and (res[k] is None or isinstance(res[k], str | int | float | bool))},
                     "truncated": True}
    for key in ("checks", "assumptions"):
        out[key] = _shrink(list(env.get(key) or []), 5, 120)
    out["warnings"] = [*_cut_warnings(list(env.get("warnings") or []), 5, 120), note]
    out["sources"] = _slim_sources(list(env.get("sources") or []), 5)
    if isinstance(out.get("error"), dict):
        out["error"] = _shrink(out["error"], 1, 300)
    return out


# --------------------------------------------------------------------------------------------- arguments

def _bad(action: str, message: str, hint: str | None = None) -> _Return:
    return _Return(fail(action, "invalid_args", message, hint))


def _act(args: Mapping[str, Any], allowed: tuple[str, ...], tool: str) -> str:
    value = args.get("action")
    if value not in allowed:
        raise _bad(DEFAULT_ACTION[tool], f"unknown action {str(value)[:30]!r} for {tool}", f"actions: {', '.join(allowed)}")
    return value


def _str(args: Mapping[str, Any], key: str, action: str, *, required: bool = False) -> str | None:
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _bad(action, f"{key} is required")
        return None
    if not isinstance(value, str):
        raise _bad(action, f"{key} must be text, not {type(value).__name__}")
    return value.strip()


def _req(args: Mapping[str, Any], key: str, action: str, hint: str | None = None) -> str:
    value = _str(args, key, action)
    if value is None:
        raise _bad(action, f"{key} is required", hint)
    return value


def _bool(args: Mapping[str, Any], key: str, action: str, default: bool | None = None) -> bool | None:
    value = args.get(key, default)
    if value is None or isinstance(value, bool):
        return value
    raise _bad(action, f"{key} must be true or false")


def _int(args: Mapping[str, Any], key: str, action: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(action, f"{key} must be a whole number")
    return value


def _num(args: Mapping[str, Any], key: str, action: str, default: float) -> float:
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _bad(action, f"{key} must be a number")
    return float(value)


def _dicts(args: Mapping[str, Any], key: str, action: str) -> list[dict[str, Any]] | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise _bad(action, f"{key} must be a list of objects")
    return value


# --------------------------------------------------------------------------------------------- projects

def _get_project(pid: str) -> dict[str, Any]:
    from .bench_core import project as P
    env = P.get(pid)
    if not env["ok"]:
        raise _Return(env)
    return env["result"]["project"]


def _apply(pid: str, ops: list[dict[str, Any]], rev: int | None = None, *, trusted: bool = False) -> dict[str, Any]:
    """project.update by the agent. Without ``rev`` the current one is used (one retry after a conflict: the
    agent's ops are absolute, a concurrent UI change does not change their meaning). ``trusted``: the ops carry a
    result this handler produced itself (set_detected/set_build/set_flash/set_debug), never the model's arguments."""
    from .bench_core import project as P
    if rev is not None:
        return P.update(pid, rev, ops, by="agent", trusted=trusted)
    upd: dict[str, Any] = {}
    for _ in range(2):
        cur = P.get(pid)
        if not cur["ok"]:
            return cur
        upd = P.update(pid, cur["result"]["rev"], ops, by="agent", trusted=trusted)
        if upd["ok"] or (upd.get("error") or {}).get("code") != "project_conflict":
            return upd
    return upd


def _assignment_view(a: Mapping[str, Any]) -> dict[str, Any]:
    return {k: a.get(k) for k in ("role", "mode", "pin", "net", "verdict", "rule_ids")}


def _conn_view(conn: Any) -> Any:
    """conn of a part, at most CONN_VIEW_MAX pins (``"…": n`` counts the rest)."""
    if not isinstance(conn, Mapping) or len(conn) <= CONN_VIEW_MAX:
        return conn
    items = list(conn.items())
    return {**dict(items[:CONN_VIEW_MAX]), "…": len(items) - CONN_VIEW_MAX}


def _part_view(x: Mapping[str, Any]) -> dict[str, Any]:
    """ref, kind, value; module parts also module, variant, address, conn (shortened) and facts (only when set),
    qty when above 1."""
    out = {k: x.get(k) for k in ("ref", "kind", "value")}
    if isinstance(x.get("qty"), int) and x["qty"] > 1:
        out["qty"] = x["qty"]
    for key in ("module", "variant", "address", "conn", "facts"):
        if x.get(key) not in (None, {}, ""):
            out[key] = _conn_view(x[key]) if key == "conn" else x[key]
    return out


def project_view(p: Mapping[str, Any]) -> dict[str, Any]:
    """Compact project for the model: everything it needs to continue, without SVGs, step texts or full calcs."""
    b = p.get("board") or {}
    det = b.get("detected")
    fw = p.get("firmware") or {}
    solder = p.get("solder") or {}
    steps, done = solder.get("steps") or [], set(solder.get("done") or [])
    nxt = next((s for s in steps if s.get("id") not in done), None)
    return {
        "id": p.get("id"), "title": p.get("title"), "rev": p.get("rev"), "simulated": p.get("simulated"),
        "board": {"chip": b.get("chip"), "module": b.get("module"), "variant": b.get("variant"),
                  "devkit": b.get("devkit"),
                  "detected": {k: det.get(k) for k in ("port", "mac", "chip", "flash_size", "at", "simulated")}
                  if isinstance(det, dict) else None},
        "options": p.get("options"),
        "assignments": [_assignment_view(a) for a in p.get("assignments") or []],
        "parts": [_part_view(x) for x in p.get("parts") or []],
        "calcs": [c.get("id") for c in p.get("calcs") or []],
        "circuits": [{k: c.get(k) for k in ("id", "block", "svg")} for c in p.get("circuits") or []],
        "solder": {"steps": len(steps), "done": len(done & {s.get("id") for s in steps}),
                   "next": {k: nxt.get(k) for k in ("id", "n", "refs", "kind")} if nxt else None},
        "firmware": {"dir": fw.get("dir"), "env": fw.get("env"), "last_build": fw.get("last_build"),
                     "last_flash": fw.get("last_flash")},
        "last_panic": (p.get("debug") or {}).get("last_panic"),
        "notes": len(p.get("notes") or []),
    }


def _with_project_view(env: dict[str, Any]) -> dict[str, Any]:
    res = env.get("result")
    if env.get("ok") and isinstance(res, dict) and isinstance(res.get("project"), dict):
        env = dict(env)
        env["result"] = {**{k: v for k, v in res.items() if k != "project"}, "project": project_view(res["project"])}
    return env


def with_board_warnings(env: dict[str, Any], devkit: Any) -> dict[str, Any]:
    """The DevKit's board-level hazards (e.g. the WT32 supply) as envelope warnings in
    front, each code once (bench_core may already have added them), with their sources. Only for ok answers."""
    if not env.get("ok") or not isinstance(devkit, str) or not devkit:
        return env
    from .bench_core import boards, sources
    try:
        items = boards.warnings_of(devkit)
    except BenchError:
        return env
    have = {w.get("code") for w in env.get("warnings") or []}
    add = [warning(w["id"], w["severity"], w["message"], [w["source_id"]] if w.get("source_id") else [])
           for w in items if w.get("id") not in have and w.get("severity") in WARNING_SEVERITIES and w.get("message")]
    if not add:
        return env
    srcs = list(env.get("sources") or [])
    known = {s.get("id") for s in srcs if isinstance(s, dict)}
    for sid in dict.fromkeys(i for w in add for i in w["source_ids"] if i not in known):
        try:
            srcs += sources.resolve([sid])
        except BenchError:
            logger.debug("circuit-bench: board warning source %s unknown", sid)
    return {**env, "warnings": [*add, *(env.get("warnings") or [])], "sources": srcs}


def _devkit_of(env: Mapping[str, Any]) -> Any:
    res = env.get("result") if isinstance(env.get("result"), dict) else {}
    proj = res.get("project") if isinstance(res.get("project"), dict) else res
    board = proj.get("board") if isinstance(proj.get("board"), dict) else {}
    return board.get("devkit")


def _update_view(upd: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """project.update answer cut down to rev, changed and what the ops touched."""
    res = upd.get("result")
    if not upd.get("ok") or not isinstance(res, dict) or not isinstance(res.get("project"), dict):
        return upd
    p = res["project"]
    names = {op.get("op") for op in ops}
    roles = {op.get("role") for op in ops if op.get("op") == "assign"}
    view: dict[str, Any] = {"id": p["id"], "rev": res["rev"], "changed": res.get("changed", [])}
    if "set_board" in names:
        view["board"] = project_view(p)["board"]
        view["options"] = p.get("options")
        roles = {a["role"] for a in p.get("assignments") or []}
    if roles:
        view["assignments"] = [_assignment_view(a) for a in p.get("assignments") or [] if a["role"] in roles]
    if "unassign" in names:
        view["removed"] = [op.get("role") for op in ops if op.get("op") == "unassign"]
        view["remaining_roles"] = [a["role"] for a in p.get("assignments") or []]
    if "set_firmware" in names:
        view["firmware"] = {"dir": p["firmware"]["dir"], "env": p["firmware"]["env"]}
    if "add_parts" in names or "remove_parts" in names:
        view["parts"] = len(p.get("parts") or [])
    if "add_parts" in names:
        added = {str(x.get("ref")).strip().upper() for op in ops if op.get("op") == "add_parts"
                 for x in op.get("parts") or [] if isinstance(x, Mapping)}
        view["added"] = [_part_view(x) for x in p.get("parts") or [] if x.get("ref") in added][:ADDED_VIEW_MAX]
    if "remove_parts" in names:
        view["removed_parts"] = [str(r).strip().upper() for op in ops if op.get("op") == "remove_parts" for r in op["refs"]]
    if "note" in names:
        view["notes"] = len(p.get("notes") or [])
    if names & {"add_module", "connect"}:
        touched = {str(op.get("ref")).strip().upper() for op in ops if op.get("ref")}
        mods = [x for x in p.get("parts") or [] if x.get("module") or x.get("ref") in touched]
        view["parts"] = len(p.get("parts") or [])
        view["modules"] = [_part_view(x) for x in mods]
    if "set_rails" in names:
        view["options"] = p.get("options")
    out = dict(upd)
    out["result"] = view
    return out


_OP_PREFIX = re.compile(r"^ops\[(\d+)\] \(([a-z_]+)\): ")


def _tool_error(upd: dict[str, Any], ops: list[dict[str, Any]], offset: int = 0) -> dict[str, Any]:
    """project.update errors name ``ops[i] (op): …``; the tool caller sent no ops array, so name its own argument
    (``assignments[i]`` when it gave several assignments) or nothing. ``offset``: ops the handler put in front."""
    err = upd.get("error")
    if upd.get("ok") or not isinstance(err, dict) or not isinstance(err.get("message"), str):
        return upd
    m = _OP_PREFIX.match(err["message"])
    if m is None:
        return upd
    rest = err["message"][m.end():]
    i, name = int(m.group(1)) - offset, m.group(2)
    field = rest.startswith(f"{name}.")
    if field:  # "add_parts.parts[0].kind: …" -> "parts[0].kind: …" (the tool argument)
        rest = rest[len(name) + 1:]
    if name in ("assign", "unassign") and sum(op.get("op") == name for op in ops) > 1 and i >= 0:
        rest = f"assignments[{i}].{rest}" if field else f"assignments[{i}]: {rest}"
    return {**upd, "error": {**err, "message": rest}}


def _pin_checks(env: dict[str, Any], upd: dict[str, Any]) -> dict[str, Any]:
    """The pin checks of all the project's assignments (like bench_pins check with the project), added to an ok
    assign/create answer, plus ``all_roles``."""
    from .bench_core import pins
    res = upd.get("result") if upd.get("ok") else None
    proj = res.get("project") if isinstance(res, dict) else None
    if not env.get("ok") or not isinstance(proj, dict) or not proj.get("assignments"):
        return env
    b = proj.get("board") or {}
    items = [{k: a.get(k) for k in ("role", "mode", "pin", "net")} for a in proj["assignments"]]
    chk = pins.check(b.get("chip"), items, variant=b.get("variant"),
                     wifi=bool((proj.get("options") or {}).get("wifi", True)), devkit=b.get("devkit"),
                     parts=proj.get("parts") or [], options=proj.get("options") or {})
    if not chk.get("ok"):
        return env
    out = dict(env)
    out["checks"] = [*env.get("checks", []), *chk["checks"]]
    if isinstance(out.get("result"), dict):
        out["result"] = {**out["result"], "all_roles": [a["role"] for a in proj["assignments"]]}
    return _module_warnings(out, chk)


def _cited(items: Any) -> set[str]:
    return {str(i) for x in items or [] if isinstance(x, dict) for i in x.get("source_ids") or []}


def _with_sources(env: dict[str, Any], chk: dict[str, Any], *, notes: bool = True) -> dict[str, Any]:
    """``env`` plus the sources pins.check resolved (``chk``) that belong to what ``env`` carries: every source an
    included check or warning cites, and the pin-rule sources (no module item cites them); a source only a dropped
    module warning cites stays out. ``notes`` False: id, title, url, retrieved only (like pins._merge_modules when
    it compacts)."""
    shown = _cited(env.get("checks")) | _cited(env.get("warnings"))
    dropped = (_cited(chk.get("checks")) | _cited(chk.get("warnings"))) - shown
    srcs = [s for s in env.get("sources") or [] if isinstance(s, dict)]
    have = {s.get("id") for s in srcs}
    for s in chk.get("sources") or []:
        if isinstance(s, dict) and s.get("id") not in have and (s.get("id") in shown or s.get("id") not in dropped):
            srcs.append(s)
            have.add(s.get("id"))
    if not notes:
        srcs = [{k: v for k, v in s.items() if k != "note"} for s in srcs]
    return {**env, "sources": srcs}


def _module_warnings(out: dict[str, Any], chk: dict[str, Any]) -> dict[str, Any]:
    """The module warnings of ``chk`` (pins.check with the project's parts) go with the project answer, so a check
    "see warning mod_…" has its warning in the same answer; ``result.module_counts`` = the engine tally; the sources
    of what is shown come along (``_with_sources``). Stays below MAX_BYTES: first the source notes go, then warnings
    that do not fit are dropped from the end (lowest severity first, never a danger) and named in
    ``module_counts.hidden``."""
    mods = (chk.get("result") or {}).get("modules")
    if not isinstance(mods, dict):
        env = _with_sources(out, chk)
        return env if _size(env) <= MAX_BYTES else _with_sources(out, chk, notes=False)
    have = {(w.get("code"), w.get("message")) for w in out.get("warnings") or []}
    new = [w for w in chk.get("warnings") or [] if isinstance(w, dict)
           and (str(w.get("code", "")).startswith("mod_") or w.get("code") == "rule_data_missing")
           and (w.get("code"), w.get("message")) not in have]
    counts = dict(mods.get("counts") or {})
    hidden = list(counts.get("hidden") or [])
    shown = counts.get("shown", len(new))
    rank = {"danger": 0, "caution": 1, "info": 2}
    notes = True

    def build() -> dict[str, Any]:
        res = out.get("result")
        c = {**counts, "shown": shown, **({"hidden": hidden[:8]} if hidden else {})}
        return _with_sources({**out, "warnings": [*(out.get("warnings") or []), *new],
                              "result": {**res, "module_counts": c} if isinstance(res, dict) else res}, chk,
                             notes=notes)

    env = build()
    if _size(env) > MAX_BYTES:
        notes = False
        env = build()
    while _size(env) > MAX_BYTES:
        drop = [i for i, w in enumerate(new) if w.get("severity") != "danger"]
        if not drop:
            break
        i = max(drop, key=lambda j: (rank.get(str(new[j].get("severity")), 3), j))
        w, shown = new.pop(i), shown - 1
        hidden.insert(0, f"{w.get('code')} {','.join(w.get('refs') or [])}".strip())
        env = build()
    return env


def _attach_update(env: dict[str, Any], pid: str, upd: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Record the outcome of the follow-up project write in ``env`` (never turns ``env`` into an error)."""
    env = dict(env)
    if upd.get("ok"):
        res = upd["result"]
        info = {"id": pid, "rev": res.get("rev"), "changed": res.get("changed", []), **extra}
        if isinstance(env.get("result"), dict):
            env["result"] = {**env["result"], "project_update": info}
        if res.get("changed"):
            env["summary"] = f"{env['summary']} Saved to project {pid} (rev {res.get('rev')})."
        env["warnings"] = [*env.get("warnings", []), *upd.get("warnings", [])]
    else:
        err = upd.get("error") or {}
        env["warnings"] = [*env.get("warnings", []), warning(
            "project_not_updated", "caution", f"project {pid} was not updated: {err.get('message', 'unknown error')}")]
    return env


# --------------------------------------------------------------------------------------------- bench_project

def _assign_ops(args: Mapping[str, Any], action: str, *, required: bool) -> list[dict[str, Any]]:
    items = _dicts(args, "assignments", action)
    if items is None and all(args.get(k) is not None for k in ("role", "mode", "pin")):
        items = [{k: args[k] for k in ("role", "mode", "pin", "net") if args.get(k) is not None}]
    if not items:
        if required:
            raise _bad(action, "assign needs assignments: [{role, mode, pin, net?}]")
        return []
    return [{"op": "assign", **item} for item in items]


def _project_ops(act: str, args: Mapping[str, Any]) -> list[dict[str, Any]]:
    action = "project.update"
    if act == "set_board":
        op: dict[str, Any] = {"op": "set_board"}
        for key in ("chip", "variant", "devkit"):
            if key in args:
                op[key] = _str(args, key, action)
        if "wifi" in args:
            op["wifi"] = _bool(args, "wifi", action)
        if len(op) == 1:
            raise _bad(action, "set_board needs chip, variant, devkit or wifi")
        return [op]
    if act == "assign":
        return _assign_ops(args, action, required=True)
    if act == "unassign":
        role = _str(args, "role", action)
        roles = [role] if role else [a.get("role") for a in _dicts(args, "assignments", action) or []]
        if not roles:
            raise _bad(action, "unassign needs role")
        return [{"op": "unassign", "role": r} for r in roles]
    if act == "set_firmware":
        return [{"op": "set_firmware", "dir": _req(args, "firmware_dir", action),
                 "env": _req(args, "env", action, ENV_HINT)}]
    if act == "add_parts":
        parts = _dicts(args, "parts", action)
        if not parts:
            raise _bad(action, "add_parts needs parts: [{ref, kind, value, package?, qty?, conn?}]",
                       "conn {pin: net}: resistor/capacitor \"1\"/\"2\", electrolytic/battery \"+\"/\"-\", "
                       "diode \"A\"/\"K\"; or connect ref later")
        return [{"op": "add_parts", "parts": parts}]
    if act in MODULE_OPS:
        return [_module_op(act, args, action)]
    if act == "remove_parts":
        refs = args.get("refs")
        if refs is None and args.get("parts") is not None:
            refs = [x.get("ref") for x in _dicts(args, "parts", action) or []]
        if isinstance(refs, str):
            refs = [refs]
        if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
            raise _bad(action, "remove_parts needs refs: [\"R1\", ...]")
        return [{"op": "remove_parts", "refs": refs}]
    return [{"op": "note", "text": _req(args, "text", action)}]


def _map_arg(args: Mapping[str, Any], key: str, action: str) -> dict[str, Any] | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _bad(action, f"{key} must be an object")
    return value


def _module_op(act: str, args: Mapping[str, Any], action: str) -> dict[str, Any]:
    """add_module {module, variant?, ref?, conn?, address?, facts?, qty?}, connect {ref, conn?, address?, facts?,
    variant?, qty?} (changes the part in place), set_rails {rails?, rail_limits?};
    project.update checks the values."""
    op: dict[str, Any] = {"op": act}
    if act in ("add_module", "connect"):
        if act == "add_module":
            op["module"] = _req(args, "module", action)
        else:
            op["ref"] = _req(args, "ref", action)
        for key in ("variant", "ref", "address"):
            if _str(args, key, action) is not None:
                op[key] = _str(args, key, action)
        for key in ("conn", "facts"):
            if _map_arg(args, key, action) is not None:
                op[key] = _map_arg(args, key, action)
        if _int(args, "qty", action) is not None:
            op["qty"] = _int(args, "qty", action)
        if act == "connect" and len(op) == 2:
            raise _bad(action, "connect needs conn {module pin: net}, address, facts, variant or qty",
                       "e.g. conn {\"SDA\": \"I2C_SDA\"} or {\"SDA\": \"GPIO8\"}; a role name stands for its net")
        return op
    for key in ("rails", "rail_limits"):
        if _map_arg(args, key, action) is not None:
            op[key] = _map_arg(args, key, action)
    if len(op) == 1:
        raise _bad(action, "set_rails needs rails {net: V} or rail_limits {net: A}")
    return op


def _demo(args: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from .bench_core import sim
    except ImportError:
        return fail("sim.demo", "dependency_missing", "the simulator is not part of this Circuit Bench build",
                    "update Circuit Bench; real projects work without it")
    return _with_project_view(sim.demo(project_id=_str(args, "id", "sim.demo") or "laser-trigger"))


def _solder_note(env: dict[str, Any], proj: Any) -> dict[str, Any]:
    """An ok answer about ``proj`` (the full project) plus a summary sentence when its solder plan is missing or no
    longer covers its parts (bench_core.solder.plan_state)."""
    from .bench_core import solder
    if not env.get("ok") or not isinstance(proj, Mapping) or not isinstance(env.get("summary"), str):
        return env
    st = solder.plan_state(proj)
    pid = proj.get("id")
    if st["state"] == "none":
        n = sum(1 for x in proj.get("parts") or [] if isinstance(x, Mapping) and x.get("ref"))
        text = f"Solder plan: none yet for {n} part{'' if n == 1 else 's'}; run bench_solder plan with project {pid}."
    elif st["state"] == "stale":
        detail = "; ".join(f"{label}: {solder.compress_refs(refs)}"
                           for label, refs in (("not in it", st["missing"]), ("removed", st["gone"])) if refs)
        text = f"Solder plan outdated ({detail}); run bench_solder plan with project {pid} again."
    else:
        return env
    return {**env, "summary": f"{env['summary']} {text}"}


def _project_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import project as P
    act = _act(args, PROJECT_ACTIONS, "bench_project")
    if act == "list":
        return P.list()
    if act == "demo":
        return _demo(args)
    action = {"get": "project.get", "create": "project.create"}.get(act, "project.update")
    pid = _req(args, "id", action)
    if act == "get":
        env = P.get(pid)
        return _solder_note(with_board_warnings(_with_project_view(env), _devkit_of(env)),
                            (env.get("result") or {}).get("project"))
    if act == "create":
        ops = _assign_ops(args, action, required=False)
        if "wifi" in args:
            ops.insert(0, {"op": "set_board", "wifi": _bool(args, "wifi", action)})
        env = P.create(pid, _str(args, "title", action) or pid, _req(args, "chip", action),
                       _str(args, "variant", action), _str(args, "devkit", action), by="agent")
        devkit = _devkit_of(env)
        if not env["ok"] or not ops:
            return with_board_warnings(_with_project_view(env), devkit)
        upd = _tool_error(P.update(pid, 1, ops, by="agent"), ops, offset=int("wifi" in args))
        if not upd["ok"]:
            return _attach_update(with_board_warnings(_with_project_view(env), devkit), pid, upd)
        out = _pin_checks(_update_view(upd, ops), upd)
        out["action"] = "project.create"
        out["summary"] = f"{env['summary']} {upd['summary']}"
        out["warnings"] = [*env["warnings"], *upd["warnings"]]
        out["assumptions"] = [a for a in env["assumptions"] if not (a["key"] == "wifi" and "wifi" in args)]
        return with_board_warnings(out, devkit)
    ops = _project_ops(act, args)
    upd = _tool_error(_apply(pid, ops, rev=_int(args, "rev", action)), ops)
    out = _update_view(upd, ops)
    if act in ("assign", "set_board", "add_parts", "remove_parts", *MODULE_OPS):  # board, pins, parts, modules or
        # rails changed: new verdicts; a plain part with conn can meet a module's requires[]
        out = _pin_checks(out, upd)
    res = upd.get("result") if isinstance(upd.get("result"), dict) else {}
    if act in ("add_parts", "remove_parts") or (act in ("add_module", "connect") and "parts" in res.get("changed", [])):
        out = _solder_note(out, res.get("project"))
    return with_board_warnings(out, _devkit_of(upd)) if act == "set_board" and "devkit" in args else out


# --------------------------------------------------------------------------------------------- bench_pins

def _board_ctx(args: Mapping[str, Any], action: str) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict]]:
    """chip/variant/devkit/wifi from the arguments, else from the project; assumptions for defaults."""
    from .bench_core.contracts import assumption
    pid = _str(args, "project", action)
    proj = _get_project(pid) if pid else None
    board = (proj or {}).get("board") or {}
    chip = _str(args, "chip", action)
    inherit = proj is not None and (chip is None or chip.lower().replace("-", "") == board.get("chip"))
    chip = chip or board.get("chip")
    if not chip:
        from .bench_core import chips
        raise _bad(action, f"give chip ({chips.ids_text()}) or project")
    out: dict[str, Any] = {"chip": chip}
    for key in ("variant", "devkit"):
        out[key] = _str(args, key, action) if key in args else (board.get(key) if inherit else None)
    notes: list[dict] = []
    if args.get("wifi") is not None:
        out["wifi"] = _bool(args, "wifi", action)
    elif proj is not None:
        out["wifi"] = bool((proj.get("options") or {}).get("wifi", True))
    else:
        out["wifi"] = True
        notes.append(assumption("wifi", "on", "not given; Wi-Fi on applies the stricter pin rules"))
    return out, proj, notes


def _pins_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import pins
    act = _act(args, PINS_ACTIONS, "bench_pins")
    if act == "modules":
        return _modules_list(args)
    if act == "module":
        return _module_info(args)
    action = f"pins.{act}"
    b, proj, notes = _board_ctx(args, action)
    if act == "check":
        items = _dicts(args, "assignments", action)
        if items is None and proj is not None:
            items = [{k: a.get(k) for k in ("role", "mode", "pin", "net")} for a in proj.get("assignments") or []]
        if not items:
            raise _bad(action, "give assignments [{role, mode, pin}] or a project with assignments")
        mods = {"parts": proj.get("parts") or [], "options": proj.get("options") or {}} if proj is not None else {}
        env = pins.check(b["chip"], items, variant=b["variant"], wifi=b["wifi"], devkit=b["devkit"], **mods)
    elif act == "suggest":
        reqs = _dicts(args, "requests", action)
        if not reqs:
            raise _bad(action, "give requests [{role, mode, pin?}]")
        asked = {r.get("role") for r in reqs if isinstance(r.get("role"), str)}
        taken = [a["pin"] for a in (proj or {}).get("assignments") or [] if a.get("role") not in asked]
        env = pins.suggest(b["chip"], reqs, variant=b["variant"], wifi=b["wifi"], devkit=b["devkit"], taken=taken,
                           limit=_int(args, "limit", action))
    else:
        if args.get("pin") is None:
            raise _bad(action, "pin is required (GPIO number)")
        env = pins.info(b["chip"], args.get("pin"), variant=b["variant"], devkit=b["devkit"])
        notes = []  # pins.info does not depend on Wi-Fi
    if env.get("ok") and notes:
        env = {**env, "assumptions": [*env["assumptions"], *notes]}
    return with_board_warnings(env, b["devkit"])


# --------------------------------------------------------------------------------------------- module catalog

def _catalog(action: str) -> Any:
    """The module catalog (modules.catalog()); a build without the loader answers rule_data_missing."""
    from .bench_core import modules
    try:
        return modules.catalog()
    except NotImplementedError:
        raise _Return(fail(action, "rule_data_missing", "the module catalog is not part of this build",
                           "update Circuit Bench")) from None


def _modules_list(args: Mapping[str, Any]) -> dict[str, Any]:
    action = "modules.list"
    q = _str(args, "q", action)
    if q is not None and len(q) > MODULE_Q_MAX:
        raise _bad(action, f"q is longer than {MODULE_Q_MAX} characters")
    limit = _int(args, "limit", action)
    limit = MODULES_LIMIT_DEFAULT if limit is None else limit
    offset = _int(args, "offset", action) or 0
    if not 1 <= limit <= MODULES_LIMIT_MAX or offset < 0:
        raise _bad(action, f"limit must be 1..{MODULES_LIMIT_MAX} and offset >= 0")
    category, interface = _str(args, "category", action), _str(args, "interface", action)
    res = _catalog(action).search(q=q, category=category, interface=interface, limit=limit, offset=offset)
    items = list(res.get("items") or [])
    total = int(res.get("total") or 0)
    filters = ", ".join(f"{k}={v!r}" for k, v in (("q", q), ("category", category), ("interface", interface)) if v)
    if total == 0:
        summary = f"No module matches{f' ({filters})' if filters else ''}."
    else:
        summary = (f"{total} module{'s' if total != 1 else ''}{f' for {filters}' if filters else ''}; showing "
                   f"{offset + 1}–{offset + len(items)}. Details: bench_pins action=module id=<id>.")
    return envelope(action, summary, {"total": total, "offset": offset, "limit": limit, "items": items})


def _f_compact(value: Any) -> Any:
    """Sourced numbers without evidence/page (the model gets the value, conditions and source id)."""
    if isinstance(value, dict):
        if "evidence" in value and ("value" in value or "rel" in value or "rel_offset" in value):
            return {k: value[k] for k in F_TOOL_KEYS if k in value}
        return {k: _f_compact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_f_compact(v) for v in value]
    return value


def module_view(entry: Mapping[str, Any], variant: str | None, *, compact: bool) -> dict[str, Any]:
    """The catalog entry for an answer: MODULE_VIEW_KEYS plus class, family, variant and the variant list.
    ``compact`` (tool): sourced numbers without evidence lines. Same shape as GET /modules/{id} (a test compares)."""
    view = {k: entry[k] for k in MODULE_VIEW_KEYS if k in entry}
    view.update({"class": entry.get("_class"), "family": entry.get("_wp"), "variant": variant,
                 "variants": [{"id": v.get("id"), "title": v.get("title")} for v in entry.get("variants") or []
                              if isinstance(v, Mapping)]})
    return _f_compact(view) if compact else view


def _module_info(args: Mapping[str, Any]) -> dict[str, Any]:
    from .bench_core import sources
    action = "modules.info"
    mid = _str(args, "id", action) or _str(args, "module", action)
    if mid is None:
        raise _bad(action, "id is required (a module id from bench_pins action=modules)")
    variant = _str(args, "variant", action)
    try:
        entry = _catalog(action).get(mid, variant)
    except BenchError as e:
        return from_error(action, e)
    srcs = []
    for sid in entry.get("source_ids") or []:
        try:
            srcs += sources.resolve([sid])
        except BenchError:
            logger.debug("circuit-bench: module source %s unknown", sid)
    warns = [warning(f"mod_hazard_{h.get('code')}", "danger" if h.get("code") in HAZARD_DANGER else "caution",
                     str(h.get("text") or h.get("code")), [h["source_id"]] if h.get("source_id") else [])
             for h in entry.get("hazards") or [] if isinstance(h, Mapping)]
    ifaces = ", ".join(str(i.get("type")) for i in entry.get("interfaces") or [] if isinstance(i, Mapping)) or "none"
    summary = (f"{entry.get('title', mid)} ({entry.get('id', mid)}{f', variant {variant}' if variant else ''}): "
               f"{len(entry.get('pins') or [])} pins, interfaces {ifaces}; source class {entry.get('_class')}.")
    return envelope(action, summary, {"module": module_view(entry, variant, compact=True)}, warnings=warns,
                    sources=srcs)


# --------------------------------------------------------------------------------------------- bench_calc

CALC_PARAMS_HINT = "parameters: "  # how calckit.run starts the hint that lists a calculator's parameters


def _calc_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import calckit
    kind = _act(args, (*calckit.kinds(), CALC_LIST), "bench_calc")
    if kind == CALC_LIST:
        return calckit.listing(compact=True)
    action = f"calc.{kind}"
    inputs = args.get("inputs")
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise _bad(action, "inputs must be an object, e.g. {\"v_supply\": \"3V3\"}")
    params = dict(inputs)
    spec = calckit.params(kind)
    for name, *_ in spec:  # tolerate inputs given at the top level
        if name in args and name not in params:
            params[name] = args[name]
    pid = _str(args, "project", action)
    proj = _get_project(pid) if pid else None
    if proj is not None and params.get("chip") is None and any(p[0] == "chip" for p in spec):
        chip = (proj.get("board") or {}).get("chip")  # the project's chip picks the datasheet values
        if chip:
            params["chip"] = chip
    env = calckit.run(kind, params)
    err = env.get("error") or {}
    if (err.get("code") == "invalid_args" and str(err.get("message") or "").startswith("missing parameter")
            and str(err.get("hint") or "").startswith(CALC_PARAMS_HINT)):
        # the calculator names its parameters; the tool adds where they go
        names = str(err["hint"])[len(CALC_PARAMS_HINT):]
        env = {**env, "error": {**err, "hint": f"pass them inside inputs: {{{names}}}"}}
    if proj is None or pid is None or not env.get("ok"):
        return env
    prefix = f"{kind}-"
    used = {c.get("id") for c in proj.get("calcs") or []}
    n = next(i for i in range(1, 1000) if f"{prefix}{i}" not in used)
    cid = f"{prefix}{n}"
    obj = {"id": cid, "type": kind, "inputs": params, "result": env["result"], "assumptions": env["assumptions"],
           "sources": env["sources"]}
    return _attach_update(env, pid, _apply(pid, [{"op": "add_calc", "calc": obj}]), calc_id=cid)


# --------------------------------------------------------------------------------------------- bench_schematic

_SAFE = re.compile(r"[^a-z0-9_-]+")


def _now_tag() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%d-%H%M%S")


def _write_new(folder: Path, stem: str, text: str) -> Path:
    for n in range(100):
        path = folder / (f"{stem}.svg" if n == 0 else f"{stem}-{n}.svg")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return path
    raise BenchError("tool_failed", f"no free file name for {stem}.svg in {folder}")


def _out_dir(value: str, action: str) -> Path:
    from .bench_core import project as P
    folder = Path(value).expanduser()
    if not folder.is_absolute():
        raise _bad(action, "out_dir must be an absolute folder")
    folder = folder.resolve()
    if not folder.is_dir():
        raise _bad(action, f"out_dir {folder} is not a folder", "create the folder first or omit out_dir "
                   "(the project's artifacts folder is used)")
    if folder == P.PACKAGE_DIR or folder.is_relative_to(P.PACKAGE_DIR):
        raise _bad(action, "out_dir points into the plugin package")
    return folder


def _circuit_id(block: str, params: Mapping[str, Any], gpio: Any, part: str | None) -> str:
    """Stored circuit id: led-gpio4 as before; module-u1 (part) or module-bme280; level_shifter-gpio8."""
    if part:
        return f"{block}-{part}"
    gpios = params.get("gpios") if isinstance(params.get("gpios"), Mapping) else {}
    first = gpio if gpio is not None else next(iter(gpios.values()), None)
    if block == "module":
        name = params.get("module") if isinstance(params.get("module"), str) else "bme280"
        return f"{block}-{name}" + (f"-gpio{first}" if first is not None else "")
    return f"{block}-gpio{first}" if first is not None else block


def _schematic_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import project as P
    from .bench_core import schematic, serialport
    _act(args, ("render",), "bench_schematic")
    action = "schematic.render"
    params = args.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise _bad(action, "params must be an object, e.g. {\"r_base\": \"1k\"}")
    pid = _str(args, "project", action)
    out_dir = _str(args, "out_dir", action)
    folder = _out_dir(out_dir, action) if out_dir else None
    proj = _get_project(pid) if pid else None
    devkit = _str(args, "devkit", action) or ((proj or {}).get("board") or {}).get("devkit")
    gpio = args.get("gpio")
    role = _str(args, "role", action)
    part = _str(args, "part", action)  # a module part of the project (U1): module, conn, address, facts
    block = args.get("block")
    if part and block is None:
        block = "module"
    if gpio is None and role:
        if proj is None:
            raise _bad(action, "role needs a project (or give gpio)")
        hit = next((a for a in proj.get("assignments") or [] if a.get("role") == role), None)
        if hit is None:
            raise _bad(action, f"no assignment with role {role} in project {pid}", "assign it with bench_project first")
        gpio = hit["pin"]
    env = schematic.render(block, params, devkit=devkit, gpio=gpio, project=proj, role=role, part=part)
    net = next((a.get("value") for a in env.get("assumptions") or [] if a.get("key") == "net"), None)
    if isinstance(net, str) and params.get("net") is None:
        params = {**params, "net": net}  # store the net that was drawn, so a redraw keeps it
    res = env.get("result")
    if not isinstance(res, dict):
        return env
    env = {**env, "result": {k: v for k, v in res.items() if k != "svg"}}
    svg = res.get("svg")
    if not env.get("ok") or not isinstance(svg, str):
        return env
    block = str(res.get("block") or block)
    if part:
        params = {**params, "part": part}  # a redraw takes the part again
    cid = _SAFE.sub("", _circuit_id(block, params, gpio, part).lower())[:32] or "circuit"
    paths: list[Path] = []
    try:
        if proj is not None:
            target = P.artifacts_dir(pid) / f"{cid}.svg"
            tmp = target.with_suffix(".svg.tmp")
            tmp.write_text(svg, encoding="utf-8")
            tmp.chmod(0o600)
            os.replace(tmp, target)
            paths.append(target)
        if folder is not None:
            paths.append(_write_new(folder, cid, svg))
        if not paths:
            paths.append(_write_new(serialport.artifacts_dir(), f"schematic-{cid}-{_now_tag()}", svg))
    except (OSError, BenchError) as e:
        err = e if isinstance(e, BenchError) else BenchError("tool_failed", f"could not write the SVG ({type(e).__name__})")
        return from_error(action, err, result=env["result"], sources=env["sources"])
    shown = paths[-1]
    env["result"] = {**env["result"], "svg_path": str(shown), "media": f"MEDIA:{shown}"}
    if proj is None:
        return env
    circuit = {"id": cid, "block": block, "params": params, "svg": f"artifacts/{cid}.svg"}
    return _attach_update(env, pid, _apply(pid, [{"op": "add_circuit", "circuit": circuit}]), circuit_id=cid)


# --------------------------------------------------------------------------------------------- bench_solder

def _bom_parts(bom_input: Any) -> list[dict[str, Any]]:
    from .bench_core import bom
    out = []
    for p in bom.parse(bom_input):
        part = {"ref": p["ref"], "kind": p["kind"], "value": str(p.get("value") or p["ref"])[:60]}
        if p.get("package"):
            part["package"] = str(p["package"])[:40]
        if isinstance(p.get("qty"), int) and p["qty"] >= 1:
            part["qty"] = p["qty"]
        out.append(part)
    return out


def _solder_plan_view(env: dict[str, Any]) -> dict[str, Any]:
    """Compact plan for the model: per step id, n, refs, kind, action, hints as strings (``"danger: <text>"``,
    ``"caution: <text>"``, info just the text) and the step's ``source_ids`` (each once, first-seen order).
    The project stores the full steps."""
    res = env.get("result")
    if not env.get("ok") or not isinstance(res, dict) or not isinstance(res.get("steps"), list):
        return env
    steps = []
    for s in res["steps"]:
        if not isinstance(s, Mapping):
            steps.append(s)
            continue
        hints = [h for h in s.get("hints") or [] if isinstance(h, Mapping)]
        steps.append({**{k: s.get(k) for k in ("id", "n", "refs", "kind", "action")},
                      "hints": [str(h.get("text", "")) if h.get("severity") == "info"
                                else f"{h.get('severity')}: {h.get('text', '')}" for h in hints],
                      "source_ids": list(dict.fromkeys(str(i) for h in hints for i in h.get("source_ids") or []))})
    return {**env, "result": {**res, "steps": steps}}


def _solder_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import solder
    act = _act(args, ("plan", "step"), "bench_solder")
    action = f"solder.{act}"
    pid = _str(args, "project", action)
    if act == "step":
        if not pid:
            raise _bad(action, "step needs project (the plan and its ticks live in the project)")
        proj = _get_project(pid)
        step_id = _req(args, "step_id", action)
        done = _bool(args, "done", action, default=True)
        plan = proj.get("solder") or {}
        if not plan.get("steps"):
            raise _bad(action, f"project {pid} has no solder plan", "run bench_solder plan with the project first")
        env = solder.step({"steps": plan["steps"], "done": plan.get("done") or []}, step_id, done)
        if not env.get("ok"):
            return env
        upd = _apply(pid, [{"op": "solder_done", "step_id": step_id, "done": done}], rev=proj["rev"])
        if (upd.get("error") or {}).get("code") == "project_conflict":
            upd = _apply(pid, [{"op": "solder_done", "step_id": step_id, "done": done}])
        return _attach_update(env, pid, upd)
    bom_input = args.get("bom")
    if bom_input is not None and not isinstance(bom_input, str | list):
        raise _bad(action, "bom must be text (CSV with or without a header row, or one part per line) or a list of rows")
    proj = _get_project(pid) if pid else None
    if bom_input is None or bom_input == "" or bom_input == []:
        parts = (proj or {}).get("parts") or []
        if not parts:
            raise _bad(action, "give bom (CSV with or without a header row, or rows)" + (f"; project {pid} has no parts" if pid else ""),
                       "pass project (its parts list) or bom")
        bom_input = solder.rows_from_parts(parts)
        from_project = True
    else:
        from_project = False
    env = solder.plan(bom_input)
    if proj is None or not env.get("ok"):
        return _solder_plan_view(env)
    ops: list[dict[str, Any]] = [{"op": "set_solder_plan", "steps": env["result"]["steps"]}]
    if not from_project:
        try:
            ops.insert(0, {"op": "add_parts", "parts": _bom_parts(bom_input)})
        except BenchError:
            pass
    upd = _apply(pid, ops)
    if not upd.get("ok") and len(ops) > 1:  # parts the project refuses must not cost the plan
        upd = _apply(pid, ops[-1:])
    return _attach_update(_solder_plan_view(env), pid, upd)  # the project got the full steps above


# --------------------------------------------------------------------------------------------- bench_board

def _no_hook(action: str) -> dict[str, Any]:
    return fail(action, "not_confirmed", NO_HOOK_MSG, NO_HOOK_HINT)


def _sim_port_of(proj: Mapping[str, Any] | None) -> str | None:
    from .bench_core import guard
    det = ((proj or {}).get("board") or {}).get("detected") or {}
    port = det.get("port") if isinstance(det, dict) else None
    return port if guard.is_sim(port) else None


def flash_target(args: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """(project, port) of a ``bench_board flash`` call: the port comes from the arguments, else from the project's
    detected board. Shared by the handler and the pre_tool_call hook. Raises ``_Return`` with an error envelope."""
    action = "board.flash"
    pid = _str(args, "project", action)
    if not pid:
        raise _Return(fail(action, "not_confirmed", "flash needs project (detected board and approved build)",
                           "pass project; run bench_board detect and build with it first"))
    proj = _get_project(pid)
    port = _str(args, "port", action) or (((proj.get("board") or {}).get("detected") or {}).get("port"))
    if not port:
        raise _Return(fail(action, "not_confirmed", f"project {pid} has no detected board",
                           f"run bench_board detect with project {pid}, then build"))
    return proj, _port(port, action)


def _port(port: str, action: str) -> str:
    """The normalised port (realpath of /dev links, only serial devices or sim://); _Return on a bad one."""
    from .bench_core import guard
    try:
        return guard.normalize_port(port)
    except BenchError as e:
        raise _Return(from_error(action, e)) from None


def flash_sha_arg(args: Mapping[str, Any]) -> str | None:
    """The ``elf_sha256`` argument of a flash call, lower case; None if missing. Raises ``_Return`` (invalid_args)
    for anything but 12 to 64 hex digits."""
    value = args.get("elf_sha256")
    if value is None:
        return None
    if not isinstance(value, str) or not SHA_ARG_RE.match(value.strip().lower()):
        raise _bad("board.flash", "elf_sha256 must be 12 to 64 hex digits of the last build's elf_sha256", SHA_ARG_HINT)
    return value.strip().lower()


REBUILD_HINT = "run bench_board build with project {pid} again, then flash with its elf_sha256"
INCOMPLETE_BUILD_HINT = "run bench_board build with project {pid} again: the build output is incomplete"


def _flash_binding(host: Host, proj: Mapping[str, Any], port: str, sha: str,
                   given: str | None) -> dict[str, Any] | None:
    """Refuse unless the flash is exactly the one the hook asked about (None = OK).

    elf_sha256 must name the current last build; the hook's entry (project, port, MAC, ELF) must equal the project
    now (a build or a detection between the approval card and this handler changes it)."""
    from .bench_core import guard
    action = "board.flash"
    det = (proj.get("board") or {}).get("detected") or {}
    mac = str(det.get("mac") or "").lower()
    # one approval, one handler run: the hook's entry is used up by this call, whatever it answers
    approved = None if guard.is_sim(port) else host.take_flash(proj["id"], port)
    if given is not None and not sha.startswith(given):
        return fail(action, "elf_mismatch", f"elf_sha256 {given[:16]}… is not the last build ({sha[:12]}…)",
                    REBUILD_HINT.format(pid=proj["id"]))
    if guard.is_sim(port):
        return None
    if given is None:
        return fail(action, "not_confirmed", "pass elf_sha256 from the last bench_board build: the approval names "
                    "exactly that firmware", SHA_ARG_HINT)
    if approved is None:
        return fail(action, "not_confirmed", "this flash was not put to the user by the approval hook",
                    "call bench_board flash again (Hermes asks the user first)")
    if approved["elf_sha256"] != sha:
        return fail(action, "elf_mismatch", f"the firmware changed after the approval ({approved['elf_sha256'][:12]}… "
                    f"was approved, the last build is {sha[:12]}…)", "flash again: the user approves the new build")
    if (approved["port"], approved["mac"]) != (port, mac):
        return fail(action, "not_confirmed", "the detected board changed after the approval",
                    "flash again: the user approves the new board")
    return None


def _model_sources(env: dict[str, Any]) -> dict[str, Any]:
    """Model view of a bench_board answer: sources keep id, title, url and retrieved, without ``note`` (bench_core,
    routes and jobs keep the full sources)."""
    srcs = env.get("sources") if isinstance(env, dict) else None
    if not isinstance(srcs, list) or not srcs:
        return env
    return {**env, "sources": _slim_sources(srcs, len(srcs))}


def _detect(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import board, guard
    action = "board.detect"
    port = _port(_req(args, "port", action, PORT_HINT), action)
    pid = _str(args, "project", action)
    proj = _get_project(pid) if pid else None
    refusal = guard.check_serial(via="tool", settings=None, port=port, cron=host.cron(), action=action)
    if refusal is not None:
        return _model_sources(refusal)
    if not guard.is_sim(port) and not host.hook_active:
        return _no_hook(action)
    env = _model_sources(board.detect(port, devkit=((proj or {}).get("board") or {}).get("devkit")))
    if proj is None or not env.get("ok") or not isinstance(env.get("result"), dict):
        return env
    res = env["result"]
    chip_id = res.get("chip_id") or board.chip_from_esptool(res.get("chip"))
    if chip_id and chip_id != (proj.get("board") or {}).get("chip"):
        env = {**env, "warnings": [*env["warnings"], warning(
            "chip_mismatch", "caution", f"the board is an {chip_id}, project {pid} is set to "
            f"{(proj.get('board') or {}).get('chip')}; fix it with bench_project set_board")]}
    return _attach_update(env, pid, _apply(pid, [{"op": "set_detected", **res}], trusted=True))


ENV_HINT = "env is the NAME of an [env:NAME] section in the folder's platformio.ini"
BUILD_ARGS_HINT = "pass project (a bench project whose firmware folder is set) or project_dir together with env"
PORT_HINT = "bench_board ports lists the ports; the simulated board is sim://esp32s3-n16r8"
BUILD_CRON_MSG = "scheduled jobs (cron) cannot run real builds: a build runs the firmware project's own PlatformIO scripts"


class BuildTarget(NamedTuple):
    """What a ``bench_board build`` call builds. ``dir`` is resolved (symlinks and ``..``), ``port`` is the sim://
    port of a simulated build or None (offline real build), ``simulated`` is true exactly for a sim:// port."""
    project: dict[str, Any] | None
    dir: Path
    env: str
    port: str | None
    simulated: bool


def build_target(args: Mapping[str, Any]) -> BuildTarget:
    """The target of a ``bench_board build`` call: from the project's firmware folder or from project_dir + env.
    Shared by the handler and the pre_tool_call hook (the approval names exactly what the handler builds). Raises
    ``_Return`` with an error envelope."""
    from .bench_core import board, guard
    action = "board.build"
    pid = _str(args, "project", action)
    given_dir, given_env = _str(args, "project_dir", action), _str(args, "env", action)
    port = _str(args, "port", action)
    proj = None
    if pid:
        proj = _get_project(pid)
        fw = proj.get("firmware") or {}
        if not fw.get("dir") or not fw.get("env"):
            raise _bad(action, f"project {pid} has no firmware folder", "set it with bench_project set_firmware")
        if given_dir and Path(given_dir).expanduser().resolve() != Path(fw["dir"]).resolve():
            raise _bad(action, f"project {pid} builds {fw['dir']}; give either project or project_dir")
        if given_env and given_env != fw["env"]:
            raise _bad(action, f"project {pid} builds env {fw['env']}; give either project or env")
        pdir, penv = fw["dir"], fw["env"]
        if port is None:
            port = _sim_port_of(proj)
        if port is None and proj.get("simulated"):
            port = next((p["device"] for p in board.list_ports() if p.get("simulated")), None)
    else:
        pdir = _req(args, "project_dir", action, BUILD_ARGS_HINT)
        penv = _req(args, "env", action, ENV_HINT)
    if port is not None and not guard.is_sim(port):
        port = None  # an offline build never touches a real board
    try:
        folder = Path(pdir).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise _bad(action, "project_dir must be a folder with platformio.ini") from None
    return BuildTarget(proj, folder, penv, port, guard.is_sim(port))


def build_asks(target: BuildTarget) -> bool:
    """Does this build need the user's approval? Yes when PlatformIO (and so the project's own scripts) starts: a
    real target always, a ``sim://`` build only when the simulator would run pio. Shared by the handler and the hook."""
    from .bench_core import board
    return not target.simulated or board.build_runs_pio(target.dir, target.env, target.port)


def _build(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import board
    action = "board.build"
    target = build_target(args)
    if build_asks(target):
        # a build that starts pio runs the project's own scripts: only after the hook's approval, never in cron
        if host.cron():
            return fail(action, "unattended_blocked", BUILD_CRON_MSG, "run it in a chat or from the Bench UI")
        if not host.hook_active:
            return _no_hook(action)
    proj = target.project
    # the build pre-check compares env MCU and project chip before pio runs (chip_mismatch, platform_too_old)
    env = _model_sources(board.build(target.dir, target.env, port=target.port,
                                     chip=((proj or {}).get("board") or {}).get("chip")))
    res = env.get("result")
    if proj is not None and isinstance(res, dict) and "ok" in res:
        env = _attach_update(env, proj["id"], _apply(proj["id"], [{"op": "set_build", **res}], trusted=True))
    return _sizes_as_objects(env)


def _sizes_as_objects(env: dict[str, Any]) -> dict[str, Any]:
    """Model view of a build: ``ram_used``/``ram_total`` → ``ram: {used, total}`` (same for flash). Hermes Desktop
    shows every top-level ``*_total`` key of a tool result as a counter (\"327680 rams\"). Routes keep the flat form."""
    res = env.get("result")
    if not isinstance(res, dict):
        return env
    res = dict(res)
    for name in ("ram", "flash"):
        if f"{name}_used" in res or f"{name}_total" in res:
            res[name] = {"used": res.pop(f"{name}_used", None), "total": res.pop(f"{name}_total", None)}
    return {**env, "result": res}


def _flash(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import board, guard
    from .bench_core import settings as S
    action = "board.flash"
    proj, port = flash_target(args)
    given = flash_sha_arg(args)
    pid = proj["id"]
    fw = proj.get("firmware") or {}
    build = fw.get("last_build") or {}
    sha = build.get("elf_sha256") if build.get("ok") is True else None
    cfg = S.load()
    cron = host.cron()

    def approval() -> dict[str, Any] | None:
        refusal = guard.check_flash(via="tool", settings=cfg, project=proj, port=port, cron=cron)
        if refusal is not None:
            return refusal
        if not guard.is_sim(port) and not host.hook_active:
            return _no_hook(action)
        return None

    refusal = approval()
    if refusal is not None:
        return _model_sources(refusal)
    if not sha or not fw.get("dir") or not fw.get("env"):
        return fail(action, "not_confirmed", f"project {pid} has no successful build",
                    f"run bench_board build with project {pid} first")
    refusal = _flash_binding(host, proj, port, sha, given)
    if refusal is not None:
        return refusal
    env = _model_sources(board.flash(fw["dir"], fw["env"], port, expected_elf_sha256=sha, guard=approval,
                                     expected_images=build.get("images"), devkit=(proj.get("board") or {}).get("devkit"),
                                     expected_board=(proj.get("board") or {}).get("detected")))
    err = env.get("error") if isinstance(env.get("error"), dict) else {}
    if err.get("code") in ("elf_mismatch", "elf_missing"):  # the agent's next step, named with its tool
        hint = REBUILD_HINT if err["code"] == "elf_mismatch" else INCOMPLETE_BUILD_HINT
        env = {**env, "error": {**err, "hint": hint.format(pid=pid)}}
    res = env.get("result")
    if not isinstance(res, dict) or "ok" not in res:
        return env
    return _attach_update(env, pid, _apply(pid, [{"op": "set_flash", **res}], trusted=True))


def _monitor(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import guard, serialport
    action = "serial.monitor"
    port = _port(_req(args, "port", action, PORT_HINT), action)
    seconds = _num(args, "seconds", action, MONITOR_DEFAULT_S)
    baud = _int(args, "baud", action)
    reset = _bool(args, "reset", action, default=False)
    refusal = guard.check_serial(via="tool", settings=None, port=port, cron=host.cron(), action=action)
    if refusal is not None:
        return _model_sources(refusal)
    if not guard.is_sim(port) and not host.hook_active:
        return _no_hook(action)
    return _model_sources(serialport.monitor(port, seconds, baud, reset=bool(reset)))


def _board_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import board
    act = _act(args, BOARD_ACTIONS, "bench_board")
    if act == "ports":
        return board.ports()
    return {"detect": _detect, "build": _build, "flash": _flash, "monitor": _monitor}[act](args, host)


# --------------------------------------------------------------------------------------------- bench_crash

def _crash_tool(args: Mapping[str, Any], host: Host) -> dict[str, Any]:
    from .bench_core import clitools, crash, serialport
    from .bench_core import project as P
    _act(args, ("decode",), "bench_crash")
    action = "crash.decode"
    log = args.get("log")
    if log is not None and not isinstance(log, str):
        raise _bad(action, "log must be text")
    log_ref = _str(args, "log_ref", action)
    if log_ref:
        try:
            log = serialport.artifact_path(log_ref).read_text(encoding="utf-8", errors="replace")
        except BenchError as e:
            raise _Return(from_error(action, e)) from None
        except OSError:
            raise _bad(action, f"log {log_ref} not found", "use the log_ref from bench_board monitor") from None
    if not log or not log.strip():
        raise _bad(action, "give log (the serial output with the panic) or log_ref",
                   "run bench_board monitor (port, seconds) and pass its log_ref, or bench_project get and pass "
                   "last_panic.log_ref, or paste the serial output with the panic as log")
    log = log[-LOG_MAX_CHARS:]
    elf = _str(args, "elf", action)
    chip = _str(args, "chip", action)
    pid = _str(args, "project", action)
    notes: list[dict[str, Any]] = []
    kw: dict[str, Any] = {"run": clitools.run}
    if pid:
        proj = _get_project(pid)
        fw = proj.get("firmware") or {}
        chip = chip or (proj.get("board") or {}).get("chip")
        kw["project_dir"] = fw.get("dir")
        if proj.get("simulated"):
            try:
                from .bench_core import sim
                kw["run"] = sim.crash_runner(kw.get("project_dir"))
            except ImportError:
                notes.append(warning("sim_missing", "info", "the simulator is not part of this build; frames of the "
                                     "simulated firmware are not resolved"))
            if not elf:
                rel = (fw.get("last_build") or {}).get("elf") or "firmware.elf"
                elf = str(Path(fw["dir"]) / rel) if fw.get("dir") else rel
        elif not elf and fw.get("dir") and fw.get("env"):
            elf = P.last_build_elf(proj)  # the stored last build; pio is never asked
            if elf is None:
                notes.append(warning("elf_lookup_failed", "info", "no ELF from the project: no successful build is "
                                     f"stored; run bench_board build with project {pid}, or pass elf"))
    env = crash.decode(log, elf=elf, chip=chip, **kw)
    if notes:
        env = {**env, "warnings": [*env.get("warnings", []), *notes]}
    if not pid or not env.get("ok"):
        return env
    panic = dict(env.get("result") or {})
    if log_ref:
        panic["log_ref"] = log_ref
    return _attach_update(env, pid, _apply(pid, [{"op": "set_debug", "last_panic": panic}], trusted=True))


# --------------------------------------------------------------------------------------------- registration

IMPLEMENTATIONS: dict[str, Callable[[Mapping[str, Any], Host], dict[str, Any]]] = {
    "bench_project": _project_tool, "bench_pins": _pins_tool, "bench_calc": _calc_tool,
    "bench_schematic": _schematic_tool, "bench_solder": _solder_tool, "bench_board": _board_tool,
    "bench_crash": _crash_tool,
}


def run_tool(name: str, args: Any, host: Host) -> dict[str, Any]:
    """Envelope of tool ``name`` (never raises)."""
    default = DEFAULT_ACTION[name]
    try:
        if not isinstance(args, dict):
            return fail(default, "invalid_args", f"{name}: arguments must be a JSON object, not {type(args).__name__}")
        return IMPLEMENTATIONS[name](args, host)
    except _Return as r:
        return r.env
    except BenchError as e:
        return from_error(default, e)
    except Exception as e:
        logger.warning("circuit-bench: %s failed unexpectedly (%s)", name, type(e).__name__)
        logger.debug("circuit-bench: %s traceback", name, exc_info=True)
        return fail(default, "tool_failed", f"{name} failed unexpectedly ({type(e).__name__})",
                    "see the Hermes log; report it to the Circuit Bench maintainers")


def _guarded(name: str, host: Host) -> Callable[..., str]:
    def handler(args: Any, **kw: Any) -> str:
        try:
            return _dump(fit(run_tool(name, args, host)))
        except Exception as e:  # noqa: BLE001 - last line of defence (e.g. a result that cannot be serialised)
            logger.warning("circuit-bench: %s answer failed (%s)", name, type(e).__name__)
            return json.dumps({"ok": False, "action": DEFAULT_ACTION[name], "summary": f"{name} failed",
                               "result": {}, "checks": [], "warnings": [], "assumptions": [], "sources": [],
                               "simulated": False, "error": {"code": "tool_failed", "message": f"{name} failed",
                                                             "hint": None}})

    handler.__name__ = handler.__qualname__ = f"{name}_handler"
    handler.__doc__ = f"Hermes handler of {name} (JSON result envelope)."
    return handler


def make_handlers(host: Host) -> dict[str, Callable[..., str]]:
    return {name: _guarded(name, host) for name in IMPLEMENTATIONS}

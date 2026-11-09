"""Shared helpers of the route modules: core access, JSON bodies, HTTP status per error code, guarded handlers.

Every answer is a result envelope as JSON; the HTTP status follows ``error.code``. Handlers never
raise: a bug becomes ``tool_failed`` (502) with the type of the exception, never its text (no secrets, no paths).
"""
import functools
import importlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("circuit_bench.dashboard")

PLUGIN_ID = "circuit-bench"
KB = 1024
BODY_LIMIT = 256 * KB  # default request body limit
LOG_LIMIT = 512 * KB  # crash log (POST /crash/decode)
CSV_LIMIT = 256 * KB  # BOM text (POST /solder/plan)

# HTTP status per error code (the envelope is always the body)
STATUS: dict[str, int] = {
    "invalid_args": 400, "unknown_chip": 400, "unknown_pin": 400, "unknown_board": 400,
    "project_not_found": 404, "port_not_found": 404,
    "project_conflict": 409, "not_confirmed": 409, "elf_mismatch": 409, "chip_mismatch": 409, "platform_too_old": 409,
    "project_damaged": 422, "job_not_found": 404, "elf_missing": 422, "decode_failed": 422, "rule_data_missing": 422,
    "port_busy": 423, "flash_disabled": 423, "unattended_blocked": 423, "sim_only": 423,
    "dependency_missing": 503, "tool_missing": 503,
    "timeout": 504,
    "tool_failed": 502,
}


class Core:
    """Lazy access to the route copy of bench_core: ``core.project`` imports ``<pkg>.project`` on first use."""

    def __init__(self, pkg: ModuleType):
        self.pkg = pkg
        self.name = pkg.__name__
        # circuit_bench/ (the folder that holds bench_core/, data/ and plugin.yaml)
        self.package_dir = Path(next(iter(getattr(pkg, "__path__", [])), ".")).resolve().parent

    def __getattr__(self, name: str) -> ModuleType:
        if name.startswith("_"):
            raise AttributeError(name)
        return importlib.import_module(f"{self.name}.{name}")

    def optional(self, name: str) -> ModuleType | None:
        """An optional bench_core module (sim, doctor) or None if it is not there (ImportError)."""
        try:
            return importlib.import_module(f"{self.name}.{name}")
        except ImportError:
            return None


class Refusal(Exception):
    """Carries a finished error envelope out of a helper (bad body, missing project ...)."""

    def __init__(self, env: dict[str, Any]):
        super().__init__(env.get("summary", "refused"))
        self.env = env


def status_of(env: Mapping[str, Any], ok_status: int = 200) -> int:
    if env.get("ok") is True:
        return ok_status
    code = (env.get("error") or {}).get("code")
    return STATUS.get(code, 502) if isinstance(code, str) else 502


def respond(env: Mapping[str, Any], ok_status: int = 200) -> JSONResponse:
    return JSONResponse(dict(env), status_code=status_of(env, ok_status))


def refuse(core: Core, action: str, code: str, message: str, hint: str | None = None, **kw: Any) -> Refusal:
    return Refusal(core.contracts.fail(action, code, message, hint, **kw))


def rewrap(core: Core, env: Mapping[str, Any], action: str) -> dict[str, Any]:
    """An error envelope of a helper action (e.g. project.get) as an error of ``action``."""
    err = env.get("error") or {}
    try:
        return core.contracts.fail(action, err.get("code", "tool_failed"), err.get("message") or "failed", err.get("hint"))
    except ValueError:
        return core.contracts.fail(action, "tool_failed", "failed")


def from_exception(core: Core, action: str, exc: BaseException) -> dict[str, Any] | None:
    """A BenchError of any package copy as an error envelope of ``action``; None for other exceptions."""
    err = core.serialport.local_error(exc)
    if err is None:
        return None
    return core.contracts.from_error(action, err)


async def read_json(core: Core, request: Request, action: str, *, limit: int = BODY_LIMIT,
                    allowed: tuple[str, ...] | None = None, required: bool = True) -> dict[str, Any]:
    """The JSON object body (at most ``limit`` bytes). ``allowed``: the only keys accepted. Raises Refusal."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise refuse(core, action, "invalid_args", f"request body too large (limit {limit // KB} kB)")
        except ValueError:
            raise refuse(core, action, "invalid_args", "bad Content-Length header") from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise refuse(core, action, "invalid_args", f"request body too large (limit {limit // KB} kB)")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.strip():
        if required:
            raise refuse(core, action, "invalid_args", "expected a JSON object as request body")
        return {}
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise refuse(core, action, "invalid_args", "request body is not valid JSON") from None
    if not isinstance(body, dict):
        raise refuse(core, action, "invalid_args", "expected a JSON object as request body")
    if allowed is not None:
        unknown = sorted(set(body) - set(allowed))
        if unknown:
            raise refuse(core, action, "invalid_args", f"unknown field(s): {', '.join(unknown)[:120]}",
                         f"fields: {', '.join(allowed)}")
    return body


def text_field(core: Core, action: str, body: Mapping[str, Any], key: str, *, required: bool = True,
               max_len: int = 256) -> str | None:
    value = body.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise refuse(core, action, "invalid_args", f"{key} must be a non-empty text (at most {max_len} characters)")
    return value.strip()


def bool_field(core: Core, action: str, body: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = body.get(key, default)
    if not isinstance(value, bool):
        raise refuse(core, action, "invalid_args", f"{key} must be true or false")
    return value


def load_project(core: Core, action: str, project_id: Any) -> dict[str, Any]:
    """The project object (``project.get``) or Refusal with the error re-wrapped as ``action``."""
    if not isinstance(project_id, str) or not project_id:
        raise refuse(core, action, "invalid_args", "project must be a bench project id")
    env = core.project.get(project_id)
    if env.get("ok") is not True:
        raise Refusal(rewrap(core, env, action))
    return env["result"]["project"]


def add_warning(env: dict[str, Any], warn: Mapping[str, Any] | None) -> dict[str, Any]:
    if warn:
        env = dict(env)
        env["warnings"] = [*env.get("warnings", []), dict(warn)]
    return env


def store_in_project(core: Core, env: dict[str, Any], project_id: str, ops: list[dict[str, Any]], what: str,
                     attempts: int = 3, *, trusted: bool = False) -> dict[str, Any]:
    """Apply derived data (a plan, a decoded panic) to the project's current rev, retried on ``project_conflict``.
    Returns ``env``, with a ``project_not_updated`` warning if storing failed. ``trusted``: the ops carry a result the
    server produced itself (e.g. ``set_debug`` from crash.decode), see ``project.SERVER_OPS``."""
    saved: Mapping[str, Any] = {}
    for _ in range(attempts):
        current = core.project.get(project_id)
        if current.get("ok") is not True:
            saved = current
            break
        saved = core.project.update(project_id, current["result"]["rev"], ops, by="ui", trusted=trusted)
        if saved.get("ok") is True or (saved.get("error") or {}).get("code") != "project_conflict":
            break
    if saved.get("ok") is True:
        return env
    msg = (saved.get("error") or {}).get("message", "unknown error")
    return add_warning(env, core.contracts.warning("project_not_updated", "caution",
                                                   f"the {what} was not stored in project {project_id!r}: {msg}"))


def guarded(core: Core, action: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Wrap an async handler: Refusal -> its envelope; any other exception -> tool_failed (502), logged."""

    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except Refusal as r:
                return respond(r.env)
            except Exception as e:  # a route never raises; unexpected ones are logged
                env = from_exception(core, action, e)
                if env is not None:
                    return respond(env)
                logger.exception("circuit-bench: route %s failed", action)
                return respond(core.contracts.fail(action, "tool_failed", f"{action} failed ({type(e).__name__})",
                                                   "see the Hermes log"))
        return wrapper

    return deco


async def threaded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Blocking bench_core work off the event loop."""
    return await run_in_threadpool(fn, *args, **kwargs)


def board_warnings(core: Core, env: dict[str, Any], devkit: Any) -> dict[str, Any]:
    """The DevKit's board-level hazards as envelope warnings in front, each code once
    (bench_core may already have added them); same rule as tools.with_board_warnings (pins routes, GET /projects/{id})."""
    if not env.get("ok") or not isinstance(devkit, str) or not devkit:
        return env
    try:
        items = core.boards.warnings_of(devkit)
    except core.contracts.BenchError:
        return env
    have = {w.get("code") for w in env.get("warnings") or []}
    add = [core.contracts.warning(w["id"], w["severity"], w["message"], [w["source_id"]] if w.get("source_id") else [])
           for w in items if w.get("id") not in have and w.get("severity") in core.contracts.WARNING_SEVERITIES
           and w.get("message")]
    if not add:
        return env
    srcs = list(env.get("sources") or [])
    known = {s.get("id") for s in srcs if isinstance(s, dict)}
    for sid in dict.fromkeys(i for w in add for i in w["source_ids"] if i not in known):
        try:
            srcs += core.sources.resolve([sid])
        except core.contracts.BenchError:
            pass
    return {**env, "warnings": [*add, *(env.get("warnings") or [])], "sources": srcs}

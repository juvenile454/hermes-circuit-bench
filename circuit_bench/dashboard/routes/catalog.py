"""Module catalog routes: GET /modules (search) and GET /modules/{module_id}.

Same envelopes as ``bench_pins action=modules/module`` (``modules.list`` / ``modules.info``); the desktop gets the
sourced numbers with their evidence lines (the tool drops them to stay small). A test keeps the views equal
(tests/test_m0_api_modules.py).
"""
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request

from .common import Core, guarded, refuse, respond, threaded

LIMIT_DEFAULT = 40
LIMIT_MAX = 200
Q_MAX = 64
VIEW_KEYS = ("id", "title", "category", "manufacturer", "kind", "aliases", "pins", "interfaces", "supplies", "io",
             "current", "requires", "hazards", "notes")  # = tools.MODULE_VIEW_KEYS
HAZARD_DANGER = frozenset({"mains", "laser", "li_ion"})  # = tools.HAZARD_DANGER


def _catalog(core: Core, action: str) -> Any:
    try:
        return core.modules.catalog()
    except NotImplementedError:
        raise refuse(core, action, "rule_data_missing", "the module catalog is not part of this build",
                     "update Circuit Bench") from None


def _text(core: Core, action: str, query: Mapping[str, str], key: str) -> str | None:
    value = (query.get(key) or "").strip()
    if len(value) > Q_MAX:
        raise refuse(core, action, "invalid_args", f"{key} is longer than {Q_MAX} characters")
    return value or None


def _int(core: Core, action: str, query: Mapping[str, str], key: str, default: int, lo: int, hi: int) -> int:
    raw = query.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise refuse(core, action, "invalid_args", f"{key} must be a whole number") from None
    if not lo <= value <= hi:
        raise refuse(core, action, "invalid_args", f"{key} must be {lo}..{hi}")
    return value


def modules_list(core: Core, query: Mapping[str, str]) -> dict[str, Any]:
    action = "modules.list"
    q, category, interface = (_text(core, action, query, k) for k in ("q", "category", "interface"))
    limit = _int(core, action, query, "limit", LIMIT_DEFAULT, 1, LIMIT_MAX)
    offset = _int(core, action, query, "offset", 0, 0, 1_000_000)
    res = _catalog(core, action).search(q=q, category=category, interface=interface, limit=limit, offset=offset)
    items = list(res.get("items") or [])
    total = int(res.get("total") or 0)
    summary = (f"{total} module{'s' if total != 1 else ''} match; showing {offset + 1}–{offset + len(items)}."
               if total else "No module matches.")
    return core.contracts.envelope(action, summary, {"total": total, "offset": offset, "limit": limit, "items": items})


def module_view(entry: Mapping[str, Any], variant: str | None) -> dict[str, Any]:
    view = {k: entry[k] for k in VIEW_KEYS if k in entry}
    view.update({"class": entry.get("_class"), "family": entry.get("_wp"), "variant": variant,
                 "variants": [{"id": v.get("id"), "title": v.get("title")} for v in entry.get("variants") or []
                              if isinstance(v, Mapping)]})
    return view


def module_info(core: Core, module_id: str, query: Mapping[str, str]) -> dict[str, Any]:
    action = "modules.info"
    variant = _text(core, action, query, "variant")
    entry = _catalog(core, action).get(module_id, variant)  # unknown -> BenchError invalid_args (guarded)
    srcs = []
    for sid in entry.get("source_ids") or []:
        try:
            srcs += core.sources.resolve([sid])
        except core.contracts.BenchError:
            pass
    warns = [core.contracts.warning(f"mod_hazard_{h.get('code')}", "danger" if h.get("code") in HAZARD_DANGER
                                    else "caution", str(h.get("text") or h.get("code")),
                                    [h["source_id"]] if h.get("source_id") else [])
             for h in entry.get("hazards") or [] if isinstance(h, Mapping)]
    ifaces = ", ".join(str(i.get("type")) for i in entry.get("interfaces") or [] if isinstance(i, Mapping)) or "none"
    summary = (f"{entry.get('title', module_id)} ({entry.get('id', module_id)}{f', variant {variant}' if variant else ''}): "
               f"{len(entry.get('pins') or [])} pins, interfaces {ifaces}; source class {entry.get('_class')}.")
    return core.contracts.envelope(action, summary, {"module": module_view(entry, variant)}, warnings=warns,
                                   sources=srcs)


def register(router: APIRouter, core: Core) -> None:
    @router.get("/modules")
    @guarded(core, "modules.list")
    async def list_modules(request: Request):
        return respond(await threaded(modules_list, core, dict(request.query_params)))

    @router.get("/modules/{module_id}")
    @guarded(core, "modules.info")
    async def get_module(module_id: str, request: Request):
        return respond(await threaded(module_info, core, module_id, dict(request.query_params)))

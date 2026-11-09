"""Workshop routes: pins, calculators, schematic, solder plan, board layout (all deterministic bench_core code).

Calculators come from the register (``core.calckit``): one static ``POST /calc/<kind>``
per kind registered when the router is built (the old paths), ``GET /calc`` (envelope ``calc.list``: every calculator
with its inputs) and ``POST /calc/{kind}`` for kinds registered later; an unknown kind is a 404.
"""
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .common import (CSV_LIMIT, Core, board_warnings, guarded, load_project, read_json, refuse, respond,
                     store_in_project, threaded)

PIN_FIELDS = ("role", "mode", "pin", "net")
CALC_LIST_ACTION = "calc.list"


def calculators(core: Core) -> tuple[str, ...]:
    """The registered calculator kinds in register order (no literal list)."""
    return tuple(core.calckit.kinds())


def _board_args(core: Core, action: str, body: dict[str, Any]) -> tuple[Any, dict[str, Any], dict[str, Any] | None]:
    """(chip, {variant, wifi, devkit}, project or None): explicit fields win over the project's board."""
    project = load_project(core, action, body["project"]) if body.get("project") is not None else None
    kw: dict[str, Any] = {}
    chip = body.get("chip")
    if project is not None:
        board = project["board"]
        chip = chip if chip is not None else board["chip"]
        kw = {"variant": board.get("variant"), "devkit": board.get("devkit"),
              "wifi": (project.get("options") or {}).get("wifi", True)}
    for key in ("variant", "devkit", "wifi"):
        if key in body:
            kw[key] = body[key]
    if chip is None:
        raise refuse(core, action, "invalid_args", f"chip is required ({core.chips.ids_text()}) or a project")
    return chip, kw, project


def pins_check(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    chip, kw, project = _board_args(core, "pins.check", body)
    assignments = body.get("assignments")
    if assignments is None and project is not None:
        assignments = [{k: a[k] for k in PIN_FIELDS if a.get(k) is not None} for a in project["assignments"]]
        if not assignments:
            raise refuse(core, "pins.check", "invalid_args", f"project {project['id']!r} has no pin assignments yet",
                         "assign pins first or pass assignments")
    if project is not None:  # the project's modules and rails join the check
        kw = {**kw, "parts": project.get("parts") or [], "options": project.get("options") or {}}
    for key in ("parts", "options"):  # explicit parts/options (the desktop's unsaved view) win over the project's
        if body.get(key) is not None:
            kw = {**kw, key: body[key]}
    return board_warnings(core, core.pins.check(chip, assignments, **kw), kw.get("devkit"))


def pins_suggest(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    chip, kw, project = _board_args(core, "pins.suggest", body)
    taken = body.get("taken")
    if taken is None and project is not None:
        taken = [a["pin"] for a in project["assignments"]]
    return board_warnings(core, core.pins.suggest(chip, body.get("requests"), taken=taken or (), **kw), kw.get("devkit"))


def pins_info(core: Core, query: dict[str, str]) -> dict[str, Any]:
    body: dict[str, Any] = {k: v for k, v in query.items() if k in ("chip", "variant", "devkit", "project")}
    chip, kw, _project = _board_args(core, "pins.info", body)
    kw.pop("wifi", None)
    if not query.get("pin"):
        raise refuse(core, "pins.info", "invalid_args", "pin is required (e.g. pin=35 or pin=GPIO35)")
    return board_warnings(core, core.pins.info(chip, query["pin"], **kw), kw.get("devkit"))


def schematic(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    action = "schematic.render"
    block = body.get("block")
    if block is None and isinstance(body.get("part"), str):
        block = "module"  # part: a module part of the project
    if not isinstance(block, str):
        raise refuse(core, action, "invalid_args", "block is required",
                     f"blocks: {', '.join(str(b.get('block')) for b in core.schematic.blocks())}")
    devkit = body.get("devkit")
    project = load_project(core, action, body["project"]) if body.get("project") is not None else None
    if devkit is None and project is not None:
        devkit = project["board"].get("devkit")
    return core.schematic.render(block, body.get("params"), devkit=devkit, gpio=body.get("gpio"),
                                 project=project, role=body.get("role"), part=body.get("part"))


def solder_plan(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    action = "solder.plan"
    project = load_project(core, action, body["project"]) if body.get("project") is not None else None
    parts = body.get("bom")
    if parts is None and project is not None:
        parts = core.solder.rows_from_parts(project["parts"])
    if parts is None:
        raise refuse(core, action, "invalid_args", "bom is required (CSV text or a list of parts) or a project")
    env = core.solder.plan(parts)
    if project is None or env.get("ok") is not True:
        return env
    return store_in_project(core, env, project["id"], [{"op": "set_solder_plan", "steps": env["result"]["steps"]}],
                            "solder plan")


def board_layout(core: Core, board_id: str) -> dict[str, Any]:
    action = "board.layout"
    try:
        layout = core.boards.layout(board_id)
        ids = [layout["source_id"]]
        module_src = (layout.get("module") or {}).get("source_id")
        if module_src and module_src not in ids:
            ids.append(module_src)  # the module facts (name, flash, PSRAM) come from the ordering information
        srcs = core.sources.resolve(ids)
    except Exception as e:
        err = core.serialport.local_error(e)
        if err is None:
            raise
        return core.contracts.from_error(action, err)
    n = len(layout["left"]) + len(layout["right"])

    def count(k: int, word: str) -> str:
        return f"{k} {word}{'' if k == 1 else 's'}"

    summary = (f"{layout['title']} {layout.get('revision') or ''}".strip()
               + f": {count(n, 'header pin')}, {count(len(layout['onboard']), 'onboard part')}, "
               + f"{count(len(layout['usb']), 'USB port')}.")
    return core.contracts.envelope(action, summary, layout, sources=srcs)


def register(router: APIRouter, core: Core) -> None:
    pin_fields = ("chip", "variant", "wifi", "devkit", "project")

    @router.post("/pins/check")
    @guarded(core, "pins.check")
    async def check(request: Request):
        # parts/options: the desktop's module view (lib/modules.js modCheckExtras); pins_check lets them win
        body = await read_json(core, request, "pins.check", allowed=(*pin_fields, "assignments", "parts", "options"))
        return respond(await threaded(pins_check, core, body))

    @router.post("/pins/suggest")
    @guarded(core, "pins.suggest")
    async def suggest(request: Request):
        body = await read_json(core, request, "pins.suggest", allowed=(*pin_fields, "requests", "taken"))
        return respond(await threaded(pins_suggest, core, body))

    @router.get("/pins/info")
    @guarded(core, "pins.info")
    async def info(request: Request):
        return respond(await threaded(pins_info, core, dict(request.query_params)))

    def calc_route(kind: str) -> None:
        action = f"calc.{kind}"

        @router.post(f"/calc/{kind}", name=f"calc_{kind}")
        @guarded(core, action)
        async def calc(request: Request):
            body = await read_json(core, request, action)
            return respond(await threaded(core.calckit.run, kind, body))

    for kind in calculators(core):
        calc_route(kind)

    @router.get("/calc")
    @guarded(core, CALC_LIST_ACTION)
    async def calc_list():
        return respond(await threaded(core.calckit.listing))

    @router.post("/calc/{kind}")
    async def calc_any(kind: str, request: Request):
        """Kinds registered after the router was built; unknown kinds -> 404 (envelope calc.list)."""
        if kind not in calculators(core):
            env = core.contracts.fail(CALC_LIST_ACTION, "invalid_args", f"unknown calculator {kind[:40]!r}",
                                      "GET /calc lists the calculators")
            return JSONResponse(env, status_code=404)
        action = f"calc.{kind}"

        @guarded(core, action)
        async def run():
            body = await read_json(core, request, action)
            return respond(await threaded(core.calckit.run, kind, body))
        return await run()

    @router.post("/schematic")
    @guarded(core, "schematic.render")
    async def render(request: Request):
        body = await read_json(core, request, "schematic.render", allowed=("block", "params", "project", "devkit", "gpio", "role", "part"))
        return respond(await threaded(schematic, core, body))

    @router.post("/solder/plan")
    @guarded(core, "solder.plan")
    async def plan(request: Request):
        body = await read_json(core, request, "solder.plan", limit=CSV_LIMIT + 4096, allowed=("bom", "project"))
        return respond(await threaded(solder_plan, core, body))

    @router.get("/boards/{board_id}")
    @guarded(core, "board.layout")
    async def layout(board_id: str):
        return respond(await threaded(board_layout, core, board_id))

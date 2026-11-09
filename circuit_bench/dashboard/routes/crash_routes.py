"""POST /crash/decode {log | log_ref, project?, elf?, chip?}."""
from typing import Any

from fastapi import APIRouter, Request

from .common import LOG_LIMIT, Core, guarded, load_project, read_json, refuse, respond, store_in_project, threaded


def decode(core: Core, body: dict[str, Any]) -> dict[str, Any]:
    action = "crash.decode"
    log, ref = body.get("log"), body.get("log_ref")
    if (log is None) == (ref is None):
        raise refuse(core, action, "invalid_args", "pass either log (panic text) or log_ref (from a serial panic)")
    if ref is not None:
        if not isinstance(ref, str):
            raise refuse(core, action, "invalid_args", "log_ref must be the name of a panic log")
        path = core.serialport.artifact_path(ref)  # BenchError invalid_args for unknown or malformed refs
        if path.stat().st_size > LOG_LIMIT:
            raise refuse(core, action, "invalid_args", f"{ref} is larger than {LOG_LIMIT // 1024} kB")
        log = path.read_text(encoding="utf-8", errors="replace")
    if not isinstance(log, str) or not log.strip():
        raise refuse(core, action, "invalid_args", "log must be the panic text from the serial monitor")
    project = load_project(core, action, body["project"]) if body.get("project") is not None else None
    elf, chip = body.get("elf"), body.get("chip")
    for key, value in (("elf", elf), ("chip", chip)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise refuse(core, action, "invalid_args", f"{key} must be a text")
    kw: dict[str, Any] = {}
    if project is not None:
        elf = elf or core.project.last_build_elf(project)
        chip = chip or (project.get("board") or {}).get("chip")
        if (project.get("firmware") or {}).get("dir"):
            kw["project_dir"] = project["firmware"]["dir"]
        if project.get("simulated") is True:
            sim = core.optional("sim")
            runner = getattr(sim, "crash_runner", None) if sim is not None else None
            if callable(runner):
                kw["run"] = runner(kw.get("project_dir"))  # simulated addr2line answers matching the example firmware
    env = core.crash.decode(log, elf=elf, chip=chip, **kw)
    if project is None or env.get("ok") is not True:
        return env
    # keep the short form in the project (debug.last_panic)
    return store_in_project(core, env, project["id"], [{"op": "set_debug", "last_panic": {**env["result"], "log_ref": ref}}],
                            "decoded panic", trusted=True)


def register(router: APIRouter, core: Core) -> None:
    @router.post("/crash/decode")
    @guarded(core, "crash.decode")
    async def crash_decode(request: Request):
        body = await read_json(core, request, "crash.decode", limit=LOG_LIMIT + 8192,
                               allowed=("log", "log_ref", "project", "elf", "chip"))
        return respond(await threaded(decode, core, body))

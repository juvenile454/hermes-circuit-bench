"""Bench projects: list, create, demo, get, PATCH (typed ops), DELETE (to the trash), firmware example, solder step."""
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from .common import Core, Refusal, board_warnings, bool_field, guarded, load_project, read_json, refuse, respond, rewrap, text_field, threaded

EXAMPLE_RE = re.compile(r"^[a-z0-9-]{1,48}$")
ENV_RE = re.compile(r"^\s*\[env:([A-Za-z0-9_][A-Za-z0-9_.:-]{0,63})\]\s*$", re.MULTILINE)
COPY_IGNORE = shutil.ignore_patterns(".pio", ".git", "__pycache__", "*.pyc", ".vscode")


def examples_dir(core: Core) -> Path:
    """circuit_bench/data/examples (the laser-trigger example ships there)."""
    return core.package_dir / "data" / "examples"


def first_env(ini: Path) -> str | None:
    try:
        m = ENV_RE.search(ini.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return m.group(1) if m else None


def copy_example(core: Core, project_id: str, name: Any, overwrite: bool) -> dict[str, Any]:
    """Copy data/examples/<name>/ to projects/<id>/firmware/ and point firmware.dir at the copy (set_firmware)."""
    action = "project.update"
    if not isinstance(name, str) or not EXAMPLE_RE.match(name):
        raise refuse(core, action, "invalid_args", "example must be a name like 'laser-trigger'")
    root = examples_dir(core)
    src = root / name
    if not (src / "platformio.ini").is_file():
        known = sorted(p.name for p in root.iterdir() if (p / "platformio.ini").is_file()) if root.is_dir() else []
        raise refuse(core, action, "invalid_args", f"unknown example {name!r}",
                     f"examples: {', '.join(known)}" if known else "this installation ships no firmware examples")
    env_name = first_env(src / "platformio.ini")
    if env_name is None:
        raise refuse(core, action, "invalid_args", f"example {name!r} has no [env:<name>] in platformio.ini")
    project = load_project(core, action, project_id)
    dst = core.project.path(project_id) / "firmware"
    if dst.exists() and any(dst.iterdir()) and not overwrite:
        raise refuse(core, action, "project_conflict", f"project {project_id!r} already has a firmware folder",
                     "pass overwrite: true to replace it with a fresh copy of the example", result={"rev": project["rev"]})
    tmp = dst.with_name(f".firmware-{secrets.token_hex(4)}")
    try:
        shutil.copytree(src, tmp, ignore=COPY_IGNORE, symlinks=False)
        os.chmod(tmp, 0o700)
        if dst.exists():
            shutil.rmtree(dst)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    env = core.project.update(project_id, project["rev"], [{"op": "set_firmware", "dir": str(dst), "env": env_name}],
                              by="ui")
    if env.get("ok") is True:
        env = dict(env)
        env["summary"] = f"Copied example {name!r} to the project ({dst.name}/, env {env_name}). " + env["summary"]
    return env


def register(router: APIRouter, core: Core) -> None:
    @router.get("/projects")
    @guarded(core, "project.list")
    async def list_projects():
        return respond(await threaded(core.project.list_projects))

    @router.post("/projects")
    @guarded(core, "project.create")
    async def create_project(request: Request):
        action = "project.create"
        body = await read_json(core, request, action, allowed=("id", "title", "chip", "variant", "devkit", "simulated"))
        pid = text_field(core, action, body, "id", max_len=48)
        title = body.get("title", pid)
        chip = text_field(core, action, body, "chip", max_len=32)
        simulated = bool_field(core, action, body, "simulated", False)
        env = await threaded(core.project.create, pid, title, chip, body.get("variant"), body.get("devkit"),
                             simulated=simulated, by="ui")
        return respond(board_warnings(core, env, _devkit_of(env)))

    @router.post("/projects/demo")
    @guarded(core, "sim.demo")
    async def demo_project():
        sim = core.optional("sim")
        demo = getattr(sim, "demo", None) if sim is not None else None
        if not callable(demo):
            return respond(core.contracts.fail("sim.demo", "dependency_missing",
                                               "the simulator is not part of this installation (bench_core/sim.py)",
                                               "update Circuit Bench to get the laser-trigger demo"))
        return respond(await threaded(demo))

    @router.get("/projects/{project_id}")
    @guarded(core, "project.get")
    async def get_project(project_id: str):
        env = await threaded(core.project.get, project_id)
        return respond(board_warnings(core, env, _devkit_of(env)))

    @router.patch("/projects/{project_id}")
    @guarded(core, "project.update")
    async def patch_project(project_id: str, request: Request):
        action = "project.update"
        body = await read_json(core, request, action, allowed=("expected_rev", "ops"))
        if "expected_rev" not in body or "ops" not in body:
            raise refuse(core, action, "invalid_args", "expected {expected_rev, ops: [...]}",
                         "read the rev with GET /projects/{id}")
        # client ops only: results (set_detected, set_build, set_flash, set_debug) come from the server's own
        # detect/build/flash jobs and crash decode (project.update refuses them without trusted=True)
        env = await threaded(core.project.update, project_id, body["expected_rev"], body["ops"], by="ui")
        ops = body["ops"] if isinstance(body["ops"], list) else []
        if any(isinstance(o, dict) and o.get("op") == "set_board" for o in ops):  # a new DevKit: its hazards
            env = board_warnings(core, env, _devkit_of(env))
        return respond(env)

    @router.delete("/projects/{project_id}")
    @guarded(core, "project.delete")
    async def delete_project(project_id: str):
        # UI only (no agent tool): removing a project is the user's decision. A running build of this project would
        # record its result into a folder that is gone, so wait for it.
        action = "project.delete"
        busy = core.jobs.table().running(f"build:{project_id}")
        if busy:
            raise refuse(core, action, "port_busy", f"a build ({busy}) is still running for {project_id!r}",
                         f"wait for {busy} to finish, then delete")
        return respond(await threaded(core.project.delete, project_id, by="ui"))

    @router.post("/projects/{project_id}/firmware/example")
    @guarded(core, "project.update")
    async def firmware_example(project_id: str, request: Request):
        action = "project.update"
        body = await read_json(core, request, action, allowed=("example", "overwrite"), required=False)
        overwrite = bool_field(core, action, body, "overwrite", False)
        env = await threaded(copy_example, core, project_id, body.get("example", "laser-trigger"), overwrite)
        return respond(env)

    @router.post("/projects/{project_id}/solder/{step_id}")
    @guarded(core, "project.update")
    async def solder_step(project_id: str, step_id: str, request: Request):
        action = "project.update"
        body = await read_json(core, request, action, allowed=("done", "expected_rev"), required=False)
        done = bool_field(core, action, body, "done", True)

        def work() -> dict[str, Any]:
            rev = body.get("expected_rev")
            if rev is None:  # a check mark is not an edit conflict: apply it to the current rev
                rev = load_project(core, action, project_id)["rev"]
            return core.project.update(project_id, rev, [{"op": "solder_done", "step_id": step_id, "done": done}],
                                       by="ui")

        try:
            env = await threaded(work)
        except Refusal as r:
            return respond(r.env)
        if env.get("ok") is not True and env.get("action") != action:
            env = rewrap(core, env, action)
        return respond(env)


def _devkit_of(env: dict[str, Any]) -> Any:
    """DevKit id of the project in a project.create/get/update answer (None if absent or failed)."""
    res = env.get("result") if env.get("ok") else None
    proj = res.get("project") if isinstance(res, dict) else None
    return ((proj or {}).get("board") or {}).get("devkit") if isinstance(proj, dict) else None

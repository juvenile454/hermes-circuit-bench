"""Board operation: GET /ports, POST /board/detect|build|flash (as jobs), GET /board/flash/check, GET /jobs/{id}.

Approvals: routes always run with ``cron=False`` and ``via="route"`` (a click in the Bench UI).
- detect: ``guard.check_serial(action="board.detect")`` before the job (real ports need hardware access).
- flash: ``guard.check_flash`` before the job (synchronous 409/423) and again inside ``board.flash`` as the
  zero-argument ``guard`` (functools.partial). Simulated ports skip ``allow_flash`` and the hardware switch, but the
  route still wants the confirmation of the flash dialog (port, MAC, ELF hash) like for a real board.
- flash/check: the same checks without ``confirm`` (``check_flash(precheck=True)``) so the UI can lock
  its flash button; no port, no tool, no ``pio project metadata``.
- detect pauses the port itself (``board.detect`` runs esptool inside ``serialport.pause``); the route must not
  pause around it (a nested pause waits for its own flock and ends with port_busy).
"""
import functools
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request

from .common import Core, add_warning, guarded, load_project, read_json, refuse, respond, threaded

DETECT_HINT = "run detect and build first"


def _norm(value: Any) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def job_envelope(core: Core, job: Mapping[str, Any], *, simulated: bool) -> dict[str, Any]:
    return core.contracts.envelope("job.get", core.jobs.summary(job), dict(job), simulated=simulated)


def port_arg(core: Core, action: str, port: str) -> str:
    """The normalised port for guard, job key and board (realpath of /dev links, only serial devices)."""
    try:
        return core.serialport.normalize_port(port)
    except Exception as e:
        err = core.serialport.local_error(e)
        if err is None:
            raise
        raise refuse(core, action, err.code, err.message, err.hint, simulated=core.guard.is_sim(port)) from None


def _start(core: Core, action: str, kind: str, work, *, key: str, simulated: bool):
    try:
        job = core.jobs.table().start(kind, work, key=key, simulated=simulated)
    except Exception as e:
        err = core.serialport.local_error(e)
        if err is None:
            raise
        return respond(core.contracts.from_error(action, err, simulated=simulated))
    return respond(job_envelope(core, job, simulated=simulated), 202)


def _sim_port_of(core: Core, project: Mapping[str, Any], requested: str | None) -> str | None:
    """The sim:// port a simulated build goes to (the provider builds instead of pio)."""
    if requested is not None:
        return requested if core.guard.is_sim(requested) else None
    detected = (project.get("board") or {}).get("detected") or {}
    if core.guard.is_sim(detected.get("port")):
        return detected["port"]
    if project.get("simulated") is True:
        sims = [p["device"] for p in core.board.list_ports() if p.get("simulated")]
        return sims[0] if sims else None
    return None


def sim_confirm_refusal(core: Core, project: Mapping[str, Any], port: str, confirm: Any, *,
                        precheck: bool = False) -> dict[str, Any] | None:
    """For sim:// ports the guard does not compare the dialog's confirmation; the route does (same rules).
    ``precheck``: only detection and build, not the confirmation (GET /board/flash/check)."""
    action = "board.flash"
    fail = core.contracts.fail
    detected = (project.get("board") or {}).get("detected")
    if not isinstance(detected, Mapping) or detected.get("port") != port:
        return fail(action, "not_confirmed", f"no board detected on {port}", DETECT_HINT, simulated=True)
    mac = _norm(detected.get("mac"))
    build = (project.get("firmware") or {}).get("last_build")
    sha = _norm(build.get("elf_sha256")) if isinstance(build, Mapping) and build.get("ok") is True else None
    if mac is None or sha is None:
        return fail(action, "not_confirmed", "no detected MAC or no successful build with an ELF hash", DETECT_HINT,
                    simulated=True)
    if precheck:
        return None
    if not isinstance(confirm, Mapping):
        return fail(action, "not_confirmed", "the flash was not confirmed in the Bench UI",
                    "confirm port, MAC and firmware in the flash dialog", simulated=True)
    if (confirm.get("port"), _norm(confirm.get("mac")), _norm(confirm.get("elf_sha256"))) != (port, mac, sha):
        return fail(action, "not_confirmed", "the confirmation does not match the detected board and the last build",
                    "detect and build again, then confirm the new values", simulated=True)
    return None


def register(router: APIRouter, core: Core) -> None:
    @router.get("/ports")
    @guarded(core, "board.ports")
    async def ports():
        return respond(await threaded(core.board.ports))

    @router.post("/board/detect")
    @guarded(core, "board.detect")
    async def detect(request: Request):
        action = "board.detect"
        body = await read_json(core, request, action, allowed=("port", "project", "before"))
        port = body.get("port")
        if not isinstance(port, str) or not port.strip():
            raise refuse(core, action, "invalid_args", "port is required (a device path or a sim:// port)")
        port = port_arg(core, action, port)
        before = body.get("before", "default-reset")
        if before not in core.board.BEFORE_MODES:
            raise refuse(core, action, "invalid_args", f"before must be one of {', '.join(core.board.BEFORE_MODES)}")
        pid = body.get("project")
        devkit = project_chip = None
        if pid is not None:
            pboard = (await threaded(load_project, core, action, pid)).get("board") or {}
            devkit, project_chip = pboard.get("devkit"), pboard.get("chip")
        cfg = core.settings.load()
        refused = core.guard.check_serial(via="route", settings=cfg, port=port, cron=False, action=action)
        if refused is not None:
            return respond(refused)
        simulated = core.guard.is_sim(port)

        def work(ctx) -> dict[str, Any]:
            # board.detect pauses the port (a monitor the broker holds) and takes its flock itself
            env = core.board.detect(port, before=before, on_line=ctx.log, devkit=devkit)
            if pid is not None:
                res = env.get("result") if env.get("ok") else None
                chip_id = ((res.get("chip_id") or core.board.chip_from_esptool(res.get("chip")))
                           if isinstance(res, dict) else None)
                if chip_id and project_chip and chip_id != project_chip:  # same caution as the agent tool
                    env = add_warning(env, core.contracts.warning(
                        "chip_mismatch", "caution", f"the board is an {chip_id}, project {pid} is set to "
                        f"{project_chip}; flashing is refused until the project chip matches (set_board)"))
                env = add_warning(env, core.jobs.record("detect", pid, env))
            return env

        return _start(core, action, "detect", work, key=f"port:{port}", simulated=simulated)

    @router.post("/board/build")
    @guarded(core, "board.build")
    async def build(request: Request):
        action = "board.build"
        body = await read_json(core, request, action, allowed=("project", "port"))
        pid = body.get("project")
        project = await threaded(load_project, core, action, pid)
        fw = project.get("firmware") or {}
        if not fw.get("dir") or not fw.get("env"):
            raise refuse(core, action, "invalid_args", f"project {pid!r} has no firmware folder yet",
                         "copy the example (POST /projects/{id}/firmware/example) or set_firmware first")
        requested = body.get("port")
        if requested is not None and not isinstance(requested, str):
            raise refuse(core, action, "invalid_args", "port must be a device path or a sim:// port")
        port = await threaded(_sim_port_of, core, project, requested)
        timeout = float(core.settings.load()["build_timeout_seconds"])

        def work(ctx) -> dict[str, Any]:
            env = core.board.build(fw["dir"], fw["env"], timeout=timeout, port=port, on_line=ctx.log,
                                   chip=(project.get("board") or {}).get("chip"))
            return add_warning(env, core.jobs.record("build", pid, env))

        return _start(core, action, "build", work, key=f"build:{pid}", simulated=port is not None)

    @router.post("/board/flash")
    @guarded(core, "board.flash")
    async def flash(request: Request):
        action = "board.flash"
        body = await read_json(core, request, action, allowed=("project", "confirm", "port"))
        pid = body.get("project")
        project = await threaded(load_project, core, action, pid)
        confirm = body.get("confirm")
        detected = (project.get("board") or {}).get("detected") or {}
        port = body.get("port")
        if port is not None and not isinstance(port, str):
            raise refuse(core, action, "invalid_args", "port must be a device path or a sim:// port")
        if port is None:
            port = (confirm or {}).get("port") if isinstance(confirm, Mapping) else None
        if port is None:
            port = detected.get("port")
        if not isinstance(port, str) or not port.strip():
            raise refuse(core, action, "not_confirmed", "no port to flash: the board was not detected yet", DETECT_HINT)
        port = port_arg(core, action, port)
        cfg = core.settings.load()
        gate = functools.partial(core.guard.check_flash, via="route", settings=cfg, project=project, port=port,
                                 confirm=confirm if isinstance(confirm, Mapping) else None, cron=False)
        refused = gate()
        simulated = core.guard.is_sim(port)
        if refused is None and simulated:
            refused = sim_confirm_refusal(core, project, port, confirm)
        if refused is not None:
            return respond(refused)
        fw = project.get("firmware") or {}
        sha = (fw.get("last_build") or {}).get("elf_sha256")
        images = (fw.get("last_build") or {}).get("images")  # the .bin files of exactly that build
        if not fw.get("dir") or not fw.get("env"):
            raise refuse(core, action, "not_confirmed", f"project {pid!r} has no firmware folder", DETECT_HINT)
        mac = detected.get("mac")

        def work(ctx) -> dict[str, Any]:
            env = core.board.flash(fw["dir"], fw["env"], port, expected_elf_sha256=sha, guard=gate, on_line=ctx.log,
                                   expected_images=images, devkit=(project.get("board") or {}).get("devkit"),
                                   expected_board=detected or None)
            return add_warning(env, core.jobs.record("flash", pid, env, port=port, mac=mac))

        return _start(core, action, "flash", work, key=f"port:{port}", simulated=simulated)

    @router.get("/board/flash/check")
    @guarded(core, "board.flash_check")
    async def flash_check(request: Request):
        """Would POST /board/flash refuse? ``ok: true``, ``result: {ready, refusal: null | {code, message, hint}}``.
        Bad input (no project, unknown project, bad port) is an error envelope."""
        action = "board.flash_check"
        unknown = sorted(set(request.query_params) - {"project", "port"})
        if unknown:
            raise refuse(core, action, "invalid_args", f"unknown parameter(s): {', '.join(unknown)[:120]}",
                         "parameters: project, port")
        pid = request.query_params.get("project")
        if not pid:
            raise refuse(core, action, "invalid_args", "project is required (a bench project id)")
        project = await threaded(load_project, core, action, pid)
        detected = (project.get("board") or {}).get("detected") or {}
        port = request.query_params.get("port") or detected.get("port")
        refusal: dict[str, Any] | None = None
        simulated = False
        if not isinstance(port, str) or not port.strip():
            refusal = core.contracts.fail("board.flash", "not_confirmed", "no port to flash: the board was not "
                                          "detected yet", DETECT_HINT)
        else:
            port = port_arg(core, action, port)
            simulated = core.guard.is_sim(port)
            cfg = core.settings.load()
            refusal = core.guard.check_flash(via="route", settings=cfg, project=project, port=port, cron=False,
                                             precheck=True)
            if refusal is None and simulated:
                refusal = sim_confirm_refusal(core, project, port, None, precheck=True)
        if refusal is None:
            env = core.contracts.envelope(action, f"Ready to flash project {pid} on {port}.",
                                          {"ready": True, "refusal": None}, simulated=simulated)
        else:
            err = refusal.get("error") or {}
            env = core.contracts.envelope(
                action, f"Flashing project {pid} would be refused: {err.get('message', 'refused')}",
                {"ready": False, "refusal": {"code": err.get("code"), "message": err.get("message"),
                                             "hint": err.get("hint")}}, simulated=simulated)
        return respond(env)

    @router.get("/jobs/{job_id}")
    @guarded(core, "job.get")
    async def get_job(job_id: str):
        job = core.jobs.table().get(job_id)
        if job is None:
            return respond(core.contracts.fail("job.get", "job_not_found", f"unknown job {job_id[:40]!r}",
                                               "jobs do not survive a backend restart; reload the project"))
        simulated = core.jobs.table().is_simulated(job_id)
        return respond(job_envelope(core, job, simulated=bool(simulated)))

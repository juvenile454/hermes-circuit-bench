#!/usr/bin/env python3
"""Sim chain on bench_core, without Hermes.

    scripts/sim_probe.py [--fast] [--toolchain] [--keep]

sim.demo -> board.detect -> board.build -> board.flash -> serial until the panic -> crash.decode -> fix the source
(DEMO_CRASH 0) -> build -> flash -> fixed boot ("[laser-trigger] boot ok"). Every result must be simulated.

Isolation: CIRCUIT_BENCH_HW=off, CIRCUIT_BENCH_DEV_GUARD=1, a temporary HOME, HERMES_HOME and CIRCUIT_BENCH_DATA_DIR
under $TMPDIR (checked by live_home_refusal() before anything runs: HERMES_HOME must be set and must not lie inside
the user's live ~/.hermes, except ~/.hermes/cache/scratch). The only port is sim://esp32s3-n16r8; no serial device is
opened, no esptool runs.
  --fast       no pauses on the simulated board
  --toolchain  real offline `pio run` for the builds (CB_TOOLCHAIN_TESTS=1; needs pio and espressif32@6.9.0 in
               ~/.platformio; build output under the temporary folder)
  --keep       keep the temporary folder
Re-runs itself with the main checkout's .venv (schemdraw for the schematic) when started with another Python.
"""
from __future__ import annotations

import argparse
import functools
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIX_FROM, FIX_TO = "#define DEMO_CRASH 1", "#define DEMO_CRASH 0"
BOOT_OK = "[laser-trigger] boot ok"


class ProbeError(AssertionError):
    pass


def _expect(cond: Any, msg: str) -> None:
    if not cond:
        raise ProbeError(msg)


class _Collector:
    """Messages of one port (subscribe before opening/flashing, so nothing is missed)."""

    def __init__(self, serialport: Any, port: str):
        self.msgs: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.unsubscribe = serialport.subscribe(port, self._add)

    def _add(self, msg: dict[str, Any]) -> None:
        with self.lock:
            self.msgs.append(msg)

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.msgs)

    def wait(self, predicate: Any, timeout: float, what: str) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msgs = self.snapshot()
            if predicate(msgs):
                return msgs
            time.sleep(0.02)
        raise ProbeError(f"timeout after {timeout:g} s waiting for {what}")


def _after_reflash(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages after the port was paused for the flash and opened again (the new firmware)."""
    paused = next((i for i, m in enumerate(msgs) if m["t"] == "state" and m["state"] == "paused"), None)
    if paused is None:
        return []
    reopened = next((i for i in range(paused + 1, len(msgs)) if msgs[i]["t"] == "state" and msgs[i]["state"] == "open"), None)
    return [] if reopened is None else msgs[reopened + 1:]


def chain(out: Any = print, *, timeout: float = 30.0) -> dict[str, Any]:
    """Run the chain in the current environment (the caller isolates it); raises ProbeError on any failure."""
    from circuit_bench.bench_core import board, guard, project, serialport, sim

    steps: list[dict[str, Any]] = []

    def step(name: str, env: dict[str, Any]) -> dict[str, Any]:
        steps.append({"step": name, "ok": env.get("ok"), "simulated": env.get("simulated"), "summary": env.get("summary")})
        out(f"[{len(steps):2d}] {name:<15} ok={env.get('ok')!s:<5} simulated={env.get('simulated')!s:<5} {env.get('summary')}")
        _expect(env.get("ok") is True, f"{name} failed: {env.get('error')}")
        _expect(env.get("simulated") is True, f"{name} is not marked simulated")
        return env

    def update(pid: str, ops: list[dict[str, Any]], what: str) -> dict[str, Any]:
        rev = project.get(pid)["result"]["rev"]
        # the chain records results of actions it ran itself (like jobs.record): trusted server-side writes
        return step(what, project.update(pid, rev, ops, by="agent", trusted=True))

    def approval(pid: str) -> Any:
        return functools.partial(guard.check_flash, via="tool", settings=None, project=project.get(pid),
                                 port=sim.PORT, cron=False)

    def flash(pid: str, fw: str, env_name: str, sha: str) -> dict[str, Any]:
        res = step("board.flash", board.flash(fw, env_name, sim.PORT, expected_elf_sha256=sha, guard=approval(pid)))
        update(pid, [{"op": "set_flash", **res["result"]}], "project.update")
        return res

    port = sim.PORT
    demo = step("sim.demo", sim.demo())
    pid, fw, env_name = demo["result"]["id"], demo["result"]["firmware_dir"], demo["result"]["env"]
    _expect(all(a["verdict"] == "ok" for a in demo["result"]["assignments"]), "demo pins are not all ok")
    again = sim.demo()
    _expect(again["ok"] and again["result"]["created"] is False and again["result"]["rev"] == demo["result"]["rev"],
            "second sim.demo changed the project")
    out(f"     sim.demo again: {again['summary']}")
    _expect(port in [p["device"] for p in board.ports()["result"]["ports"]], f"{port} is not listed")

    det = step("board.detect", board.detect(port))
    update(pid, [{"op": "set_detected", **det["result"]}], "project.update")
    b1 = step("board.build", board.build(fw, env_name, port=port))
    update(pid, [{"op": "set_build", **b1["result"]}], "project.update")
    flash(pid, fw, env_name, b1["result"]["elf_sha256"])

    col = _Collector(serialport, port)
    try:
        opened = serialport.open_port(port)
        out(f"     serial.open {port}: state={opened['state']} simulated={opened['simulated']}")
        msgs = col.wait(lambda ms: any(m["t"] == "panic" for m in ms), timeout, "the panic")
        pnc = next(m for m in msgs if m["t"] == "panic")
        before = [m["text"] for m in msgs if m["t"] == "line" and m["seq"] < pnc["seq"]]
        out(f"     panic at seq {pnc['seq']}: {pnc['summary']} (log_ref {pnc['log_ref']}), after {before[-1]!r}")
        log = serialport.artifact_path(pnc["log_ref"]).read_text(encoding="utf-8")
        # crash.decode with the simulated addr2line (sim.crash_runner); sim.decode marks the result simulated
        dec = step("crash.decode", sim.decode(log, elf=b1["result"]["elf_path"], project_dir=fw))
        top = dec["result"]["frames"][0]
        _expect(top["function"].startswith("write_sensor_buffer(") and top["file"] == "src/main.cpp",
                f"unexpected top frame {top}")
        src = (Path(fw) / "src" / "main.cpp").read_text(encoding="utf-8").splitlines()
        out(f"     src/main.cpp:{top['line']}: {src[top['line'] - 1].strip()}")
        update(pid, [{"op": "set_debug", "last_panic": {**dec["result"], "log_ref": pnc["log_ref"]}}], "project.update")

        main = Path(fw) / "src" / "main.cpp"
        text = main.read_text(encoding="utf-8")
        _expect(text.count(FIX_FROM) == 1, f"{FIX_FROM!r} not found once in {main}")
        main.write_text(text.replace(FIX_FROM, FIX_TO), encoding="utf-8")
        out(f"     fix: {FIX_FROM!r} -> {FIX_TO!r} in firmware/src/main.cpp")
        if b1["result"].get("toolchain") == "simulated":  # the simulated ELF hash is the hash of the sources
            stale = board.flash(fw, env_name, port, expected_elf_sha256=b1["result"]["elf_sha256"], guard=approval(pid))
            _expect(stale["ok"] is False and stale["error"]["code"] == "elf_mismatch",
                    "flash of a stale build was not refused")
            out(f"     flash without a new build: refused ({stale['error']['code']})")
        else:
            out("     real build: the old ELF is unchanged until the next build (a flash now would upload the old firmware)")
        b2 = step("board.build", board.build(fw, env_name, port=port))
        _expect(b2["result"]["elf_sha256"] != b1["result"]["elf_sha256"], "the fixed build has the old hash")
        update(pid, [{"op": "set_build", **b2["result"]}], "project.update")
        mark = len(col.snapshot())
        flash(pid, fw, env_name, b2["result"]["elf_sha256"])
        msgs = col.wait(lambda ms: any(m["t"] == "line" and m["text"] == BOOT_OK for m in _after_reflash(ms[mark:])),
                        timeout, f"{BOOT_OK!r} after the second flash")
        fresh = _after_reflash(msgs[mark:])
        _expect(not any(m["t"] == "panic" for m in fresh), "panic after the fix")
        for m in fresh:
            if m["t"] == "line" and m["text"].startswith("[laser-trigger]"):
                out(f"     serial: {m['text']}")
    finally:
        col.unsubscribe()
        serialport.close_port(port)

    final = project.get(pid)["result"]["project"]
    _expect(final["firmware"]["last_flash"]["elf_sha256"] == b2["result"]["elf_sha256"], "project has the wrong flash")
    _expect(final["debug"]["last_panic"]["reason"] == "StoreProhibited", "project has no panic")
    out(f"     project {pid}: rev {final['rev']}, last panic {final['debug']['last_panic']['top_frame']}, "
        f"board firmware state {sim.board_state()['firmware']}")
    return {"steps": steps, "project": final, "panic": pnc, "decode": dec}


def _main_checkout() -> Path:
    try:
        res = subprocess.run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True,
                             text=True, check=True)
        first = next(line.split(" ", 1)[1] for line in res.stdout.splitlines() if line.startswith("worktree "))
        return Path(first)
    except (OSError, subprocess.CalledProcessError, StopIteration):
        return ROOT


def _reexec_in_venv(argv: list[str]) -> None:
    venv = _main_checkout() / ".venv"
    py = venv / "bin" / "python"
    if os.environ.get("CB_SIM_PROBE_CHILD") == "1" or not py.is_file() or Path(sys.prefix) == venv:
        return
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["CB_SIM_PROBE_CHILD"] = "1"
    os.execve(str(py), [str(py), str(Path(__file__).resolve()), *argv], env)  # noqa: S606 - own venv python, fixed argv


def _real_home() -> Path:
    """Home directory of the account from the password database (not $HOME, which a test run may have replaced)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def live_home_refusal(hermes_home: str | None, real_home: str | os.PathLike[str]) -> str | None:
    """Why HERMES_HOME must not be used, or None when it is safe.

    Refused: unset or empty (Hermes would fall back to the live ~/.hermes), and any path that resolves (symlinks and
    `..` included, the path need not exist) to <real home>/.hermes or below it, except <real home>/.hermes/cache/scratch
    and below it, where scratch homes live."""
    live = os.path.realpath(os.path.join(real_home, ".hermes"))
    if not hermes_home:
        return f"HERMES_HOME is not set (Hermes would use {live})"
    real = os.path.realpath(hermes_home)

    def inside(path: str, root: str) -> bool:
        return path == root or path.startswith(root.rstrip(os.sep) + os.sep)

    if inside(real, os.path.join(live, "cache", "scratch")):
        return None
    if inside(real, live):
        return f"HERMES_HOME={real} is the live Hermes home"
    return None


def _isolate(tmp: Path, toolchain: bool) -> None:
    real_home = _real_home()
    dirs = {"HOME": tmp / "home", "HERMES_HOME": tmp / "hhome", "CIRCUIT_BENCH_DATA_DIR": tmp / "data"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    os.environ.pop("PYTHONPATH", None)
    os.environ.update({k: str(v) for k, v in dirs.items()})
    os.environ.update({"CIRCUIT_BENCH_HW": "off", "CIRCUIT_BENCH_DEV_GUARD": "1", "CIRCUIT_BENCH_SETTINGS_JSON": "{}"})
    for key in [k for k in os.environ if k.startswith("ESPTOOL_")]:
        del os.environ[key]
    os.environ.pop("CB_TOOLCHAIN_TESTS", None)
    if toolchain:
        pio = shutil.which("pio") or str(real_home / ".local" / "bin" / "pio")
        os.environ.update({"CB_TOOLCHAIN_TESTS": "1", "PLATFORMIO_CORE_DIR": str(real_home / ".platformio"),
                           "PLATFORMIO_BUILD_DIR": str(tmp / "pio-build"),
                           "PLATFORMIO_SETTING_ENABLE_TELEMETRY": "No",
                           "PLATFORMIO_SETTING_CHECK_PLATFORMIO_INTERVAL": "3650",
                           "CIRCUIT_BENCH_SETTINGS_JSON": f'{{"pio_path": "{pio}"}}'})
    refusal = live_home_refusal(os.environ.get("HERMES_HOME"), real_home)
    if refusal:
        raise SystemExit(f"sim_probe: refused: {refusal}")


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--fast", action="store_true", help="no pauses on the simulated board")
    ap.add_argument("--toolchain", action="store_true", help="real offline pio builds (CB_TOOLCHAIN_TESTS=1)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = ap.parse_args(args_list)
    _reexec_in_venv(args_list)
    tmp = Path(tempfile.mkdtemp(prefix="cb-sim-probe-", dir=os.environ.get("TMPDIR") or None))
    started = time.monotonic()
    try:
        _isolate(tmp, args.toolchain)
        sys.path.insert(0, str(ROOT))
        from circuit_bench.bench_core import sim
        if args.fast:
            sim.TIME_SCALE = 0.0
        print(f"sim_probe: python {sys.version.split()[0]} ({sys.prefix}), data {os.environ['CIRCUIT_BENCH_DATA_DIR']}, "
              f"CIRCUIT_BENCH_HW={os.environ['CIRCUIT_BENCH_HW']}, home check ok, "
              f"builds {'real pio' if args.toolchain else 'simulated'}")
        res = chain(timeout=900.0 if args.toolchain else 30.0)
    except ProbeError as e:
        print(f"sim_probe: FAILED: {e}")
        return 1
    finally:
        from circuit_bench.bench_core import runtime
        broker = runtime.peek("broker")
        if broker is not None:
            broker.shutdown()
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"sim_probe: OK ({len(res['steps'])} steps, all simulated, {time.monotonic() - started:.1f} s)"
          + (f", kept {tmp}" if args.keep else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

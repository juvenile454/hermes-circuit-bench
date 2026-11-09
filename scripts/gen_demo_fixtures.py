#!/usr/bin/env python3
"""Regenerate the demo fixtures from the real simulated chain, through the real backend routes.

    .venv/bin/python scripts/gen_demo_fixtures.py [--out DIR] [--write]

Runs POST /projects/demo -> detect -> build -> flash (confirmed) -> serial open/tail (panic) -> crash decode
-> GET /projects/laser-trigger against the in-process FastAPI app with the real sim:// board (no Hermes, no
hardware: CIRCUIT_BENCH_HW=off, temporary HOME/HERMES_HOME/data folder). Paths are anonymised. Default output is
$TMPDIR/cb-demo-fixtures; --write also replaces desktop-src/fixtures/{sim.demo,project.laser-trigger,
serial.lines,crash.decode}.json (a deliberate maintainer step).
"""
from __future__ import annotations

import json
import os
import pwd
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "desktop-src" / "fixtures"
NAMES = ("sim.demo", "project.laser-trigger", "serial.lines", "crash.decode")
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir  # the real home, before HOME points into the temporary folder


def _anon(obj, tmp: Path):
    s = json.dumps(obj, ensure_ascii=False)
    data = re.escape(str(tmp / "data"))
    s = re.sub(data, "/home/user/.hermes/plugin-data/circuit-bench", s)
    s = s.replace(str(tmp / "home"), "/home/user").replace(REAL_HOME, "/home/user")
    s = re.sub(r"panic-\d{8}-\d{6}(?:-\d+)?\.log", "panic-20261109-201500.log", s)
    s = re.sub(r'"epoch": "[0-9a-f]{8}-[0-9a-f]{8}"', '"epoch": "5f3c9a1e-0b7d42c6"', s)
    s = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", "2026-11-09T20:15:00Z", s)
    left = sorted(set(re.findall(rf'[^"]*(?:{re.escape(str(tmp))}|{re.escape(REAL_HOME)})[^"]*', s)))
    if left:
        raise SystemExit(f"anonymisation incomplete: {left[:5]}")
    return json.loads(s)


def main(argv: list[str]) -> int:
    out = Path(tempfile.gettempdir()) / "cb-demo-fixtures"
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1]).expanduser().resolve()
    write = "--write" in argv
    with tempfile.TemporaryDirectory(prefix="cb-demo-fx-") as t:
        tmp = Path(t)
        for d in ("home", "hhome", "data"):
            (tmp / d).mkdir()
        os.environ.update({"HOME": str(tmp / "home"), "HERMES_HOME": str(tmp / "hhome"),
                           "CIRCUIT_BENCH_DATA_DIR": str(tmp / "data"), "CIRCUIT_BENCH_SETTINGS_JSON": "{}",
                           "CIRCUIT_BENCH_HW": "off", "CIRCUIT_BENCH_DEV_GUARD": "1"})
        sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
        import test_api_support as sup  # loads the dashboard like the Hermes loader does
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        mod = sup.load_plugin_api()
        sup.route_module("sim").TIME_SCALE = 0.0
        app = FastAPI()
        app.include_router(mod.router, prefix=sup.PREFIX)
        c = TestClient(sup.StampPrincipal(app))

        def call(method: str, path: str, body=None, status=(200, 202)):
            r = c.request(method, sup.PREFIX + path, json=body)
            env = r.json()
            if r.status_code not in status or not env.get("ok"):
                raise SystemExit(f"{path}: HTTP {r.status_code} {json.dumps(env)[:400]}")
            return env

        def job(path: str, body: dict) -> dict:
            jid = call("POST", path, body)["result"]["job_id"]
            for _ in range(400):
                env = call("GET", f"/jobs/{jid}")
                if env["result"]["state"] == "done":
                    return env
                if env["result"]["state"] == "failed":
                    raise SystemExit(f"{path}: job failed {json.dumps(env)[:400]}")
                time.sleep(0.02)
            raise TimeoutError(path)

        got: dict[str, dict] = {}
        try:
            got["sim.demo"] = call("POST", "/projects/demo")
            port = got["sim.demo"]["result"]["port"]
            job("/board/detect", {"port": port, "project": "laser-trigger"})
            job("/board/build", {"project": "laser-trigger"})
            proj = call("GET", "/projects/laser-trigger")["result"]["project"]
            confirm = {"port": port, "mac": proj["board"]["detected"]["mac"],
                       "elf_sha256": proj["firmware"]["last_build"]["elf_sha256"]}
            call("POST", "/serial/open", {"port": port, "project": "laser-trigger"})
            job("/board/flash", {"project": "laser-trigger", "port": port, "confirm": confirm})
            tail = None
            for _ in range(400):
                tail = call("GET", f"/serial/tail?port={port}&after=0")
                if tail["result"].get("panic"):
                    break
                time.sleep(0.02)
            if not (tail and tail["result"].get("panic")):
                raise SystemExit("no panic on the simulated board")
            got["serial.lines"] = tail
            got["crash.decode"] = call("POST", "/crash/decode",
                                       {"log_ref": tail["result"]["panic"]["log_ref"], "project": "laser-trigger"})
            got["project.laser-trigger"] = call("GET", "/projects/laser-trigger")
        finally:
            sup.shutdown()
        got = {k: _anon(v, tmp) for k, v in got.items()}
    out.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        text = json.dumps(got[name], indent=2, ensure_ascii=False) + "\n"
        (out / f"{name}.json").write_text(text, encoding="utf-8")
        if write:
            (FIXTURES / f"{name}.json").write_text(text, encoding="utf-8")
        print(f"{name}: {got[name]['summary'][:110]}")
    print(f"wrote {len(NAMES)} fixtures to {out}" + (" and desktop-src/fixtures" if write else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

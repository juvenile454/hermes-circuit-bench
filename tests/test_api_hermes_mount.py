"""Backend routes in a real Hermes (marker ``hermes``).

- The real mount: the plugin is copied to a temporary HERMES_HOME (``plugins/circuit-bench``, enabled in
  ``config.yaml``), then ``hermes_cli.web_server`` is imported in a child process (it mounts plugin APIs at import
  time). Anonymous requests get 401, the session token 200; every route is mounted exactly once; the plugin
  WebSocket refuses anonymous sockets and serves one that carries a (stamped) native principal.
- Catalog checks on our files: no private Hermes imports (the scanner of ``hermes plugins validate``) and no
  high/critical findings of the plugin guard in dashboard/, jobs.py, portwatch.py.

Nothing here touches the live Hermes home: HOME, HERMES_HOME and TMPDIR of the child point into tmp_path.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.hermes

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "circuit_bench"
FAKES_BIN = ROOT / "tests" / "fakes" / "bin"
PREFIX = "/api/plugins/circuit-bench"
EXPECTED = sorted([
    "GET /health", "GET /doctor", "GET /projects", "POST /projects", "POST /projects/demo", "GET /projects/{project_id}",
    "PATCH /projects/{project_id}", "DELETE /projects/{project_id}", "POST /projects/{project_id}/firmware/example",
    "POST /projects/{project_id}/solder/{step_id}", "POST /pins/check", "POST /pins/suggest", "GET /pins/info",
    "POST /calc/led", "POST /calc/npn", "POST /calc/divider", "POST /calc/i2c_pullup", "POST /calc/mosfet", "POST /calc/ldo",
    "GET /calc", "POST /calc/{kind}", "GET /modules", "GET /modules/{module_id}",  # module routes
    "POST /schematic",
    "POST /solder/plan", "GET /boards/{board_id}", "GET /ports", "POST /board/detect", "POST /board/build",
    "POST /board/flash", "GET /board/flash/check", "GET /jobs/{job_id}", "POST /serial/open", "POST /serial/close", "GET /serial/tail",
    "WS /serial/stream", "POST /crash/decode",
])


def _expected() -> list[str]:
    """EXPECTED plus one fixed route per registered calculator (module families add kinds; same as test_api_routes)."""
    from circuit_bench.bench_core import calckit
    return sorted(set(EXPECTED) | {f"POST /calc/{kind}" for kind in calckit.kinds()})

CHILD = textwrap.dedent('''
    import json, os, sys
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from hermes_cli import web_server as ws  # mounts the plugin APIs at import time

    PREFIX = "/api/plugins/circuit-bench"
    out = {}
    routes = []
    for r in ws.app.router.routes:
        path = getattr(r, "path", "")
        if path.startswith(PREFIX + "/"):
            methods = sorted(getattr(r, "methods", None) or ["WS"])
            routes += [f"{m} {path[len(PREFIX):]}" for m in methods if m != "HEAD"]
    out["routes"] = routes

    def stamped(app):
        async def wrapper(scope, receive, send):  # plays the gate after it redeemed a Desktop native grant
            if scope["type"] == "websocket":
                scope.setdefault("state", {})["native_http_principal"] = {"profile_id": "default", "test": True}
            await app(scope, receive, send)
        return wrapper

    peer = ("127.0.0.1", 50123)
    base = "http://127.0.0.1:9119"
    with TestClient(ws.app, base_url=base, client=peer) as anon:
        r = anon.get(PREFIX + "/health")
        out["anon_health"] = [r.status_code, r.text[:200]]
        r = anon.post(PREFIX + "/projects", json={"id": "mount-a", "title": "Mount", "chip": "esp32s3"})
        out["anon_create"] = r.status_code
        try:
            with anon.websocket_connect(PREFIX + "/serial/stream?port=sim%3A%2F%2Fmount") as s:
                out["ws_anon"] = ["accepted", s.receive_json()]
        except WebSocketDisconnect as e:
            out["ws_anon"] = ["refused", e.code]
        except Exception as e:
            out["ws_anon"] = ["refused", type(e).__name__]
    with TestClient(ws.app, base_url=base, client=peer) as c:
        c.headers[ws._SESSION_HEADER_NAME] = ws._SESSION_TOKEN
        r = c.get(PREFIX + "/health")
        out["health"] = [r.status_code, r.json()]
        r = c.post(PREFIX + "/projects", json={"id": "mount-a", "title": "Mount", "chip": "esp32s3", "variant": "n16r8"})
        out["create"] = [r.status_code, r.json()["ok"], r.json()["result"].get("rev")]
        r = c.get(PREFIX + "/projects/mount-a")
        out["get"] = [r.status_code, r.json()["result"]["project"]["id"]]
        r = c.get(PREFIX + "/projects/nope")
        out["missing"] = [r.status_code, r.json()["error"]["code"]]
        r = c.get(PREFIX + "/ports")
        out["ports"] = [r.status_code, r.json()["result"], r.json()["warnings"][0]["code"]]
        r = c.post(PREFIX + "/board/detect", json={"port": "/dev/ttyACM0"})
        out["detect_real"] = [r.status_code, r.json()["error"]["code"]]
        r = c.get(PREFIX + "/serial/tail", params={"port": "sim://mount"})
        out["tail"] = [r.status_code, sorted(r.json()["result"])]
        r = c.get(PREFIX + "/calc")
        out["calc_list"] = [r.status_code, [k["kind"] for k in r.json()["result"]["calculators"]]]
        r = c.post(PREFIX + "/calc/led", json={"v_supply": "3V3", "v_f": "2V", "i_f": "5mA"})
        out["calc_led"] = [r.status_code, r.json()["action"]]
        r = c.get(PREFIX + "/modules")
        out["modules"] = [r.status_code, r.json()["action"]]
    with TestClient(stamped(ws.app), base_url=base, client=peer) as s_client:
        try:
            with s_client.websocket_connect(PREFIX + "/serial/stream?port=sim%3A%2F%2Fmount&native_dial=x") as s:
                out["ws_stamped"] = ["accepted", s.receive_json()]
        except WebSocketDisconnect as e:
            out["ws_stamped"] = ["refused", e.code]
    data = os.path.join(os.environ["HERMES_HOME"])
    out["project_files"] = sorted(str(p) for p in __import__("pathlib").Path(data).rglob("project.json"))
    with open(os.environ["CB_RESULT_FILE"], "w", encoding="utf-8") as f:  # Hermes may own stdout
        json.dump(out, f)
    os._exit(0)
''')


@pytest.fixture
def scratch_home(tmp_path):
    pytest.importorskip("hermes_cli.web_server_dashboard")
    home, hhome = tmp_path / "home", tmp_path / "hhome-mount"
    home.mkdir(exist_ok=True)
    from circuit_bench.bench_core import storage
    live = (storage.real_home() / ".hermes").resolve()
    for p in (home, hhome):  # never the live Hermes home (only below ~/.hermes/cache/scratch)
        assert not p.resolve().is_relative_to(live) or p.resolve().is_relative_to(live / "cache" / "scratch")
    shutil.copytree(PKG, hhome / "plugins" / "circuit-bench", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (hhome / "config.yaml").write_text("plugins:\n  enabled:\n    - circuit-bench\n", encoding="utf-8")
    return home, hhome


def test_real_mount_401_without_token_200_with_token(scratch_home, tmp_path):
    home, hhome = scratch_home
    script = tmp_path / "mount_child.py"
    script.write_text(CHILD, encoding="utf-8")
    result = tmp_path / "mount-result.json"
    env = {"HOME": str(home), "HERMES_HOME": str(hhome), "TMPDIR": str(tmp_path), "LANG": "C.UTF-8",
           "CB_RESULT_FILE": str(result),
           "PATH": f"{FAKES_BIN}{os.pathsep}/usr/bin{os.pathsep}/bin", "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
           "CIRCUIT_BENCH_HW": "off", "CIRCUIT_BENCH_DEV_GUARD": "1"}
    proc = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=240,
                          cwd=str(tmp_path), check=False)
    assert proc.returncode == 0 and result.is_file(), (proc.returncode, proc.stdout[-3000:], proc.stderr[-5000:])
    out = json.loads(result.read_text(encoding="utf-8"))
    assert sorted(out["routes"]) == _expected()  # every route mounted exactly once
    assert out["calc_list"][0] == 200 and out["calc_list"][1][:6] == ["led", "npn", "divider", "i2c_pullup", "mosfet",
                                                                       "ldo"]
    assert out["calc_led"] == [200, "calc.led"]
    assert out["modules"][1] == "modules.list"  # 200 with the catalog, rule_data_missing without it
    assert out["anon_health"][0] == 401 and out["anon_create"] == 401
    assert out["ws_anon"][0] == "refused"
    status, health = out["health"]
    assert status == 200 and health["ok"] is True and health["action"] == "health"
    assert health["result"]["plugin"] == "circuit-bench" and health["result"]["hardware_access"] is False
    assert health["result"]["hermes"]  # the Hermes distribution is visible in the scratch venv
    assert health["result"]["tools"]["pio"] == "unknown"  # the silent fake on PATH, never a real pio
    assert out["create"] == [200, True, 1] and out["get"] == [200, "mount-a"]
    assert out["missing"] == [404, "project_not_found"]
    status, res, code = out["ports"]  # hardware off: only the simulated board
    assert status == 200 and code == "hardware_off"
    assert [(p["device"], p["simulated"]) for p in res["ports"]] == [("sim://esp32s3-n16r8", True)]
    assert out["detect_real"] == [423, "sim_only"]
    assert out["tail"] == [200, ["epoch", "lines", "next_seq", "panic", "port", "simulated", "state"]]
    kind, state = out["ws_stamped"]
    assert kind == "accepted" and state["t"] == "state" and state["port"] == "sim://mount" and state["epoch"]
    assert out["project_files"] and all(p.startswith(str(hhome)) for p in out["project_files"])


def test_no_private_hermes_imports_in_the_package():
    from hermes_cli.plugin_validate_private_imports import private_import_findings

    assert private_import_findings(PKG) == []


def test_plugin_guard_finds_nothing_serious_in_our_files():
    from tools.plugin_guard import scan_plugin

    result = scan_plugin(PKG)
    ours = [f for f in result.findings
            if (f.file.startswith("dashboard/") or f.file in ("bench_core/jobs.py", "bench_core/portwatch.py"))
            and f.severity in ("high", "critical")]
    assert ours == []

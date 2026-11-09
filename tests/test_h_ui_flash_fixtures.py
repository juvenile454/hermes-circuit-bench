"""desktop-src/fixtures/flash.check.*.json are real answers of GET /board/flash/check.

Three states of the fixture project ``laser-trigger`` (the same project as ``project.laser-trigger.json``):

- ``ok``: the simulated board as detected and built (settings default, hardware off)
- ``flash_disabled``: the real port ``/dev/ttyACM0`` of ``ports.json`` with hardware access on and ``allow_flash`` off
- ``chip_mismatch``: ``allow_flash`` on, the board detected on ``/dev/ttyACM0`` as an ESP32-S3, the project then set to
  the ESP32-S2-DevKitC-1 (``set_board``), as the PLAN what-if "Apply to project" does in the fixture world

The precheck opens no port and starts no tool; like ``tests/test_h_board_flash_check.py`` every port lookup, CLI call
and serial open fails the run. The test compares the files with fresh answers (whole envelopes).

Script mode (writes the answers; desktop-src/fixtures only when given explicitly)::

    .venv/bin/python tests/test_h_ui_flash_fixtures.py --regen "$TMPDIR/cb-flash-check"
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:  # script mode
    sys.path.insert(0, str(TESTS))
if str(TESTS.parent) not in sys.path:
    sys.path.insert(0, str(TESTS.parent))

import board_fixtures as bf  # noqa: E402
import test_api_fixtures as taf  # noqa: E402
import test_api_support as sup  # noqa: E402

REAL = "/dev/ttyACM0"  # the real port of desktop-src/fixtures/ports.json
NAMES = ("flash.check.ok", "flash.check.flash_disabled", "flash.check.chip_mismatch")


def _no_hardware(mp: pytest.MonkeyPatch) -> None:
    sup.mock_ports(mp, [(REAL, 0x303A, 0x1001, "USB JTAG/serial debug unit", "TEST0001")])
    board = sup.route_module("board")
    for name in ("metadata", "project_config", "image_info", "_port_lookup", "_port_info", "detect", "flash", "build"):
        mp.setattr(board, name, lambda *a, _n=name, **k: pytest.fail(f"board.{_n} ran"))
    mp.setattr(sup.route_module("clitools"), "run", lambda *a, **k: pytest.fail("clitools.run ran"))
    sp = sup.route_module("serialport")
    mp.setattr(sp, "open_port", lambda *a, **k: pytest.fail("serial port opened"))
    real = sp._realpath
    mp.setattr(sp, "_realpath", lambda p: p if p == REAL else real(p))


def _check(api: sup.Api, **params) -> dict:
    env = api.get("/board/flash/check", params=params).json()
    assert sup.route_module("contracts").validate_envelope(env) == [], env
    return env


def generate(api: sup.Api, mp: pytest.MonkeyPatch, tmp: Path) -> dict[str, dict]:
    sup.route_module("board").register_provider("sim://", taf.DemoProvider(lines=["boot"]))
    pid = taf._build_demo_project(api, tmp)
    out = {"flash.check.ok": _check(api, project=pid)}
    _no_hardware(mp)
    mp.setenv("CIRCUIT_BENCH_HW", "on")
    mp.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"hardware_access": True, "allow_flash": False}))
    out["flash.check.flash_disabled"] = _check(api, project=pid, port=REAL)
    mp.setenv("CIRCUIT_BENCH_SETTINGS_JSON", json.dumps({"hardware_access": True, "allow_flash": True}))
    before = api.project(pid)
    det, build = before["board"]["detected"], before["firmware"]["last_build"]
    # set_board clears detection and build; both are recorded again as before (the fixture world keeps them)
    api.apply(pid, {"op": "set_board", "chip": "esp32s2", "devkit": "esp32-s2-devkitc-1"})
    api.record(pid, {"op": "set_detected", "port": REAL, "mac": det["mac"], "chip": det["chip"]},
               {"op": "set_build", **build})
    out["flash.check.chip_mismatch"] = _check(api, project=pid, port=REAL)
    return out


def test_flash_check_fixtures_are_real_answers(monkeypatch, tmp_path):
    with sup.api_session(monkeypatch) as api:
        got = generate(api, monkeypatch, tmp_path)
    assert got["flash.check.ok"]["result"] == {"ready": True, "refusal": None}
    assert got["flash.check.flash_disabled"]["result"]["refusal"]["code"] == "flash_disabled"
    assert got["flash.check.chip_mismatch"]["result"]["refusal"]["code"] == "chip_mismatch"
    for name in NAMES:
        assert taf._fixture(name) == got[name], name


def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "--regen":
        print(__doc__)
        return 2
    target = Path(argv[1]).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="cb-flash-check-") as t, pytest.MonkeyPatch.context() as mp:
        tmp = Path(t)
        for d in ("home", "hhome", "data"):
            (tmp / d).mkdir()
        for key, value in {"HOME": tmp / "home", "HERMES_HOME": tmp / "hhome", "CIRCUIT_BENCH_DATA_DIR": tmp / "data",
                           "CIRCUIT_BENCH_SETTINGS_JSON": "{}", "CIRCUIT_BENCH_HW": "off",
                           "CIRCUIT_BENCH_DEV_GUARD": "1"}.items():
            mp.setenv(key, str(value))
        mp.setenv("PATH", f"{bf.FAKES_BIN}{os.pathsep}{os.environ.get('PATH', '')}")
        with contextlib.ExitStack() as stack:
            api = stack.enter_context(sup.api_session(mp))
            answers = generate(api, mp, tmp)
    target.mkdir(parents=True, exist_ok=True)
    for name, env in sorted(answers.items()):
        (target / f"{name}.json").write_text(json.dumps(env, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name}: {env['summary']}")
    print(f"wrote {len(answers)} answers to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

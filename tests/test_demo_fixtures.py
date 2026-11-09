"""The demo fixtures (desktop-src/fixtures) stay in step with the real simulated chain through the real routes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from test_api_fixtures import FREE_FORM, key_diff

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("sim.demo", "project.laser-trigger", "serial.lines", "crash.decode")


def test_demo_fixtures_match_the_simulated_chain(tmp_path):
    out = tmp_path / "out"
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_demo_fixtures.py"), "--out", str(out)],
                          capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    for name in NAMES:
        real = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        fixture = json.loads((ROOT / "desktop-src" / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
        assert key_diff(fixture, real, skip=FREE_FORM.get(name, set())) == [], name
        assert real["summary"] == fixture["summary"], name

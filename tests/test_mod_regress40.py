"""Regression: the 40 hobby projects of a module rule review (tests/mod_projects40.py) against the
shown warnings of the module engine (after Finding.supersedes). Correct projects carry no caution/danger outside
expect/allow; faulty ones get the expected finding with the expected severity; pins.check stays below 8 KB.

Accepted deviations:
- p27 HC-SR04: the only source is class B (vendor sheet), so the echo finding stays info.
- p35 SIM800L: TXD VOH 2.4 V (no load given, Table 10) below the ESP-S3 VIH 2.48 V is a true, formal caution."""
from __future__ import annotations

import fnmatch
import json

import mod_projects40 as P
import pytest

from circuit_bench.bench_core import modcheck, pins
from circuit_bench.bench_core.contracts import MAX_RESULT_BYTES

ACCEPTED = {"p27_hcsr04_direct": {"expect"}, "p35_sim800l_3v3": {"extra"}}


def _match(pat, code):
    return any(fnmatch.fnmatch(code, p) for p in pat.split("|"))


@pytest.mark.parametrize("p", P.PROJECTS, ids=[p["id"] for p in P.PROJECTS])
def test_project(p):
    rep = modcheck.run(chip=p["chip"], assignments=p["assignments"], parts=p["parts"], options=p["options"])
    assert rep is not None
    ws = [(w["code"], w["severity"], w["message"]) for w in rep.warnings]
    skip = ACCEPTED.get(p["id"], set())
    if "expect" not in skip:
        for pat, sevs in p["expect"]:
            assert [w for w in ws if _match(pat, w[0]) and w[1] in sevs], (pat, sevs, ws)
    for fb in p["forbid"]:
        pat, sevs = (fb, {"caution", "danger"}) if isinstance(fb, str) else fb
        assert not [w for w in ws if _match(pat, w[0]) and w[1] in sevs], (pat, ws)
    if "extra" not in skip:
        allowed = [pat for pat, _ in p["expect"]] + list(p["allow"])
        extra = [w for w in ws if w[1] in ("caution", "danger") and not any(_match(a, w[0]) for a in allowed)]
        assert extra == [], extra
    env = pins.check(p["chip"], p["assignments"], parts=p["parts"], options=p["options"])
    assert env["ok"] and len(json.dumps(env).encode()) <= MAX_RESULT_BYTES

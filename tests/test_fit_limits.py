"""fit(): source notes go first; danger and caution warnings are never dropped or cut short (up to 600 chars), and
a solder plan of 15 parts in 11 kinds reaches the model whole (compact step view of bench_solder plan)."""
from __future__ import annotations

import json
import sys
import types

import pytest

from circuit_bench import tools
from circuit_bench.bench_core import contracts, solder

BOM15 = [("R1", "resistor", "4k7"), ("R2", "resistor", "4k7"), ("R3", "resistor", "10k"), ("R4", "resistor", "330"),
         ("C1", "ceramic", "100nF"), ("C2", "ceramic", "100nF"), ("C3", "electrolytic", "100uF 16V"),
         ("D1", "diode", "1N4148"), ("D2", "led", "green"), ("Q1", "transistor", "2N2222A"), ("J1", "header", "1x4"),
         ("J2", "connector", "JST-PH 2"), ("SW1", "switch", "tactile"), ("U1", "ic", "74AHCT125"),
         ("BZ1", "buzzer", "5V buzzer")]


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    cfg = types.ModuleType("hermes_cli.config")
    cfg.load_config = lambda: {"approvals": {"mode": "manual"}}
    pkg = types.ModuleType("hermes_cli")
    pkg.config = cfg
    monkeypatch.setitem(sys.modules, "hermes_cli", pkg)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", cfg)


def _bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def test_a_plan_of_15_parts_reaches_the_model_whole():
    rows = [{"ref": r, "kind": k, "value": v} for r, k, v in BOM15]
    full = solder.plan(rows)
    assert len(full["result"]["steps"]) == 11
    out = tools.make_handlers(tools.Host(hook_active=True))["bench_solder"]({"action": "plan", "bom": rows})
    env = json.loads(out)
    assert contracts.validate_envelope(env) == [], env
    assert len(out.encode("utf-8")) <= 8192
    assert "truncated" not in env["result"]
    assert not any(w["code"] == "result_truncated" for w in env["warnings"])
    assert len(env["result"]["steps"]) == 11
    dangers = [w for w in full["warnings"] if w["severity"] == "danger"]
    assert dangers and [w for w in env["warnings"] if w["severity"] == "danger"] == dangers


def test_the_compact_plan_view_has_the_documented_shape():
    rows = [{"ref": r, "kind": k, "value": v} for r, k, v in BOM15]
    full = solder.plan(rows)
    env = tools.fit(json.loads(tools.make_handlers(tools.Host())["bench_solder"]({"action": "plan", "bom": rows})))
    for compact, s in zip(env["result"]["steps"], full["result"]["steps"], strict=True):
        assert set(compact) == {"id", "n", "refs", "kind", "action", "hints", "source_ids"}
        assert {k: compact[k] for k in ("id", "n", "refs", "kind", "action")} == \
               {k: s[k] for k in ("id", "n", "refs", "kind", "action")}
        assert compact["hints"] == [h["text"] if h["severity"] == "info" else f"{h['severity']}: {h['text']}"
                                    for h in s["hints"]]
        assert compact["source_ids"] == list(dict.fromkeys(i for h in s["hints"] for i in h["source_ids"]))
    assert {k: v for k, v in env["result"].items() if k != "steps"} == \
           {k: v for k, v in full["result"].items() if k != "steps"}


def _dangers(n: int = 3, size: int = 500) -> list[dict]:
    return [contracts.warning(f"d{i}", "danger", f"{i}" + "d" * (size - 1)) for i in range(n)]


@pytest.mark.parametrize("keys", [50, 300], ids=["shortened", "last-stage"])
def test_danger_warnings_stay_whole_when_the_result_is_cut(keys):
    kept = {"rev": 4, "port": "sim://test-s3", "log_ref": "flash-1.log", "elf_sha256": "c" * 64}
    result = {**kept, **{f"k{i:03d}": "z" * 400 for i in range(keys)}}
    infos = [contracts.warning(f"i{i}", "info", "m" * 400) for i in range(30)]
    env = contracts.envelope("board.flash", "Flashed.", result, warnings=[*_dangers(), *infos])
    assert _bytes(env) > 20_000
    out = tools.fit(env)
    assert _bytes(out) <= tools.MAX_BYTES
    assert contracts.validate_envelope(out) == []
    assert out["result"]["truncated"] is True
    assert any(w["code"] == "result_truncated" for w in out["warnings"])
    assert [w for w in out["warnings"] if w["severity"] == "danger"] == _dangers()
    assert {k: out["result"][k] for k in kept} == kept
    assert len([w for w in out["warnings"] if w["code"].startswith("i")]) < len(infos)


def test_long_danger_and_caution_messages_are_cut_only_beyond_600_chars():
    long_danger = contracts.warning("d", "danger", "x" * 900)
    caution = contracts.warning("c", "caution", "y" * 600)
    env = contracts.envelope("pins.check", "s", {"blob": ["b" * 500] * 60}, warnings=[long_danger, caution])
    out = tools.fit(env)
    msgs = {w["code"]: w["message"] for w in out["warnings"]}
    assert msgs["d"] == "x" * 600 + "…"
    assert msgs["c"] == "y" * 600


def test_source_notes_go_first_without_marking_the_answer():
    sources = [{"id": f"s{i}", "title": f"Title {i}", "url": f"https://example.com/{i}", "retrieved": "2026-11-01",
                "note": "n" * 400} for i in range(20)]
    env = contracts.envelope("board.flash", "Flashed.", {"rev": 2, "lines": ["l" * 100] * 10},
                             warnings=[contracts.warning("w", "info", "a note")], sources=sources)
    assert _bytes(env) > tools.MAX_BYTES
    out = tools.fit(env)
    assert _bytes(out) <= tools.MAX_BYTES
    assert "truncated" not in out["result"]
    assert out["result"] == env["result"] and out["warnings"] == env["warnings"]
    assert not any(w["code"] == "result_truncated" for w in out["warnings"])
    assert all("note" not in s for s in out["sources"])
    assert [s["id"] for s in out["sources"]] == [s["id"] for s in sources]
    assert contracts.validate_envelope(out) == []

"""calc.led_strip planning current: a second, sourced current next to the datasheet test condition.

* data: data/parts/pixel.json carries ``i_planning`` for WS2812B and APA102C only; the quoted sentence is a line of the
  committed excerpt (tests/corpus/excerpts/pixel-planning-*.txt), the source entries in sources/calc-plus.json name the
  pinned snapshot (manifest tests/corpus/calc-pixel-planning.json);
* corpus (needs the pinned HTML in the corpus folder, skipped only when the file is missing): every excerpt line is in
  the file (line ⊂ excerpt ⊂ file) and the quote of pixel.json is in the file;
* behaviour: ``result.i_planning``, assumption ``planning_current``, summary with both currents, ``high_current`` from
  the larger value, no check status changes; a part without a planning value answers exactly as before.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import excerpts as ex
from circuit_bench.bench_core import calckit, parts, sources
from test_c0_corpus import html_text, squash

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "circuit_bench" / "data" / "parts" / "pixel.json"
PLUS_SOURCES = ROOT / "circuit_bench" / "data" / "sources" / "calc-plus.json"
MANIFEST = "calc-pixel-planning"

ADAFRUIT = "adafruit-neopixel-uberguide-powering"
SPARKFUN = "sparkfun-apa102-hookup-guide"
PLANNED = {"WS2812B": ADAFRUIT, "APA102C": SPARKFUN}
EXCERPT = {ADAFRUIT: "pixel-planning-adafruit-neopixel-uberguide.txt",
           SPARKFUN: "pixel-planning-sparkfun-apa102-hookup-guide.txt"}
SNAPSHOT = {ADAFRUIT: "https://web.archive.org/web/20261012131918id_/"
                      "https://learn.adafruit.com/adafruit-neopixel-uberguide/powering-neopixels",
            SPARKFUN: "https://web.archive.org/web/20260626110410id_/"
                      "https://learn.sparkfun.com/tutorials/apa102-addressable-led-hookup-guide/all"}
SHA = {ADAFRUIT: "754fb1eedf9c0b0b2bcd15d6e40b4e06abf078381017cd259e9d8cbc9580cd3d",
       SPARKFUN: "aa6d736db19e36f431aa1ce4dd666629cec454d16a5a2488975fc913386f0bd6"}


def _parts() -> dict[str, dict]:
    return {p["id"]: p for p in json.loads(PARTS.read_text(encoding="utf-8"))["parts"]}


def _manifest() -> dict[str, dict]:
    path = ex.MANIFESTS / f"{MANIFEST}.json"
    return {e["source_id"]: e for e in json.loads(path.read_text(encoding="utf-8"))["files"]}


def _calc(**p):
    return calckit.run("led_strip", p)


def _amps(q: dict) -> float:
    assert q["unit"] == "A"
    return q["value"]


# --- data ----------------------------------------------------------------------------------------------------------
def test_only_ws2812b_and_apa102c_carry_a_planning_value():
    got = {pid: p["i_planning"] for pid, p in _parts().items() if "i_planning" in p}
    assert set(got) == set(PLANNED)
    for pid, f in got.items():
        assert f["value"] == 0.06 and f["unit"] == "A" and f["basis"] == "rule_of_thumb"
        assert f["class"] == "B" and f["verified"] is False and f["source_id"] == PLANNED[pid]
        assert "not a datasheet value" in f["conditions"] and "full white" in f["conditions"]
    assert "i_planning" not in _parts()["SK6812"]  # no source names the part: no number


@pytest.mark.parametrize(("pid", "sid"), PLANNED.items())
def test_the_quote_is_a_line_of_the_excerpt_and_says_60_ma(pid, sid):
    f = _parts()[pid]["i_planning"]
    e = ex.parse(EXCERPT[sid])
    assert e.source_id == sid and e.pages() == []
    assert any(f["quote"] in line for line in e.lines), f["quote"]
    assert re.search(r"\b60 ?(?:mA|milliamps)\b", f["quote"]) and f["value"] == 0.06
    assert re.search(r"full-on|maximum brightness white", f["quote"])
    if "caveat_quote" in f:
        assert any(f["caveat_quote"] in line for line in e.lines)


@pytest.mark.parametrize("sid", SNAPSHOT)
def test_source_manifest_and_excerpt_agree(sid):
    src = sources.get(sid)
    entry = _manifest()[sid]
    e = ex.parse(EXCERPT[sid])
    assert src["url"] == entry["url"] == e.meta["url"] == SNAPSHOT[sid]
    assert re.fullmatch(r"https://web\.archive\.org/web/\d{14}id_/https://\S+", src["url"])
    assert entry["sha256"] == SHA[sid] and e.corpus() == (entry["path"], SHA[sid])
    assert entry["excerpt"] == f"excerpts/{EXCERPT[sid]}"
    assert src["class"] == "B" and src["retrieved"] == e.meta["retrieved"] == "2026-11-13"
    assert SHA[sid] in src["note"] and "not a datasheet" in src["note"]
    assert any(s["id"] == sid for s in json.loads(PLUS_SOURCES.read_text(encoding="utf-8")))


def test_every_planning_source_is_cited_by_a_part():
    cited = {p["i_planning"]["source_id"] for p in _parts().values() if "i_planning" in p}
    assert cited == set(SNAPSHOT)


# --- corpus: line ⊂ excerpt ⊂ file ---------------------------------------------------------------------------------
@pytest.mark.corpus
@pytest.mark.parametrize("sid", SNAPSHOT)
def test_excerpt_and_quote_are_in_the_pinned_file(sid):
    entry = _manifest()[sid]
    target = ex.CORPUS / entry["path"]
    if not target.is_file():
        pytest.skip(f"corpus file missing: {entry['path']} (scripts/fetch_corpus.py calc-pixel-planning)")
    data = target.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SHA[sid]
    text = html_text(data.decode("utf-8"))
    hay = squash(text)
    pos = 0
    for line in ex.parse(EXCERPT[sid]).lines:
        found = hay.find(squash(line), pos)
        assert found >= 0, f"{line!r} not found in {entry['path']} after offset {pos}"
        pos = found + len(squash(line))
        assert text.count(line) == 1  # the sentence is verbatim, not only whitespace-equal
    for p in _parts().values():
        f = p.get("i_planning")
        if f and f["source_id"] == sid:
            assert f["quote"] in text and squash(f["quote"]) in hay


# --- behaviour -----------------------------------------------------------------------------------------------------
def test_ws2812b_60_leds_show_both_currents_and_size_for_the_larger():
    e = _calc(count=60)
    r = e["result"]
    assert e["ok"] and _amps(r["i_total"]) == pytest.approx(60 * 0.0366)  # datasheet test condition, as before
    pl = r["i_planning"]
    assert _amps(pl) == pytest.approx(3.6) and _amps(pl["per_pixel"]) == 0.06
    assert pl["basis"] == "rule_of_thumb" and pl["class"] == "B" and pl["verified"] is False
    assert pl["source_id"] == ADAFRUIT and "not a datasheet value" in pl["conditions"]
    assert _amps(pl["size_supply_for"]) == pytest.approx(3.6) and pl["larger"] == "planning"
    s = e["summary"]
    assert "2.20 A" in s and s.count("3.60 A") == 2
    assert "rule of thumb, worst case at full white, not a datasheet value" in s and "larger" in s
    assert "datasheet test condition" in s
    assert [x for x in r["steps"] if x["name"] == "I_planning"][0]["value"]["value"] == pytest.approx(3.6)
    a = {x["key"]: x for x in e["assumptions"]}
    assert "planning_current" in a and "60.0 mA" in a["planning_current"]["value"]
    assert "rule of thumb, worst case at full white, not a datasheet value" in a["planning_current"]["reason"]
    assert ADAFRUIT in {s["id"] for s in e["sources"]}


def test_planning_current_is_independent_of_brightness():
    full, dim = _calc(count=60, brightness=1.0)["result"], _calc(count=60, brightness=0.1)["result"]
    assert _amps(full["i_planning"]) == _amps(dim["i_planning"]) == pytest.approx(3.6)
    assert _amps(dim["i_total"]) < _amps(full["i_total"])


def test_apa102c_gets_the_sparkfun_value_and_stays_unverified():
    e = _calc(count=144, part="apa102c", brightness=0.5)
    pl = e["result"]["i_planning"]
    assert _amps(pl) == pytest.approx(144 * 0.06) and pl["source_id"] == SPARKFUN
    assert e["ok"] and e["result"]["part"]["verified"] is False and "(unverified)" in e["summary"]
    assert {c["status"] for c in e["checks"]} == {"not_checked"}
    assert {w["severity"] for w in e["warnings"]} == {"info"}
    assert SPARKFUN in {s["id"] for s in e["sources"]}


def test_high_current_uses_the_larger_value():
    # 20 × WS2812B: 0.73 A from the test condition, 1.2 A planning value
    e = _calc(count=20)
    assert _amps(e["result"]["i_total"]) < 1.0 <= _amps(e["result"]["i_planning"])
    [w] = [x for x in e["warnings"] if x["code"] == "high_current"]
    assert w["severity"] == "info" and "1.20 A" in w["message"] and "rule of thumb" in w["message"]
    assert ADAFRUIT in w["source_ids"] and "rule-of-thumb" in w["source_ids"]
    assert "60.0 mA per pixel" in w["message"]  # the planning value behind the number is named
    assert "high_current" not in {x["code"] for x in _calc(count=10)["warnings"]}  # 0.6 A planning
    assert "high_current" not in {x["code"] for x in _calc(count=10, part="sk6812")["warnings"]}


def test_high_current_names_the_planning_value_for_both_planned_parts():
    for part, count, brightness in (("ws2812b", 20, 1.0), ("apa102c", 40, 0.5)):
        e = _calc(count=count, part=part, brightness=brightness)
        assert _amps(e["result"]["i_planning"]) > _amps(e["result"]["i_total"]), part  # the planning value is larger
        [w] = [x for x in e["warnings"] if x["code"] == "high_current"]
        assert "60.0 mA per pixel" in w["message"] and "not a datasheet value" in w["message"], part
        assert f"{count * 0.06:.2f} A at full setting" in w["message"], part
        ids = [x["id"] for x in e["sources"]]
        assert len(ids) == len(set(ids)), ids  # a source is listed once per answer
    # no planning value (SK6812) or the datasheet value is the larger one: nothing is claimed about 60 mA
    [w] = [x for x in _calc(count=40, part="sk6812")["warnings"] if x["code"] == "high_current"]
    assert "per pixel" not in w["message"] and "rule of thumb," not in w["message"]


def test_no_check_status_changes_with_the_planning_value(monkeypatch):
    with_plan = {}
    without = {}
    for key, p in (("a", dict(count=60)), ("b", dict(count=144, brightness=0.5, v_supply=5.5)),
                   ("c", dict(count=10, v_supply=3.3)), ("d", dict(count=144, part="apa102c", brightness=0.5))):
        with_plan[key] = _status(_calc(**p))
    real = parts.find
    monkeypatch.setattr(parts, "find", lambda name, kind=None: _strip(real(name, kind)))
    for key, p in (("a", dict(count=60)), ("b", dict(count=144, brightness=0.5, v_supply=5.5)),
                   ("c", dict(count=10, v_supply=3.3)), ("d", dict(count=144, part="apa102c", brightness=0.5))):
        without[key] = _status(_calc(**p))
    assert with_plan == without
    assert with_plan["a"][0] == {"calc.led_strip.supply": "passed", "calc.led_strip.level": "failed"}


def _status(e: dict) -> tuple[dict, dict]:
    return ({c["id"]: c["status"] for c in e["checks"]},
            {w["code"]: w["severity"] for w in e["warnings"] if w["code"] != "high_current"})


def _strip(rec):
    if rec is not None:
        rec.pop("i_planning", None)
    return rec


def test_the_larger_value_can_also_be_the_datasheet_one(monkeypatch):
    real = parts.find

    def low(name, kind=None):
        rec = real(name, kind)
        if rec and "i_planning" in rec:
            rec["i_planning"]["value"] = 0.01
        return rec

    monkeypatch.setattr(parts, "find", low)
    pl = _calc(count=60)["result"]["i_planning"]
    assert pl["larger"] == "datasheet" and _amps(pl["size_supply_for"]) == pytest.approx(60 * 0.0366)


# --- a part without a source answers exactly as before ---------------------------------------------------------------
# SHA-256 of the canonical JSON of summary, result, checks, warnings, assumptions and source ids of the answers below,
# computed on the code before the planning value existed.
_MATRIX = [(n, b, v) for n in (1, 10, 60, 144) for b in (0.1, 0.5, 1.0) for v in (3.3, 5.0, 5.5)]
BASELINE_SHA = {"sk6812": "f779ca45ddee5f9159658e6f9ca35c833b8a380a0c7c9ce44d4bf3b1903fd814",
                "ws2812b-without-planning": "4d4e004bbc07663e06247cd89320b0e98482fea3ebd031f06b73628c82164006",
                "apa102c-without-planning": "14180994b0dadec0af00bc8c17b07b939f80413b97ea857d0c299a6789de5f7d"}


def _digest(part: str) -> str:
    answers = []
    for n, b, v in _MATRIX:
        e = _calc(count=n, part=part, brightness=b, v_supply=v)
        answers.append([e["summary"], e["result"], e["checks"], e["warnings"], e["assumptions"],
                        [s["id"] for s in e["sources"]]])
    return hashlib.sha256(json.dumps(answers, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_sk6812_answers_exactly_as_before():
    assert _digest("sk6812") == BASELINE_SHA["sk6812"]
    e = _calc(count=60, part="sk6812")
    assert "i_planning" not in e["result"] and "planning_current" not in {a["key"] for a in e["assumptions"]}
    assert "planning" not in e["summary"] and not {ADAFRUIT, SPARKFUN} & {s["id"] for s in e["sources"]}


@pytest.mark.parametrize("part", ["ws2812b", "apa102c"])
def test_a_part_record_without_the_value_answers_exactly_as_before(monkeypatch, part):
    real = parts.find
    monkeypatch.setattr(parts, "find", lambda name, kind=None: _strip(real(name, kind)))
    assert _digest(part) == BASELINE_SHA[f"{part}-without-planning"]
    assert "i_planning" not in _calc(count=60, part=part)["result"]

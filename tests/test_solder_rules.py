"""rules.json and sources/solder.json stay consistent (no hint without a source, no invented numbers)."""
import json
import re
from pathlib import Path

from circuit_bench.bench_core import bom, sources

DATA = Path(__file__).resolve().parent.parent / "circuit_bench" / "data"
RULES = json.loads((DATA / "solder" / "rules.json").read_text(encoding="utf-8"))
SOLDER_SOURCES = json.loads((DATA / "sources" / "solder.json").read_text(encoding="utf-8"))
ALL = sources.all_sources()
SAFETY_POLICY = {"check_manually", "low_voltage_only"}  # product policy, not a fact: no source needed


def _hints():
    for k in RULES["kinds"]:
        for h in k["hints"]:
            yield k["kind"], h
    for h in RULES["text_rules"]:
        yield "text_rules", h
    for h in RULES["extra_hints"].values():
        yield "extra_hints", h


def test_solder_source_ids_are_prefixed_and_complete():
    for s in SOLDER_SOURCES:
        assert s["id"].startswith("solder-"), s["id"]
        assert s["url"].startswith("https://") and s["retrieved"] == "2026-11-06"
        assert s["note"]


def test_every_order_rule_is_rule_of_thumb():
    assert RULES["order"]["source_id"] == "rule-of-thumb"
    assert RULES["classify"]["capacitor_by_value"]["source_id"] == "rule-of-thumb"
    for k in RULES["kinds"]:
        assert k["source_id"] == "rule-of-thumb", k["kind"]


def test_every_hint_has_a_source_unless_it_is_policy():
    for where, h in _hints():
        ids = h.get("source_ids", [])
        assert all(i in ALL for i in ids), (where, h["code"])
        if h["code"] not in SAFETY_POLICY:
            assert ids, (where, h["code"])


def test_rule_of_thumb_hints_say_so():
    for where, h in _hints():
        if h.get("source_ids") == ["rule-of-thumb"]:
            assert "(rule of thumb)" in h["text"], (where, h["code"])


def test_manufacturer_claims_quote_their_source():
    """Each hint citing a manufacturer document carries evidence quoted in that source's note (source file is the audit
    trail: URL, retrieval date, PDF SHA-256, quote)."""
    for where, h in _hints():
        cited = [i for i in h.get("source_ids", []) if i != "rule-of-thumb"]
        if not cited:
            assert "evidence" not in h
            continue
        assert h.get("evidence"), (where, h["code"])
        notes = " ".join(ALL[i].get("note", "") for i in cited)
        for quote in h["evidence"]:
            assert quote in notes, (where, h["code"], quote)


def test_pdf_sources_record_their_hash():
    for s in SOLDER_SOURCES:
        if s["url"].endswith(".pdf"):
            assert re.search(r"SHA-256 [0-9a-f]{64}", s["note"]), s["id"]


def test_no_unsourced_numbers_in_hints():
    """No temperatures, times or other values in hint texts; digits only in part names (1N4001, TO-92) or 'pin 1'."""
    allowed = {"1N4001", "TO-92", "PN2222", "P2N2222A", "WP7113GD"}
    for where, h in _hints():
        text = h["text"]
        assert not re.search(r"\d\s*(°|℃|deg|s\b|sec|mm|w\b|v\b|ma\b)", text, re.I), (where, text)
        rest = text.replace("pin 1-2-3", "").replace("pin 1", "")
        for token in re.findall(r"[\w-]*\d[\w-]*", rest):
            assert token in allowed, (where, token)


def test_danger_hints_cover_elko_battery_laser_mains():
    danger = {(where, h["code"]) for where, h in _hints() if h["severity"] == "danger"}
    assert ("electrolytic", "polarity") in danger
    assert ("battery", "battery_safety") in danger
    assert ("text_rules", "laser_safety") in danger
    assert ("text_rules", "battery_safety") in danger
    assert ("text_rules", "low_voltage_only") in danger


def test_rules_cover_the_required_prefixes():
    want = {"R": "resistor", "C": "capacitor", "D": "diode", "LED": "led", "Q": "transistor", "U": "ic", "J": "connector",
            "SW": "switch", "F": "fuse", "L": "inductor", "Y": "crystal", "BZ": "buzzer", "RV": "potentiometer",
            "TP": "test_point"}
    prefixes = RULES["classify"]["prefixes"]
    assert {p: prefixes[p] for p in want} == want
    known = set(bom.kinds())
    assert set(prefixes.values()) <= known


def test_kinds_are_unique_and_well_formed():
    kinds = [k["kind"] for k in RULES["kinds"]]
    assert len(kinds) == len(set(kinds))
    for k in RULES["kinds"]:
        assert isinstance(k["mechanical"], bool) and str(k["height_class"]) in RULES["order"]["height_classes"]
        assert str(k["sensitivity"]) in RULES["order"]["sensitivity"]
        assert "{what}" in k["action"] and len(k["label"]) == 2
        for h in k["hints"]:
            assert h["severity"] in ("info", "caution", "danger")


def test_text_rule_patterns():
    rules = {r["code"]: re.compile(r["pattern"], re.I) for r in RULES["text_rules"]}
    assert rules["laser_safety"].search("Laser module KY-008")
    assert not rules["laser_safety"].search("Lasergate")
    assert rules["battery_safety"].search("LiPo 3.7 V") and rules["battery_safety"].search("CR2032 holder")
    assert rules["battery_safety"].search("Li-Ion 18650")
    assert rules["low_voltage_only"].search("230 V relay") and rules["low_voltage_only"].search("mains")
    assert not rules["low_voltage_only"].search("Netzteil 5 V")

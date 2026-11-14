"""Tool texts survive tool_search's 500-character clip and tell where the sim panic comes from."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from circuit_bench import schemas

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "circuit_bench" / "skills" / "esp32-bench" / "SKILL.md"
TOOL_SEARCH_CLIP = 500  # hermes-agent tools/tool_search.py _clip_description(cap=500)


@pytest.mark.parametrize("schema", schemas.ALL, ids=lambda s: s["name"])
def test_description_is_not_clipped_by_tool_search(schema):
    assert len(schema["description"]) <= TOOL_SEARCH_CLIP, len(schema["description"])


def test_schema_cost_and_description_length_did_not_grow():
    # budgets of the module support; the ratchet on the measured values lives in
    # tests/test_m0_api_schemas.py
    assert len(json.dumps(list(schemas.ALL))) <= 10000
    assert sum(len(s["description"]) for s in schemas.ALL) <= 2800


def test_sim_texts_point_to_the_demo_firmware():
    assert "bench_project demo" in schemas.BOARD["description"]
    assert "emulates only the demo firmware" in schemas.BOARD["description"]
    text = schemas.PROJECT["description"]
    assert "laser-trigger" in text and "crashes on purpose" in text and "unchanged" in text
    skill = SKILL.read_text(encoding="utf-8")
    for needle in ("sim_not_demo_firmware", "rom_boot_only", "returns it unchanged", "not emulated", "forced_beta",
                   "allocation"):
        assert needle in skill, needle
    # the answer for an existing demo project does not say whether its firmware was fixed: the skill has to
    assert "returns it unchanged (maybe fixed)" in skill

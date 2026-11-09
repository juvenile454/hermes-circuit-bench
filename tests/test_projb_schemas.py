"""Tool schemas: cost, descriptions, no $ref/$defs, sanitizer-proof shape, vocabularies."""
import json

import pytest

from circuit_bench import schemas, tools
from circuit_bench.bench_core import calc, calckit, contracts, modspec, schematic


def _nodes(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _nodes(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _nodes(v, f"{path}[{i}]")


def test_cost_below_budget():
    cost = len(json.dumps(list(schemas.ALL)))
    assert cost <= 10000, cost  # ceiling; ratchet: tests/test_m0_api_schemas.py


def test_seven_tools_with_contract_names():
    assert schemas.NAMES == ("bench_project", "bench_pins", "bench_calc", "bench_schematic", "bench_solder",
                             "bench_board", "bench_crash")
    assert set(schemas.EMOJI) == set(schemas.NAMES)


@pytest.mark.parametrize("schema", schemas.ALL, ids=lambda s: s["name"])
def test_description_ends_with_the_contract_sentence(schema):
    assert schema["description"].endswith("Only report checks listed as passed; cite the returned sources.")
    assert len(schema["description"]) < 600


@pytest.mark.parametrize("schema", schemas.ALL, ids=lambda s: s["name"])
def test_plain_json_schema(schema):
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and "definitions" not in text
    params = schema["parameters"]
    assert params["type"] == "object" and params["required"] == ["action"]
    assert not {"anyOf", "oneOf", "allOf", "enum", "not"} & set(params)  # no top-level combinators
    for path, node in _nodes(params):
        assert not isinstance(node.get("type"), list), path  # unions only as anyOf
        if node.get("type") == "object":
            assert isinstance(node.get("properties"), dict), path
            assert isinstance(node.get("required"), list), path
            assert set(node["required"]) <= set(node["properties"]), path
        if "oneOf" in node or "allOf" in node:
            pytest.fail(f"{path}: use anyOf")


def test_action_enums_match_the_contract():
    actions = {s["name"]: s["parameters"]["properties"]["action"]["enum"] for s in schemas.ALL}
    assert actions == {
        "bench_project": ["create", "get", "list", "set_board", "assign", "unassign", "set_firmware", "add_parts",
                          "remove_parts", "note", "add_module", "connect", "set_rails", "demo"],
        "bench_pins": ["check", "suggest", "info", "modules", "module"],
        "bench_calc": [*calckit.kinds(), "list"],  # the register (basics first, then calcs/*.py), plus list
        "bench_schematic": ["render"],
        "bench_solder": ["plan", "step"],
        "bench_board": ["ports", "detect", "build", "flash", "monitor"],
        "bench_crash": ["decode"],
    }


def test_vocabularies_follow_bench_core():
    assert tuple(schemas.MODES) == contracts.MODES
    assert tuple(schemas.BLOCKS) == schematic.BLOCKS
    assert tuple(schemas.CALCS) == tuple(calc.CALCULATORS) == calckit.kinds()
    assert schemas.CALCS[:6] == list(modspec.BASIC_CALCS)


def test_calc_list_names_every_input():
    """bench_calc action=list names every input of every calculator; the description
    names the basic calculators and points to list."""
    text = schemas.CALC["description"]
    for kind in modspec.BASIC_CALCS:
        assert kind in text
    assert "list" in text
    env = json.loads(tools.make_handlers(tools.Host())["bench_calc"]({"action": "list"}))
    listed = {c["kind"]: c["inputs"] for c in env["result"]["calculators"]}
    assert list(listed) == list(calckit.kinds())
    for kind, params in calc.PARAMS.items():
        for name, *_ in params:
            assert name in listed[kind], (kind, name)


def test_schematic_description_names_required_params():
    text = schemas.SCHEMATIC["description"]
    for block, params in schematic.PARAMS.items():
        assert block in text
        for p in params:
            if p.required:
                assert p.name in text, (block, p.name)


def test_contract_parameters_present():
    props = {s["name"]: set(s["parameters"]["properties"]) for s in schemas.ALL}
    assert {"id", "chip", "variant", "devkit", "wifi", "assignments", "firmware_dir", "env", "parts"} <= props["bench_project"]
    assert {"chip", "variant", "wifi", "devkit", "assignments", "project", "requests", "pin"} <= props["bench_pins"]
    assert {"project"} <= props["bench_calc"]
    assert {"block", "params", "project", "out_dir"} <= props["bench_schematic"]
    assert {"bom", "project", "step_id", "done"} <= props["bench_solder"]
    assert {"port", "project", "project_dir", "env", "seconds", "baud"} <= props["bench_board"]
    assert {"log", "elf", "chip", "project"} <= props["bench_crash"]


def test_board_text_discloses_what_build_runs():
    """No "offline" promise; build runs the project's scripts and may download platforms."""
    text = schemas.BOARD["description"]
    assert "offline" not in text
    assert "no upload" in text and "project's PlatformIO scripts" in text and "may download platforms" in text
    assert "elf_sha256" in schemas.BOARD["parameters"]["properties"]

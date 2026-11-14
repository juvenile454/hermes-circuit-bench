"""Hints that tell the user how to continue after an error."""
import pytest
from test_api_support import api  # noqa: F401 - fixture

from circuit_bench.bench_core import boards, pins, project
from circuit_bench.bench_core.contracts import BenchError

LEAVE_OUT = "or leave devkit out: the chip checks still run, pins.broken_out and pins.board are skipped"


def test_unknown_board_hint_lists_boards_and_names_the_way_out():
    with pytest.raises(BenchError) as e:
        boards.load("nope")
    assert e.value.code == "unknown_board"
    assert e.value.message == "unknown board 'nope'"
    assert e.value.hint == f"known boards: {', '.join(boards.ids())}; {LEAVE_OUT}"
    assert len(boards.ids()) >= 7


def test_unknown_board_hint_reaches_the_pin_check_error():
    res = pins.check("esp32s3", [{"mode": "out", "pin": 1}], devkit="nope")
    assert res["ok"] is False and res["error"]["code"] == "unknown_board"
    assert res["error"]["hint"].endswith(LEAVE_OUT)


def test_leaving_devkit_out_does_what_the_hint_says():
    res = pins.check("esp32s3", [{"mode": "out", "pin": 1}])
    assert res["ok"] is True
    by_id = {c["id"]: c["status"] for c in res["checks"]}
    assert by_id["pins.broken_out"] == "skipped" and by_id["pins.board"] == "skipped"
    others = {k: v for k, v in by_id.items() if k not in ("pins.broken_out", "pins.board")}
    assert others and all(v != "skipped" for v in others.values()), by_id


@pytest.mark.parametrize("bad", ["../boards/x", ".hidden", ""])
def test_malformed_board_id_keeps_the_short_message_without_a_hint(bad):
    with pytest.raises(BenchError) as e:
        boards.load(bad)
    assert e.value.code == "unknown_board" and e.value.hint is None


def test_board_asked_for_by_id_gets_no_leave_devkit_out_advice():
    """Where the board is the thing asked for (the board layout), devkit cannot be left out."""
    with pytest.raises(BenchError) as e:
        boards.layout("nope")
    assert e.value.code == "unknown_board" and e.value.message == "unknown board 'nope'"
    assert e.value.hint == f"known boards: {', '.join(boards.ids())}"
    assert "leave devkit out" not in e.value.hint
    with pytest.raises(BenchError) as again:  # the advice stays where devkit is optional
        boards.load("nope")
    assert again.value.hint.endswith(LEAVE_OUT)


def test_board_route_hint_lists_boards_only(api):  # noqa: F811
    body = api.err(api.get("/boards/nope"), 400, "unknown_board")
    assert body["error"]["hint"] == f"known boards: {', '.join(boards.ids())}"


def test_project_create_still_says_devkit_can_be_left_out():
    """devkit is optional for a project, so the way out stays in the hint there."""
    res = project.create("hint-bench", "T", "esp32s3", "n16r8", "nope")
    assert res["ok"] is False and res["error"]["code"] == "unknown_board"
    assert res["error"]["hint"].endswith(LEAVE_OUT)

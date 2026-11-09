"""The ``drawing`` block of the board layouts.

* Contract: ``boards.drawing_problems`` accepts every committed block and rejects the broken variants below.
* ``layout()`` passes the block through unchanged; boards without it answer without the key.
* Citations (marker corpus): every quote is a verbatim substring of a text file pinned for its source_id; a figure is
  the file name of a pinned image of the same source_id; module_size_mm quotes are checked the same way.
* Every source_id is a known source.
"""
import copy
import json
from pathlib import Path

import pytest

from circuit_bench.bench_core import boards, sources

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / ".corpus"
FILES: dict[str, list[dict]] = {}
for _name in ("boards", "pins", "wt32", "visual"):
    for _e in json.loads((ROOT / "tests" / "corpus" / f"{_name}.json").read_text(encoding="utf-8"))["files"]:
        FILES.setdefault(_e["source_id"], []).append(_e)
WITH_DRAWING = [b for b in boards.ids() if "drawing" in boards.load(b)]


def _excerpt_lines(entry: dict) -> str:
    out, inside = [], False
    for line in (ROOT / "tests" / "corpus" / entry["excerpt"]).read_text(encoding="utf-8").split("\n"):
        if line.startswith("@@ "):
            inside = True
        elif inside and line:
            out.append(line)
    return "\n".join(out)


def _texts(source_id: str) -> list[str]:
    out = []
    for e in FILES.get(source_id, []):
        if e.get("excerpt"):
            out.append(_excerpt_lines(e))
        elif not e["path"].endswith((".png", ".jpg", ".pdf", ".html")) and (CORPUS / e["path"]).is_file():
            out.append((CORPUS / e["path"]).read_text(encoding="utf-8"))
    return out


def _cited(d: dict):
    yield from d["parts"]
    if "module_size_mm" in d:
        yield d["module_size_mm"]


def test_s3_pilot_has_a_drawing():
    assert "esp32-s3-devkitc-1" in WITH_DRAWING


@pytest.mark.parametrize("board_id", WITH_DRAWING)
def test_drawing_contract(board_id):
    assert boards.drawing_problems(boards.load(board_id)) == []


@pytest.mark.parametrize("board_id", boards.ids())
def test_layout_passes_drawing_through(board_id):
    b, lay = boards.load(board_id), boards.layout(board_id)
    assert lay.get("drawing") == b.get("drawing")
    assert ("drawing" in lay) == ("drawing" in b)


@pytest.mark.parametrize("board_id", WITH_DRAWING)
def test_drawing_sources_are_known(board_id):
    for item in _cited(boards.load(board_id)["drawing"]):
        assert sources.get(item["source_id"]), item


def _broken(mutate):
    b = boards.load("esp32-s3-devkitc-1")
    mutate(b["drawing"])
    return boards.drawing_problems(b)


@pytest.mark.parametrize("mutate, word", [
    (lambda d: d.update(extra=1), "unknown keys"),
    (lambda d: d.update(schema=2), "schema 1"),
    (lambda d: d["parts"][0].update(kind="laser"), "kind"),
    (lambda d: d["parts"][0].pop("quote"), "quote"),
    (lambda d: d["parts"][0].update(connector="lightning"), "connector"),
    (lambda d: d["parts"][2].update(connector="usb_c"), "connector only"),
    (lambda d: d["parts"][0].update(zone="middle"), "exactly one"),
    (lambda d: d["parts"][0].pop("order"), "order"),
    (lambda d: d["parts"][1].update(order=1), "duplicate"),
    (lambda d: d["parts"][0].update(ref="JTAG"), "usb[].label"),
    (lambda d: d["parts"][5].update(gpio=48), "onboard[].gpio"),
    (lambda d: d["parts"][2].update(zone="top"), "zone"),
    (lambda d: d["parts"][2].pop("note"), "figure and note"),
    (lambda d: d["parts"][2].pop("label"), "label required"),
    (lambda d: d.update(module_size_mm={"w": 18}), "module_size_mm"),
])
def test_drawing_contract_rejects(mutate, word):
    problems = _broken(mutate)
    assert any(word in p for p in problems), problems


def test_buttons_must_match_the_board_buttons():
    b = copy.deepcopy(boards.load("esp32-s3-devkitc-1"))
    b["buttons"] = ["Boot"]
    assert any("buttons" in p for p in boards.drawing_problems(b))


_missing = sorted({e["path"] for b in WITH_DRAWING for item in _cited(boards.load(b)["drawing"])
                   for e in FILES.get(item["source_id"], []) if not e.get("excerpt") and not (CORPUS / e["path"]).is_file()})


@pytest.mark.corpus
@pytest.mark.skipif(bool(_missing), reason=f"corpus missing ({len(_missing)} files): scripts/fetch_corpus.py")
@pytest.mark.parametrize("board_id", WITH_DRAWING)
def test_drawing_quotes_and_figures_are_pinned(board_id):
    for item in _cited(boards.load(board_id)["drawing"]):
        texts = _texts(item["source_id"])
        assert texts and any(item["quote"] in t for t in texts), item
        if item.get("figure"):
            pinned = [Path(e["path"]).name for e in FILES[item["source_id"]] if e["path"].endswith((".png", ".jpg"))]
            pinned += [Path(e.get("excerpt", "")).name for e in FILES[item["source_id"]]]
            assert item["figure"] in pinned or any(item["figure"] in e.get("figure", "") for e in FILES[item["source_id"]]), item

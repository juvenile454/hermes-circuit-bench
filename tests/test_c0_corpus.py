"""Chip corpus entries and their committed excerpts.

* every manifest entry has a source in data/sources/;
* every excerpt ('#' metadata, '@@ page N' / '@@ html' segments) names the pinned file and its SHA-256, and,
  with the corpus present, every segment line is found in order (whitespace-insensitive) in that page or HTML text.

Excerpts: every tests/corpus/excerpts/*.txt with a '# source_id' header except calc-*.txt (tests/test_calc_sources.py
and tests/test_plus_calc_sources.py check those): the chip files, and automatically all others
(esp-*-dc.txt of the chip electrical data, mod-*.txt of the module families). Parser and PDF text cache: tests/excerpts.py.
"""
import hashlib
import html.parser
import re
from pathlib import Path

import pytest

import excerpts as ex
from circuit_bench.bench_core import sources

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ex.CORPUS
MANIFESTS = ex.MANIFESTS
EXCERPTS = [(e.source_id, e.name) for e in ex.excerpts() if not e.name.startswith("calc-")]
CHIPS_EXCERPTS = {  # the chip excerpts must stay covered (the glob above finds them)
    "ds-esp32-c6-wroom-1": "esp32-c6-wroom-1-datasheet-v1.4.txt",
    "ds-esp32-c6-mini-1": "esp32-c6-mini-1-datasheet-v1.5.txt",
    "ds-wt32-eth01-v1.4": "wt32-eth01-datasheet-v1.4.txt",
    "sch-wt32-eth01-v1.4": "wt32-eth01-schematic-v1.4.txt",
    "wiki-wt32-eth01-features": "wt32-eth01-wiki-board-features.txt",
    "wiki-wt32-eth01-resources": "wt32-eth01-wiki-board-resources.txt",
}


def entries() -> list[dict]:
    return [e for _, e in ex.manifest_entries(MANIFESTS)]


def excerpt(name: str) -> tuple[dict[str, str], list[tuple[str, list[str]]]]:
    e = ex.parse(name)
    return e.meta, e.segments


class _Text(html.parser.HTMLParser):
    BLOCK = {"p", "li", "tr", "h1", "h2", "h3", "h4", "div", "br", "td", "th", "table"}

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    return "".join(p.out)


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def test_every_manifest_entry_has_a_source():
    known = sources.all_sources()
    for e in entries():
        if e.get("source_id"):
            assert e["source_id"] in known, e["path"]


def test_the_chips_excerpts_are_covered():
    assert set(CHIPS_EXCERPTS.items()) <= set(EXCERPTS)
    assert all(sources.get(sid)["retrieved"] == "2026-11-06" for sid in CHIPS_EXCERPTS)


@pytest.mark.parametrize(("sid", "name"), EXCERPTS, ids=[n for _, n in EXCERPTS])
def test_excerpt_metadata_matches_the_manifest(sid, name):
    meta, segs = excerpt(name)
    assert meta["source_id"] == sid and meta["retrieved"] == sources.get(sid)["retrieved"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["retrieved"])
    candidates = [e for e in entries() if e.get("source_id") == sid]
    [e] = ([c for c in candidates if c.get("excerpt") == f"excerpts/{name}"] or candidates)[:1]
    assert e["excerpt"] == f"excerpts/{name}" and meta["url"] == e["url"]
    assert meta["corpus"] == f"{e['path']} sha256 {e['sha256']}"
    assert segs and all(lines for _, lines in segs)


@pytest.mark.corpus
@pytest.mark.parametrize(("sid", "name"), EXCERPTS, ids=[n for _, n in EXCERPTS])
def test_excerpt_lines_are_in_the_pinned_file(sid, name):
    meta, segs = excerpt(name)
    path, sha = meta["corpus"].split(" sha256 ")
    target = CORPUS / path
    if not target.is_file():
        pytest.skip(f"corpus file missing: {path} (scripts/fetch_corpus.py)")
    data = target.read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha
    text = None
    if path.endswith(".pdf"):
        pytest.importorskip("pypdf")  # dev tool only
        text = ex.PdfText(target, sha)  # pypdf page text through the cache tests/.corpus/.text/<sha>.json
    for label, lines in segs:
        if label == "html":
            hay = squash(html_text(data.decode("utf-8")))
        else:
            m = re.fullmatch(r"page (\d+)", label)
            assert m and text is not None, label
            hay = squash(text.text(int(m.group(1))))
        pos = 0
        for line in lines:
            found = hay.find(squash(line), pos)
            assert found >= 0, f"{name} {label}: {line!r} not found after offset {pos}"
            pos = found + len(squash(line))

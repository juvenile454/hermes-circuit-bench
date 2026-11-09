"""Generic checks of every data/modules/*.json and loader tests on synthetic entries. Every module family's data
must pass them.

Checks on the real data (each a loop over all files; an empty data/modules/ is fine):
1. loader: ``Catalog.from_dir(data/modules).problems == []`` (file shape, schema, wp == file name, every entry by
   ``modules.validate_module``, ids and aliases unique across all files);
2. prefixes: a module of ``<wp>.json`` cites only sources ``mod-<wp>-…`` defined in ``data/sources/mod-<wp>.json``;
3. evidence: every quoted item (F, requires, hazards, notes with ``evidence``) quotes its source's excerpt on the
   given page verbatim: a string is part of one excerpt line of a ``@@ page N`` segment, a list are parts of lines
   of one such segment in this order (gaps allowed);
4. excerpts ``mod-<wp>-<part>.txt``: header (source_id, document, url, corpus, retrieved, extracted) ↔ source
   (url, retrieved, sha256 in the note) ↔ manifest ``tests/corpus/mod-<wp>.json`` (path under mod/<wp>/, sha256,
   url, source_id, excerpt); segments ``page N`` (or ``html``) and not empty;
5. manifests ``mod-<wp>.json``: entries {url, path, sha256, source_id, excerpt?, note?}, https URL, path under
   mod/<wp>/ and unique, pinned sha256, the source exists in mod-<wp>.json, the excerpt exists and names that source;
6. sources ``mod-<wp>.json``: loadable by sources.load_dir (class required, id prefix), A2 titles say
   "copy hosted by", A1 URLs are web.archive.org ``id_`` snapshots, a source with a manifest entry names its sha256.
The tree-level checks run once more on a synthetic tree in tmp_path (valid, then one defect at a time).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import excerpts as ex
from circuit_bench.bench_core import modspec as ms
from circuit_bench.bench_core import modules, sources
from circuit_bench.bench_core.contracts import BenchError

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Tree:
    modules_dir: Path
    sources_dir: Path
    excerpts_dir: Path
    manifests_dir: Path


REPO = Tree(modules.MODULES_DIR, sources.SOURCES_DIR, ex.EXCERPTS, ex.MANIFESTS)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


# --- tree-level checks (used on the repo and on synthetic trees) ---------------------------------------------------
def module_files(tree: Tree) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for p in sorted(tree.modules_dir.glob("*.json")) if tree.modules_dir.is_dir() else []:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue  # reported by the loader
        if isinstance(doc, dict) and isinstance(doc.get("modules"), list):
            out.append((p.stem, doc))
    return out


def all_sources(tree: Tree) -> dict[str, dict[str, Any]]:
    return sources.load_dir(tree.sources_dir)


def mod_source_files(tree: Tree) -> dict[str, list[dict[str, Any]]]:
    """wp -> entries of data/sources/mod-<wp>.json."""
    return {p.stem.removeprefix("mod-"): json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(tree.sources_dir.glob("mod-*.json"))}


def effective_entries(m: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [(m.get("id", "?"), m)]
    for v in m.get("variants") or []:
        if isinstance(v, dict) and isinstance(v.get("overrides"), dict):
            out.append((f"{m.get('id')}[{v.get('id')}]", modules.apply_variant(m, v)))
    return out


def quoted_items(obj: Any, where: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Every object with an ``evidence`` key below ``obj`` (F values, requires, hazards, notes)."""
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(obj, dict):
        if "evidence" in obj:
            out.append((where, obj))
        for k, v in obj.items():
            if k != "variants":
                out.extend(quoted_items(v, f"{where}.{k}" if where else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(quoted_items(v, f"{where}[{i}]"))
    return out


def check_loader(tree: Tree) -> list[str]:
    return list(modules.Catalog.from_dir(tree.modules_dir).problems)


def check_prefixes(tree: Tree) -> list[str]:
    defined = {wp: {s.get("id") for s in entries} for wp, entries in mod_source_files(tree).items()}
    out = []
    for wp, doc in module_files(tree):
        for m in doc["modules"]:
            for _, eff in effective_entries(m):
                for sid in eff.get("source_ids") or []:
                    if not str(sid).startswith(f"{ms.SOURCE_PREFIX}{wp}-"):
                        out.append(f"{wp}.json: {m.get('id')}: source {sid!r} must start with mod-{wp}-")
                    elif sid not in defined.get(wp, set()):
                        out.append(f"{wp}.json: {m.get('id')}: source {sid!r} is not defined in "
                                   f"data/sources/mod-{wp}.json")
    return sorted(set(out))


def check_evidence(tree: Tree) -> list[str]:
    by_source = ex.by_source("*.txt", tree.excerpts_dir)
    out = []
    for wp, doc in module_files(tree):
        for m in doc["modules"]:
            for label, eff in effective_entries(m):
                sids = eff.get("source_ids") or []
                for where, item in quoted_items(eff):
                    parts = modules.evidence_parts(item.get("evidence"))
                    sid = item.get("source_id") or (sids[0] if len(sids) == 1 else None)
                    page = item.get("page")
                    if parts is None or sid is None or not isinstance(page, int):
                        continue  # malformed: reported by the loader
                    head = f"{wp}.json: {label}: {where}"
                    if sid not in by_source:
                        out.append(f"{head}: no excerpt with '# source_id: {sid}' in tests/corpus/excerpts/")
                        continue
                    segs = [seg for e in by_source[sid] for seg in e.page_segments(page)]
                    if not segs:
                        out.append(f"{head}: the excerpt of {sid} has no '@@ page {page}' segment")
                    elif not any(ex.find_parts_in_order(parts, seg) for seg in segs):
                        out.append(f"{head}: evidence {item['evidence']!r} is not on page {page} of the excerpt "
                                   f"of {sid} (verbatim part of a line; list parts in order)")
    return sorted(set(out))


def _manifest(tree: Tree, wp: str) -> dict[str, Any] | None:
    p = tree.manifests_dir / f"mod-{wp}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def check_excerpts(tree: Tree) -> list[str]:
    srcs = all_sources(tree)
    out = []
    for p in sorted(tree.excerpts_dir.glob("mod-*.txt")):
        e = ex.parse(p)
        name = p.name
        m = re.fullmatch(r"mod-(n?[a-z]{2,12})-[a-z0-9][a-z0-9_.-]*\.txt", name)
        if not m:
            out.append(f"{name}: name must be mod-<wp>-<part>.txt")
            continue
        wp = m.group(1)
        missing = [k for k in ("source_id", "document", "url", "corpus", "retrieved", "extracted") if not e.meta.get(k)]
        if missing:
            out.append(f"{name}: header lines missing: {missing}")
            continue
        sid = e.meta["source_id"]
        if not sid.startswith(f"mod-{wp}-"):
            out.append(f"{name}: source_id {sid!r} must start with mod-{wp}-")
        src = srcs.get(sid)
        if src is None:
            out.append(f"{name}: unknown source {sid!r}")
            continue
        corpus = e.corpus()
        if corpus is None:
            out.append(f"{name}: corpus must be '<path> sha256 <64 hex>'")
            continue
        path, sha = corpus
        if not path.startswith(f"mod/{wp}/"):
            out.append(f"{name}: corpus path {path!r} must be under mod/{wp}/")
        if e.meta["url"].split(" ")[0] != src["url"]:
            out.append(f"{name}: url differs from the source's url {src['url']!r}")
        if e.meta["retrieved"] != src["retrieved"]:
            out.append(f"{name}: retrieved differs from the source ({src['retrieved']})")
        if f"sha256 {sha}" not in src.get("note", ""):
            out.append(f"{name}: the source note must name 'sha256 {sha}'")
        if not e.meta["extracted"].startswith("pypdf ") and not any(lab == "html" for lab, _ in e.segments):
            out.append(f"{name}: extracted must name the pypdf version ('pypdf 6.21.4, …')")
        if not e.segments or not all(seg for _, seg in e.segments):
            out.append(f"{name}: needs non-empty '@@ page N' segments")
        bad = [lab for lab, _ in e.segments if not (ex.PAGE_LABEL.fullmatch(lab) or lab == "html")]
        if bad:
            out.append(f"{name}: segment labels must be 'page N' or 'html', got {bad}")
        man = _manifest(tree, wp)
        entry = next((f for f in (man or {}).get("files", []) if f.get("path") == path), None)
        if entry is None:
            out.append(f"{name}: {path} is not in tests/corpus/mod-{wp}.json")
            continue
        if entry.get("sha256") != sha:
            out.append(f"{name}: sha256 differs from the manifest")
        if entry.get("url") != src["url"]:
            out.append(f"{name}: manifest url differs from the source's url")
        if entry.get("source_id") != sid:
            out.append(f"{name}: manifest source_id {entry.get('source_id')!r} differs")
        if entry.get("excerpt") != f"excerpts/{name}":
            out.append(f"{name}: manifest excerpt must be 'excerpts/{name}'")
    return out


MANIFEST_KEYS = {"url", "path", "sha256", "source_id", "excerpt", "note"}


def check_manifests(tree: Tree) -> list[str]:
    defined = {wp: {s.get("id") for s in entries} for wp, entries in mod_source_files(tree).items()}
    out = []
    for p in sorted(tree.manifests_dir.glob("mod-*.json")):
        wp = p.stem.removeprefix("mod-")
        name = p.name
        if not ms.WP_RE.fullmatch(wp):
            out.append(f"{name}: work package name {wp!r} does not match {ms.WP_RE.pattern}")
        if wp not in defined:
            out.append(f"{name}: data/sources/mod-{wp}.json is missing")
        doc = json.loads(p.read_text(encoding="utf-8"))
        files = doc.get("files") if isinstance(doc, dict) else None
        if not isinstance(files, list):
            out.append(f"{name}: expected {{'files': [...]}}")
            continue
        seen: set[str] = set()
        for i, f in enumerate(files):
            where = f"{name}: files[{i}]"
            if not isinstance(f, dict) or set(f) - MANIFEST_KEYS or not {"url", "path", "sha256", "source_id"} <= set(f):
                out.append(f"{where}: keys must be url, path, sha256, source_id (+ excerpt, note)")
                continue
            if not str(f["url"]).startswith("https://"):
                out.append(f"{where}: url must be https")
            parts = Path(f["path"]).parts
            if parts[:2] != ("mod", wp) or len(parts) < 3 or ".." in parts:
                out.append(f"{where}: path {f['path']!r} must be under mod/{wp}/")
            if f["path"] in seen:
                out.append(f"{where}: duplicate path {f['path']!r}")
            seen.add(f["path"])
            if not SHA_RE.fullmatch(str(f["sha256"])):
                out.append(f"{where}: sha256 must be pinned (scripts/fetch_corpus.py --pin mod-{wp})")
            if f["source_id"] not in defined.get(wp, set()):
                out.append(f"{where}: source {f['source_id']!r} is not in data/sources/mod-{wp}.json")
            if "excerpt" in f:
                xp = tree.manifests_dir / f["excerpt"]
                if not xp.is_file():
                    out.append(f"{where}: excerpt {f['excerpt']!r} does not exist")
                elif ex.parse(xp).source_id != f["source_id"]:
                    out.append(f"{where}: excerpt {f['excerpt']!r} names another source")
    return out


def check_sources(tree: Tree) -> list[str]:
    try:
        all_sources(tree)
    except ValueError as e:
        return [f"sources: {e}"]
    out = []
    for wp, entries in mod_source_files(tree).items():
        man = _manifest(tree, wp) or {}
        pinned = {f.get("source_id"): f.get("sha256") for f in man.get("files", []) if isinstance(f, dict)}
        for s in entries:
            sid = s["id"]
            if s["class"] == "A2" and "copy hosted by" not in s["title"]:
                out.append(f"mod-{wp}.json: {sid}: an A2 title says '…, copy hosted by <third party>'")
            if s["class"] == "A1" and not re.match(r"^https://web\.archive\.org/web/\d+id_/https?://", s["url"]):
                out.append(f"mod-{wp}.json: {sid}: an A1 url is https://web.archive.org/web/<ts>id_/<manufacturer url>")
            if pinned.get(sid) and f"sha256 {pinned[sid]}" not in s.get("note", ""):
                out.append(f"mod-{wp}.json: {sid}: note must name 'sha256 {pinned[sid]}' (the pinned file)")
    return out


CHECKS = (check_loader, check_prefixes, check_evidence, check_excerpts, check_manifests, check_sources)


def run_check(check, tree: Tree) -> list[str]:
    try:
        return check(tree)
    except ValueError as e:  # a malformed data/sources file stops the source loader
        return [f"{check.__name__}: {e}"]


def check_all(tree: Tree) -> list[str]:
    return [p for c in CHECKS for p in run_check(c, tree)]


# --- the real data -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("check", CHECKS, ids=[c.__name__ for c in CHECKS])
def test_module_data(check):
    assert run_check(check, REPO) == []


def test_runtime_catalog_has_no_problems():
    modules.clear_cache()
    cat = modules.catalog()
    assert cat.problems == []
    assert cat.families() == sorted(wp for wp, _ in module_files(REPO))
    assert len(cat.ids()) == sum(len(doc["modules"]) for _, doc in module_files(REPO))
    for mid in cat.ids():
        e = cat.get(mid)
        assert e["_class"] in ms.SOURCE_CLASSES, mid
        for v in e.get("variants", []):
            cat.get(mid, v["id"])


def test_an_empty_catalog_is_fine(tmp_path):
    cat = modules.Catalog.from_dir(tmp_path / "absent")
    assert (cat.problems, cat.ids(), cat.families(), cat.categories()) == ([], [], [], [])
    assert cat.search() == {"total": 0, "items": []}
    empty = Tree(tmp_path / "m", tmp_path / "s", tmp_path / "x", tmp_path / "c")
    for d in (empty.modules_dir, empty.sources_dir, empty.excerpts_dir, empty.manifests_dir):
        d.mkdir()
    assert check_all(empty) == []


# --- synthetic tree: the checks accept a valid family and catch each defect ---------------------------------------
def F(value, unit="V", page=2, evidence="Supply voltage VDD 1.71 3.6 V", **kw):  # F = belegte Zahl
    return {"value": value, "unit": unit, "page": page, "evidence": evidence, **kw}


PAGES = {
    2: ["Table 1. Operating range", "Supply voltage VDD 1.71 1.8 3.6 V", "Interface supply VDDIO 1.2 1.8 3.6 V",
        "Absolute maximum VDD -0.3 4.25 V"],
    3: ["Input high level VIH VDDIO=1.2 V to 3.6 V 80   %VDDI", "O", "Input low level VIL 20 %VDDIO",
        "The 7-bit device address is 111011x. SDO to GND: 0x76, SDO to VDDIO: 0x77"],
    4: ["Current in normal mode 714 µA", "A 100 nF decoupling capacitor between VDD and GND is recommended"],
}


def module_entry(wp: str = "test") -> dict[str, Any]:
    ds = f"mod-{wp}-abc-ds"
    return {
        "id": "abc280", "aliases": ["gy-abc280"], "title": "ABC280 synthetic environment sensor",
        "category": "sensor.environment", "manufacturer": "Example Sensors", "kind": "module",
        "source_ids": [ds, f"mod-{wp}-abc-shop"],
        "supplies": {
            "VDD": {"min": F(1.71, evidence="Supply voltage VDD 1.71", source_id=ds),
                    "max": F(3.6, evidence="Supply voltage VDD 1.71 1.8 3.6 V", source_id=ds),
                    "abs_max": F(4.25, evidence="Absolute maximum VDD -0.3 4.25 V", source_id=ds)},
            "VDDIO": {"min": F(1.2, evidence="Interface supply VDDIO 1.2", source_id=ds),
                      "max": F(3.6, evidence="Interface supply VDDIO 1.2 1.8 3.6 V", source_id=ds)}},
        "io": {"domain": "VDDIO",
               "vih": {"rel": 0.8, "of": "VDDIO", "unit": "V", "page": 3, "source_id": ds,
                       "evidence": ["Input high level VIH", "80   %VDDI", "O"], "conditions": "VDDIO 1.2–3.6 V"},
               "vil": {"rel": 0.2, "of": "VDDIO", "unit": "V", "page": 3, "source_id": ds,
                       "evidence": "Input low level VIL 20 %VDDIO"},
               "outputs": "open_drain"},
        "pins": [{"name": "SDA", "signal": "i2c_sda"}, {"name": "SCL", "signal": "i2c_scl"},
                 {"name": "SDO", "signal": "addr_select", "must_connect": True},
                 {"name": "CSB", "signal": "mode_select", "tie": "VDDIO"},
                 {"name": "VDD", "signal": "supply"}, {"name": "VDDIO", "signal": "supply", "tie": "VDD"},
                 {"name": "GND", "signal": "gnd"}],
        "interfaces": [{"type": "i2c", "default": "0x76",
                        "addresses": {"value": ["0x76", "0x77"], "page": 3, "source_id": ds,
                                      "evidence": ["SDO to GND: 0x76", "SDO to VDDIO: 0x77"]},
                        "select": {"pin": "SDO", "map": {"GND": "0x76", "VDDIO": "0x77"}}}],
        "current": {"supply": "VDD", "max": F(0.000714, "A", 4, "Current in normal mode 714 µA", source_id=ds)},
        "requires": [{"code": "decoupling", "kind": "ceramic", "value": "100nF", "pins": ["VDD", "GND"], "page": 4,
                      "source_id": ds, "evidence": "A 100 nF decoupling capacitor between VDD and GND"}],
        "hazards": [],
        "variants": [{"id": "alt", "title": "ABC280 with SDO strapped high",
                      "overrides": {"interfaces": [{"type": "i2c", "default": "0x77",
                                                    "addresses": {"value": ["0x77"], "page": 3, "source_id": ds,
                                                                  "evidence": "SDO to VDDIO: 0x77"}}]}}],
        "notes": [{"text": "Breakouts often add a 3.3 V regulator and pull-ups.", "verified": False},
                  {"text": "Shop page lists the part as ABC280.", "page": 1, "source_id": f"mod-{wp}-abc-shop",
                   "evidence": "ABC280 breakout"}],
    }


def write_tree(root: Path, wp: str = "zz") -> Tree:
    tree = Tree(root / "modules", root / "sources", root / "corpus" / "excerpts", root / "corpus")
    for d in (tree.modules_dir, tree.sources_dir, tree.excerpts_dir):
        d.mkdir(parents=True)
    sha_ds, sha_shop = hashlib.sha256(b"ds").hexdigest(), hashlib.sha256(b"shop").hexdigest()
    srcs = [
        {"id": f"mod-{wp}-abc-ds", "title": "Example Sensors ABC280 datasheet, rev 1.0", "class": "A",
         "url": "https://example.com/abc280.pdf", "retrieved": "2026-11-08",
         "note": f"Document ABC-DS-001 rev 1.0. sha256 {sha_ds}"},
        {"id": f"mod-{wp}-abc-shop", "title": "Some shop, ABC280 breakout page", "class": "B",
         "url": "https://shop.example.net/abc280.pdf", "retrieved": "2026-11-08",
         "note": f"Retailer page. sha256 {sha_shop}"},
    ]
    (tree.sources_dir / f"mod-{wp}.json").write_text(json.dumps(srcs, ensure_ascii=False), encoding="utf-8")
    (tree.modules_dir / f"{wp}.json").write_text(json.dumps(
        {"schema": 1, "wp": wp, "note": "synthetic", "modules": [module_entry(wp)]}, ensure_ascii=False),
        encoding="utf-8")

    def excerpt(name, sid, url, path, sha, pages):
        head = [f"# source_id: {sid}", "# document: synthetic", f"# url: {url}", f"# corpus: {path} sha256 {sha}",
                "# retrieved: 2026-11-08", "# extracted: pypdf 6.21.4, PdfReader(pdf).pages[N - 1].extract_text()"]
        body = [x for n, lines in pages.items() for x in [f"@@ page {n}", *lines]]
        (tree.excerpts_dir / name).write_text("\n".join(head + body) + "\n", encoding="utf-8")

    excerpt(f"mod-{wp}-abc280.txt", srcs[0]["id"], srcs[0]["url"], f"mod/{wp}/abc280-ds.pdf", sha_ds, PAGES)
    excerpt(f"mod-{wp}-abc280-shop.txt", srcs[1]["id"], srcs[1]["url"], f"mod/{wp}/abc280-shop.pdf", sha_shop,
            {1: ["ABC280 breakout board"]})
    manifest = {"files": [
        {"url": srcs[0]["url"], "path": f"mod/{wp}/abc280-ds.pdf", "sha256": sha_ds, "source_id": srcs[0]["id"],
         "excerpt": f"excerpts/mod-{wp}-abc280.txt"},
        {"url": srcs[1]["url"], "path": f"mod/{wp}/abc280-shop.pdf", "sha256": sha_shop, "source_id": srcs[1]["id"],
         "excerpt": f"excerpts/mod-{wp}-abc280-shop.txt"}]}
    (tree.manifests_dir / f"mod-{wp}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tree


@pytest.fixture
def tree(tmp_path, monkeypatch):
    t = write_tree(tmp_path)
    monkeypatch.setattr(sources, "SOURCES_DIR", t.sources_dir)
    sources.clear_cache()
    yield t
    sources.clear_cache()


def _edit_json(path: Path, fn) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _edit_module(t: Tree, fn) -> None:
    _edit_json(t.modules_dir / "zz.json", lambda d: fn(d["modules"][0]))


def test_synthetic_tree_is_valid(tree):
    assert check_all(tree) == []
    cat = modules.Catalog.from_dir(tree.modules_dir)
    assert cat.ids() == ["abc280"] and cat.get("GY-ABC280")["_class"] == "A" and cat.get("abc280")["_wp"] == "zz"


def _replace_line(t: Tree, name: str, old: str, new: str) -> None:
    p = t.excerpts_dir / name
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


DEFECTS = {
    "evidence not in excerpt": (lambda t: _edit_module(t, lambda m: m["supplies"]["VDD"]["max"].update(
        evidence="Supply voltage VDD 1.71 1.8 3.7 V")), "is not on page 2"),
    "evidence on another page": (lambda t: _edit_module(t, lambda m: m["supplies"]["VDD"]["max"].update(page=3)),
                                 "is not on page 3"),
    "evidence list out of order": (lambda t: _edit_module(t, lambda m: m["io"]["vih"].update(
        evidence=["80   %VDDI", "Input high level VIH"])), "list parts in order"),
    "page without segment": (lambda t: _edit_module(t, lambda m: m["current"]["max"].update(page=9)),
                             "has no '@@ page 9' segment"),
    "excerpt missing": (lambda t: (t.excerpts_dir / "mod-zz-abc280-shop.txt").unlink(),
                        "no excerpt with '# source_id: mod-zz-abc-shop'"),
    "variant evidence": (lambda t: _edit_module(t, lambda m: m["variants"][0]["overrides"]["interfaces"][0][
        "addresses"].update(evidence="SDO to VDD: 0x77")), "abc280[alt]: interfaces[0].addresses"),
    "foreign source prefix": (lambda t: _edit_module(t, lambda m: m["source_ids"].append("mod-other-x")),
                              "must start with mod-zz-"),
    "header url": (lambda t: _replace_line(t, "mod-zz-abc280.txt", "# url: https://example.com/abc280.pdf",
                                           "# url: https://example.com/other.pdf"), "url differs"),
    "header retrieved": (lambda t: _replace_line(t, "mod-zz-abc280.txt", "# retrieved: 2026-11-08",
                                                 "# retrieved: 2026-11-07"), "retrieved differs"),
    "header extracted missing": (lambda t: _replace_line(t, "mod-zz-abc280.txt", "# extracted:", "# extract:"),
                                 "header lines missing: ['extracted']"),
    "header sha": (lambda t: _replace_line(t, "mod-zz-abc280.txt", "sha256 " + hashlib.sha256(b"ds").hexdigest(),
                                           "sha256 " + "0" * 64), "sha256 differs from the manifest"),
    "corpus path outside": (lambda t: _replace_line(t, "mod-zz-abc280.txt", "# corpus: mod/zz/", "# corpus: calc/"),
                            "must be under mod/zz/"),
    "manifest path outside": (lambda t: _edit_json(t.manifests_dir / "mod-zz.json", lambda d: d["files"][1].update(
        path="other/abc.pdf")), "path 'other/abc.pdf' must be under mod/zz/"),
    "manifest unpinned": (lambda t: _edit_json(t.manifests_dir / "mod-zz.json", lambda d: d["files"][1].update(
        sha256="")), "sha256 must be pinned"),
    "manifest unknown source": (lambda t: _edit_json(t.manifests_dir / "mod-zz.json", lambda d: d["files"][1].update(
        source_id="mod-zz-nope")), "is not in data/sources/mod-zz.json"),
    "note without sha": (lambda t: _edit_json(t.sources_dir / "mod-zz.json", lambda d: d[0].update(note="rev 1")),
                         "note must name 'sha256"),
    "A2 title": (lambda t: _edit_json(t.sources_dir / "mod-zz.json", lambda d: d[0].update(**{"class": "A2"})),
                 "copy hosted by"),
    "A1 url": (lambda t: _edit_json(t.sources_dir / "mod-zz.json", lambda d: d[0].update(**{"class": "A1"})),
               "web.archive.org"),
    "source without class": (lambda t: _edit_json(t.sources_dir / "mod-zz.json", lambda d: d[0].pop("class")),
                             "class is required"),
    "B backs a hard value": (lambda t: _edit_module(t, lambda m: m["supplies"]["VDD"]["min"].update(
        source_id="mod-zz-abc-shop")), "class B source 'mod-zz-abc-shop' cannot back a hard value"),
    "wp differs from file name": (lambda t: _edit_json(t.modules_dir / "zz.json", lambda d: d.update(wp="yy")),
                                  "differs from the file name"),
}


@pytest.mark.parametrize("defect", DEFECTS)
def test_synthetic_tree_defects_are_caught(tree, defect):
    mutate, expected = DEFECTS[defect]
    mutate(tree)
    sources.clear_cache()
    found = check_all(tree)
    assert any(expected in p for p in found), found


# --- loader on synthetic entries (Catalog.from_entries) -----------------------------------------------------------
SRC = {"mod-test-abc-ds": {"id": "mod-test-abc-ds", "class": "A"},
       "mod-test-abc-shop": {"id": "mod-test-abc-shop", "class": "B"},
       "mod-test-abc-copy": {"id": "mod-test-abc-copy", "class": "A2"}}


def cat_of(*entries, wp="test"):
    return modules.Catalog.from_entries(list(entries), sources=SRC, wp=wp)


def one(**top) -> dict[str, Any]:
    """A minimal valid entry with one source."""
    e = {"id": "xyz", "title": "XYZ test part", "category": "rtc", "manufacturer": "Example", "kind": "ic",
         "source_ids": ["mod-test-abc-ds"], "pins": [{"name": "VCC", "signal": "supply"}, {"name": "GND", "signal": "gnd"},
                                                    {"name": "DQ", "signal": "onewire"}]}
    e.update(top)
    return e


def test_valid_entries_load():
    cat = cat_of(module_entry(), one())
    assert cat.problems == []
    assert cat.ids() == ["abc280", "xyz"]


def _m(fn):
    def make():
        e = module_entry()
        fn(e)
        return e
    return make


def _sup(e, **f):
    e["supplies"]["VDD"]["max"].update(f)


ENTRY_DEFECTS = {
    "unknown key": (_m(lambda e: e.update(colour="red")), "unknown keys ['colour']"),
    "missing title": (_m(lambda e: e.pop("title")), "missing keys ['title']"),
    "bad id": (_m(lambda e: e.update(id="BME-280")), "id must match"),
    "bad alias": (_m(lambda e: e.update(aliases=["GY BME"])), "aliases must be"),
    "alias equals id": (_m(lambda e: e.update(aliases=["abc280"])), "differ from the id"),
    "bad category": (_m(lambda e: e.update(category="sensor.weather")), "category 'sensor.weather'"),
    "bad kind": (_m(lambda e: e.update(kind="board")), "kind 'board'"),
    "unknown source": (_m(lambda e: e["source_ids"].append("mod-test-nope")), "unknown source id 'mod-test-nope'"),
    "no sources": (_m(lambda e: e.update(source_ids=[])), "source_ids must be a non-empty list"),
    "weakest source first": (_m(lambda e: e.update(source_ids=["mod-test-abc-shop", "mod-test-abc-ds"])),
                             "source_ids[0] must be the strongest"),
    "signal outside list": (_m(lambda e: e["pins"][0].update(signal="data")), "signal 'data' not in"),
    "duplicate pin": (_m(lambda e: e["pins"].append({"name": "SDA", "signal": "i2c_sda"})), "duplicate pin name 'SDA'"),
    "unit not in list": (_m(lambda e: _sup(e, unit="mV")), "unit 'mV' not in"),
    "unit not SI for the field": (_m(lambda e: _sup(e, unit="A")), "unit must be 'V'"),
    "value and rel": (_m(lambda e: _sup(e, rel=0.5)), "exactly one of value / rel / rel_offset"),
    "rel in supplies": (_m(lambda e: e["supplies"]["VDD"].update(
        max={"rel": 1.0, "of": "VDD", "unit": "V", "page": 2, "evidence": "VDD", "source_id": "mod-test-abc-ds"})),
        "absolute value expected"),
    "rel without of": (_m(lambda e: e["io"]["vil"].pop("of")), "of must name a supply pin"),
    "of not a supply pin": (_m(lambda e: e["io"]["vil"].update(of="SDA")), "of must name a supply pin"),
    "of with value": (_m(lambda e: _sup(e, of="VDD")), "of is only allowed with rel"),
    "value not a number": (_m(lambda e: _sup(e, value="3.6")), "value must be a finite number"),
    "F without evidence": (_m(lambda e: (e["supplies"]["VDD"]["max"].pop("evidence"))), "evidence (line of the excerpt)"),
    "evidence empty list": (_m(lambda e: _sup(e, evidence=[])), "evidence must be a non-empty string"),
    "evidence wrong type": (_m(lambda e: _sup(e, evidence=36)), "evidence must be a non-empty string"),
    "page zero": (_m(lambda e: _sup(e, page=0)), "page must be a PDF page number"),
    "source_id needed": (_m(lambda e: e["supplies"]["VDD"]["max"].pop("source_id")), "source_id is required"),
    "source_id not cited": (_m(lambda e: _sup(e, source_id="mod-test-abc-copy")), "is not in the module's source_ids"),
    "B backs a value": (_m(lambda e: _sup(e, source_id="mod-test-abc-shop")), "cannot back a hard value"),
    "B backs a requirement": (_m(lambda e: e["requires"][0].update(source_id="mod-test-abc-shop")),
                              "cannot back a requirement"),
    "select pin unknown": (_m(lambda e: e["interfaces"][0]["select"].update(pin="ADDR")),
                           "select.pin 'ADDR' is not a pin"),
    "select pins unknown": (_m(lambda e: e["interfaces"][0].update(select={"pins": ["SDO", "ADDR"],
                                                                          "map": {"GND,GND": "0x76"}})),
                            "select.pins 'ADDR' is not a pin"),
    "select pins key arity": (_m(lambda e: e["interfaces"][0].update(select={"pins": ["SDO", "CSB"],
                                                                           "map": {"GND": "0x76"}})),
                              "needs one target per pin"),
    "select target unknown": (_m(lambda e: e["interfaces"][0]["select"]["map"].update(VDDIO="0x78")),
                              "target must be one of addresses"),
    "default unknown": (_m(lambda e: e["interfaces"][0].update(default="0x78")), "default '0x78' is not in addresses"),
    "address format": (_m(lambda e: e["interfaces"][0]["addresses"].update(value=["0x76", "0X77"])),
                       "distinct 7-bit addresses"),
    "addresses on spi": (_m(lambda e: e["interfaces"].append({"type": "spi", "default": "0x76"})),
                         "only allowed on i2c"),
    "interface type": (_m(lambda e: e["interfaces"][0].update(type="iic")), "type 'iic' not in"),
    "mux channels": (_m(lambda e: e["interfaces"][0].update(mux_channels=[["SD0", "SC0"]])), "mux_channels"),
    "spi mode": (_m(lambda e: e["interfaces"].append({"type": "spi", "mode": 4})), "SPI mode 0..3"),
    "supply key not a supply pin": (_m(lambda e: e["supplies"].update(SDA=e["supplies"]["VDD"])),
                                    "'SDA' is not a pin with signal 'supply'"),
    "supply range order": (_m(lambda e: e["supplies"]["VDD"]["min"].update(value=3.7)), "min <= typ <= max"),
    "io domain": (_m(lambda e: e["io"].update(domain="SDA")), "io.domain 'SDA'"),
    "io outputs": (_m(lambda e: e["io"].update(outputs="totem")), "io.outputs 'totem'"),
    "current supply": (_m(lambda e: e["current"].update(supply="VBAT")), "current.supply 'VBAT'"),
    "current unit": (_m(lambda e: e["current"]["max"].update(unit="V")), "unit must be 'A'"),
    "internal pull": (_m(lambda e: e["pins"][0].update(internal_pull="weak")), "internal_pull must be"),
    "require code": (_m(lambda e: e["requires"][0].update(code="cap")), "code 'cap' not in"),
    "require pins": (_m(lambda e: e["requires"][0].update(pins=["VCC"])), "pins must name pins of the module"),
    "require without evidence": (_m(lambda e: [e["requires"][0].pop(k) for k in ("evidence", "page", "source_id")]),
                                 "evidence (line of the excerpt) and page are required"),
    "hazard code": (_m(lambda e: e["hazards"].append({"code": "fire", "text": "Hot."})), "code 'fire' not in"),
    "hazard text": (_m(lambda e: e["hazards"].append({"code": "heat"})), "text (English) is required"),
    "note unverified missing": (_m(lambda e: e["notes"][0].pop("verified")), "needs \"verified\": false"),
    "note verified without evidence": (_m(lambda e: e["notes"][0].update(verified=True)), "needs \"verified\": false"),
    "note page without evidence": (_m(lambda e: e["notes"][0].update(page=3)), "page without evidence"),
    "variant id": (_m(lambda e: e["variants"].append(copy.deepcopy(e["variants"][0]))), "be unique"),
    "variant overrides id": (_m(lambda e: e["variants"][0]["overrides"].update(id="other")), "overrides cannot set"),
    "variant broken override": (_m(lambda e: e["variants"][0]["overrides"]["interfaces"][0].update(default="0x76")),
                                "variants[alt]: interfaces[0]: default '0x76'"),
}


@pytest.mark.parametrize("defect", ENTRY_DEFECTS)
def test_entry_defects_are_problems(defect):
    make, expected = ENTRY_DEFECTS[defect]
    cat = cat_of(make(), one())
    assert any(p.startswith("test.json: ") and expected in p for p in cat.problems), cat.problems
    assert cat.ids() == ["xyz"]  # the broken entry is dropped, the valid one stays
    assert not cat.has("gy-abc280")


def test_ids_and_aliases_are_unique_across_entries():
    dup_alias = one(id="other", aliases=["xyz"])
    cat = cat_of(one(), one(), dup_alias)
    assert cat.ids() == ["xyz"]
    assert any("id 'xyz' is already used by 'xyz'" in p for p in cat.problems)
    assert any("alias 'xyz' is already used" in p for p in cat.problems)


def test_files_are_checked(tmp_path):
    d = tmp_path / "modules"
    d.mkdir()
    (d / "aa.json").write_text(json.dumps({"schema": 1, "wp": "aa", "modules": [one()]}), encoding="utf-8")
    (d / "bb.json").write_text(json.dumps({"schema": 2, "wp": "cc", "modules": [], "x": 1}), encoding="utf-8")
    (d / "dd.json").write_text("{", encoding="utf-8")
    (d / "Bad-Name.json").write_text(json.dumps({"schema": 1, "wp": "Bad-Name", "modules": []}), encoding="utf-8")
    (d / "ee.json").write_text(json.dumps({"schema": 1, "wp": "ee", "modules": [one(id="eee", aliases=["XYZ"])]}),
                               encoding="utf-8")
    (d / "ff.json").write_text(json.dumps({"schema": 1, "wp": "ff", "modules": {}}), encoding="utf-8")
    probs = modules.Catalog.from_dir(d).problems
    joined = "\n".join(probs)
    for text in ("bb.json: -: unknown keys ['x']", "bb.json: -: schema must be 1", "bb.json: -: wp 'cc' differs",
                 "dd.json: -: not readable JSON", "Bad-Name.json: -: file name", "ff.json: -: modules must be a list",
                 "ee.json: eee: aliases must be"):
        assert text in joined, (text, probs)


def test_alias_collision_across_files(tmp_path):
    d = tmp_path / "modules"
    d.mkdir()
    (d / "aa.json").write_text(json.dumps({"schema": 1, "wp": "aa", "modules": [one()]}), encoding="utf-8")
    (d / "bb.json").write_text(json.dumps({"schema": 1, "wp": "bb", "modules": [one(id="other", aliases=["xyz"])]}),
                               encoding="utf-8")
    cat = modules.Catalog(SRC)
    for f in sorted(d.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        cat._add(f.name, doc["wp"], doc["modules"])
    assert cat.ids() == ["xyz"] and cat.problems == ["bb.json: other: alias 'xyz' is already used by 'xyz' (aa.json)"]


def test_from_dir_uses_the_real_sources(tmp_path):
    d = tmp_path / "modules"
    d.mkdir()
    (d / "aa.json").write_text(json.dumps({"schema": 1, "wp": "aa", "modules": [one()]}), encoding="utf-8")
    assert any("unknown source id 'mod-test-abc-ds'" in p for p in modules.Catalog.from_dir(d).problems)


def test_b_only_module_may_carry_addresses_and_notes():
    e = one(id="cheap", category="sensor.environment", source_ids=["mod-test-abc-shop"],
            pins=[{"name": "VCC", "signal": "supply"}, {"name": "SDA", "signal": "i2c_sda"},
                  {"name": "SCL", "signal": "i2c_scl"}],
            interfaces=[{"type": "i2c", "default": "0x38",
                         "addresses": {"value": ["0x38"], "page": 1, "evidence": "I2C address 0x38"}}],
            notes=[{"text": "Shop page: 2.2-5.5 V.", "page": 1, "evidence": "2.2-5.5V"}])
    cat = cat_of(e)
    assert cat.problems == [] and cat.get("cheap")["_class"] == "B"
    e["supplies"] = {"VCC": {"max": F(5.5, page=1, evidence="2.2-5.5V")}}
    assert any("cannot back a hard value" in p for p in cat_of(e).problems)


# --- lookup ----------------------------------------------------------------------------------------------------------
def test_get_returns_a_copy_with_wp_and_class():
    cat = cat_of(module_entry(), wp="env")
    e = cat.get("GY-ABC280")
    assert e["id"] == "abc280" and e["_wp"] == "env" and e["_class"] == "A"
    e["pins"].clear()
    assert cat.get("abc280")["pins"]
    assert cat.resolve_id(" Gy-Abc280 ") == "abc280" and cat.has("ABC280") and not cat.has("abc")


def test_get_applies_the_variant_flat():
    cat = cat_of(module_entry())
    base, alt = cat.get("abc280"), cat.get("abc280", "alt")
    assert [i["default"] for i in alt["interfaces"]] == ["0x77"]
    assert "select" not in alt["interfaces"][0]  # an override replaces the whole top-level key
    assert alt["supplies"] == base["supplies"] and base["interfaces"][0]["default"] == "0x76"
    assert cat.get("abc280", None) == base


def test_unknown_module_and_variant_raise_invalid_args():
    cat = cat_of(module_entry())
    with pytest.raises(BenchError) as e:
        cat.get("nope")
    assert e.value.code == "invalid_args" and e.value.hint == "list modules with bench_pins action=modules"
    with pytest.raises(BenchError) as e:
        cat.resolve_id("nope")
    assert e.value.code == "invalid_args"
    with pytest.raises(BenchError) as e:
        cat.get("abc280", "zz")
    assert e.value.code == "invalid_args" and "alt" in e.value.hint


def _many():
    a = module_entry()
    b = one(id="ds_rtc", title="DS-RTC clock", manufacturer="Analog Example",
            interfaces=[{"type": "onewire"}], supplies={"VCC": {"min": F(3.0), "max": F(5.5)}})
    c = one(id="aaa_env", title="Another environment sensor", category="sensor.environment", aliases=["zzz"])
    d = one(id="light1", title="Light sensor", category="sensor.light")
    return cat_of(a, b, c, d)


def test_search_rows_and_order():
    cat = _many()
    res = cat.search()
    assert res["total"] == 4
    assert [r["id"] for r in res["items"]] == ["ds_rtc", "aaa_env", "abc280", "light1"]  # category, then id
    row = next(r for r in res["items"] if r["id"] == "abc280")
    assert row == {"id": "abc280", "title": "ABC280 synthetic environment sensor", "category": "sensor.environment",
                   "kind": "module", "interfaces": ["i2c"], "addresses": ["0x76", "0x77"], "supply": "1.71–3.6 V",
                   "class": "A"}
    assert next(r for r in res["items"] if r["id"] == "ds_rtc")["supply"] == "3–5.5 V"
    assert next(r for r in res["items"] if r["id"] == "light1")["supply"] is None


def test_search_filters_and_paging():
    cat = _many()
    ids = lambda **kw: [r["id"] for r in cat.search(**kw)["items"]]  # noqa: E731
    assert ids(q="GY-ABC") == ["abc280"]  # alias
    assert ids(q="zzz") == ["aaa_env"]
    assert ids(q="analog example") == ["ds_rtc"]  # manufacturer
    assert ids(q="SENSOR") == ["aaa_env", "abc280", "light1"]  # title
    assert ids(category="sensor.environment") == ["aaa_env", "abc280"]
    assert ids(category="sensor") == ["aaa_env", "abc280", "light1"]  # prefix of a dotted category
    assert ids(category="sens") == []
    assert ids(interface="i2c") == ["abc280"] and ids(interface="onewire") == ["ds_rtc"]
    page = cat.search(limit=2, offset=1)
    assert page["total"] == 4 and [r["id"] for r in page["items"]] == ["aaa_env", "abc280"]
    assert cat.search(limit=0)["items"] == [] and cat.search(offset=10)["items"] == []


def test_families_and_categories():
    cat = modules.Catalog(SRC)
    cat._add("b.json", "bb", [one()])
    cat._add("a.json", "aa", [one(id="other", category="adc")])
    assert cat.families() == ["aa", "bb"] and cat.categories() == ["adc", "rtc"]


def test_value_resolves_belegte_zahlen():
    assert modules.value({"value": 3.6, "unit": "V"}, {}) == 3.6
    assert modules.value({"rel": 0.7, "of": "VDD"}, {"VDD": 3.3}) == pytest.approx(2.31)
    assert modules.value({"rel_offset": 0.3, "of": "VDDIO"}, {"VDDIO": 3.3}) == pytest.approx(3.6)
    assert modules.value({"rel": 0.7, "of": "VDD"}, {"VDDIO": 3.3}) is None
    assert modules.value(None, {"VDD": 3.3}) is None
    assert modules.value({"value": ["0x76"]}, {}) is None
    assert modules.value({"unit": "V"}, {}) is None


def test_sources_class_field(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    base = {"title": "t", "url": "https://example.com/x.pdf", "retrieved": "2026-11-08"}
    (d / "old.json").write_text(json.dumps([{"id": "old-a", **base}, {"id": "old-b", **base, "class": "A1"}]),
                                encoding="utf-8")
    (d / "mod-zz.json").write_text(json.dumps([{"id": "mod-zz-a", **base, "class": "B"}]), encoding="utf-8")
    got = sources.load_dir(d)
    assert got["old-a"].get("class") is None and got["old-b"]["class"] == "A1" and got["mod-zz-a"]["class"] == "B"
    for i, (name, entry, text) in enumerate((
            ("old.json", {"id": "x", **base, "class": "C"}, "class must be one of"),
            ("mod-zz.json", {"id": "mod-zz-b", **base}, "class is required"),
            ("mod-zz.json", {"id": "mod-yy-b", **base, "class": "A"}, "ids must start with mod-zz-"),
            ("mod-Z.json", {"id": "mod-Z-b", **base, "class": "A"}, "work package name"))):
        e = tmp_path / f"case{i}"
        e.mkdir()
        (e / name).write_text(json.dumps([entry]), encoding="utf-8")
        with pytest.raises(ValueError, match=text):
            sources.load_dir(e)

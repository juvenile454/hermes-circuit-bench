"""Five corpus files that vendors stopped serving to scripts (or replaced by a newer revision) are pinned to
web.archive.org ``id_`` snapshots. For these five the snapshot is byte-identical to the file pinned before, so
their SHA-256 stays. (The DRV5032 datasheet and the two WT32-ETH01 wiki pages are archive snapshots, too, but of
different bytes: they carry new hashes, which the tests of their own modules expect.)

Offline: reads the manifests, excerpt headers and source files only (the byte check against the files themselves is
done by the corpus tests when the corpus is present).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus"
SOURCES = ROOT / "circuit_bench" / "data" / "sources"

# manifest, excerpt, source file, source id, snapshot url, pinned sha256, expected source class
CASES = [
    ("electrical", "esp-esp32c3-dc", "electrical", "elec-ds-esp32c3",
     "https://web.archive.org/web/20261104145406id_/https://documentation.espressif.com/esp32-c3_datasheet_en.pdf",
     "833fc000b4b3c3d39c496fcbd597fed5806956503ce7390b19cc8ae82f19f968", "A"),
    ("electrical", "esp-esp32c6-dc", "electrical", "elec-ds-esp32c6",
     "https://web.archive.org/web/20261105173933id_/https://documentation.espressif.com/esp32-c6_datasheet_en.pdf",
     "372a5b42b2900c83ef4309149c8835e9ae2d1be19244995bf2fb83af4dc5edf1", "A"),
    ("mod-ndisplay", "mod-ndisplay-st7735s", "mod-ndisplay", "mod-ndisplay-st7735s-ds",
     "https://web.archive.org/web/20230729195332id_/https://www.waveshare.com/w/upload/e/e2/ST7735S_V1.1_20111121.pdf",
     "37b93f0ef6d5ac0bafe76868e048b67dce682d92fb9bf5a7ca8d8070a45fcc94", "A2"),
    ("mod-pixel", "mod-pixel-gc9a01", "mod-pixel", "mod-pixel-gc9a01-ds",
     "https://web.archive.org/web/20251217183447id_/https://www.waveshare.com/w/upload/5/5e/GC9A01A.pdf",
     "af8f6f0a03f4a340510fc06321eb78a2d9bb49670ff1f59164bd6ccf71a2bd47", "B"),
    ("mod-switch", "mod-switch-6n137", "mod-switch", "mod-switch-6n137-ds",
     "https://web.archive.org/web/20251022204009id_/https://www.vishay.com/docs/84732/6n137.pdf",
     "e838b59beab53ddad0fedf094df8bd32fc35297fda7d500fd24ddd188924f6d2", "A1"),
]
IDS = [c[3] for c in CASES]


def _header(excerpt: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for ln in (CORPUS / "excerpts" / f"{excerpt}.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"# (source_id|url|corpus|retrieved): (.*)$", ln)
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta


@pytest.mark.parametrize("manifest,excerpt,srcfile,sid,url,sha,cls", CASES, ids=IDS)
def test_entry_points_at_the_snapshot_and_keeps_its_hash(manifest, excerpt, srcfile, sid, url, sha, cls):
    entry = next(e for e in json.loads((CORPUS / f"{manifest}.json").read_text(encoding="utf-8"))["files"]
                 if e["source_id"] == sid)
    assert entry["url"] == url and entry["sha256"] == sha
    meta = _header(excerpt)
    assert meta["source_id"] == sid and meta["url"] == url
    assert meta["corpus"] == f"{entry['path']} sha256 {sha}"
    assert meta["retrieved"] == "2026-11-13"
    src = next(s for s in json.loads((SOURCES / f"{srcfile}.json").read_text(encoding="utf-8")) if s["id"] == sid)
    assert src["url"] == url and src["retrieved"] == "2026-11-13"
    assert src.get("class", "A") == cls  # a snapshot of a copy or a preliminary file does not raise the class
    assert f"sha256 {sha}" in src["note"] and "web.archive.org snapshot" in src["note"]


@pytest.mark.parametrize("manifest,excerpt,srcfile,sid,url,sha,cls", CASES, ids=IDS)
def test_snapshot_url_has_the_raw_id_form(manifest, excerpt, srcfile, sid, url, sha, cls):
    m = re.fullmatch(r"https://web\.archive\.org/web/(\d{14})id_/(https://[^\s]+)", url)
    assert m, url
    assert "/web/" + m.group(1) + "id_/" in url

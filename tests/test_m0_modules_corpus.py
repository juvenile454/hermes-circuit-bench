"""Module excerpts against the pinned files, and the corpus tools.

- corpus (``@pytest.mark.corpus``, skips per file without tests/.corpus): for every tests/corpus/excerpts/mod-*.txt the
  pinned file's SHA-256 equals the manifest, and every line of every ``@@ page N`` segment IS a line of pypdf's text of
  that page (exact up to trailing whitespace, in document order, gaps allowed). The page text comes from the cache
  tests/.corpus/.text/<sha256>.json (tests/excerpts.py). HTML segments are checked by tests/test_c0_corpus.py.
- tools (no corpus): tests/excerpts.py (parser, in-order matching, text cache, AES-encrypted PDFs),
  scripts/excerpt.py (output format, --grep, --find, --header) and scripts/fetch_corpus.py (backoff on 429/5xx,
  gzip before the hash, CB_CORPUS_DIR, mod-<wp> paths) on synthetic PDFs and fake HTTP responses.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

import excerpts as ex

ROOT = Path(__file__).resolve().parent.parent
MOD_EXCERPTS = sorted(p.name for p in ex.EXCERPTS.glob("mod-*.txt"))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"cb_script_{name}", ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- corpus: module excerpts ↔ pinned PDFs --------------------------------------------------------------------------
@pytest.mark.corpus
@pytest.mark.parametrize("name", MOD_EXCERPTS)
def test_module_excerpt_lines_are_on_the_pinned_page(name):
    e = ex.parse(name)
    corpus = e.corpus()
    assert corpus, f"{name}: no '# corpus: <path> sha256 <hex>' header"
    path, sha = corpus
    entry = ex.entry_for_path(path)
    assert entry is not None and entry["sha256"] == sha, f"{name}: {path} not pinned with this sha256 in a manifest"
    target = ex.CORPUS / path
    if not target.is_file():
        pytest.skip(f"corpus file missing: {path} (scripts/fetch_corpus.py)")
    assert ex.file_sha256(target) == sha, f"{path}: SHA-256 differs from the manifest"
    if not path.endswith(".pdf"):
        return  # HTML: tests/test_c0_corpus.py
    pytest.importorskip("pypdf")
    text = ex.PdfText(target, sha)
    for page in e.pages():
        hay = text.lines(page)
        for seg in e.page_segments(page):
            miss = ex.lines_in_order(seg, hay)
            assert miss is None, f"{name} page {page}: {miss!r} is not a line of pypdf's page text (in order)"


@pytest.mark.corpus
def test_module_manifest_files_match_their_sha256():
    for stem, entry in ex.manifest_entries(pattern="mod-*.json"):
        target = ex.CORPUS / entry["path"]
        if target.is_file():
            assert ex.file_sha256(target) == entry["sha256"], f"{stem}: {entry['path']}"


# --- tests/excerpts.py --------------------------------------------------------------------------------------------
def test_parser_reads_header_segments_and_hash_lines():
    e = ex.parse_text("# source_id: mod-env-x\n# a comment line\n# corpus: mod/env/x.pdf sha256 " + "a" * 64 +
                      "\n\n@@ page 3\nline one\n# 5 V tolerant\n\n@@ page 7\nlast\n", "x.txt")
    assert e.meta == {"source_id": "mod-env-x", "corpus": "mod/env/x.pdf sha256 " + "a" * 64}
    assert e.comments == ["a comment line"]
    assert e.segments == [("page 3", ["line one", "# 5 V tolerant"]), ("page 7", ["last"])]
    assert e.pages() == [3, 7] and e.page_segments(3) == [["line one", "# 5 V tolerant"]]
    assert e.corpus() == ("mod/env/x.pdf", "a" * 64) and e.lines == ["line one", "# 5 V tolerant", "last"]


def test_every_committed_excerpt_parses():
    found = ex.excerpts()
    assert len(found) >= 10
    for e in found:
        assert e.segments, e.name


def test_parts_in_order():
    lines = ["Input high level Vih_si VDDIO=1.2 V to 3.6 V 80   %VDDI", "O", "Input low level 20 %VDDIO"]
    assert ex.find_parts_in_order(["Input high level Vih_si", "80   %VDDI", "O"], lines)
    assert ex.find_parts_in_order(["Vih_si", "Input low level"], lines)
    assert ex.find_parts_in_order(["VDDIO=1.2", "VDDIO"], lines)  # same line, later column, then next lines
    assert not ex.find_parts_in_order(["80   %VDDI", "Input high level"], lines)
    assert not ex.find_parts_in_order(["80 %VDDI"], lines)  # verbatim, whitespace counts
    assert ex.lines_in_order(["a", "c "], ["a", "b", "c"]) is None
    assert ex.lines_in_order(["c", "a"], ["a", "b", "c"]) == "a"
    assert ex.lines_in_order(["b"], ["a", "bb"]) == "b"


def _pdf(pages: list[list[str]]) -> bytes:
    """A minimal PDF with one Helvetica text line per entry (synthetic test data)."""
    objs: list[bytes] = []
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = 3 + 2 * len(pages)
    for i, lines in enumerate(pages):
        body = "BT /F1 11 Tf 72 720 Td 14 TL " + " ".join(
            f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in lines) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R "
                    f">> >> /Contents {4 + 2 * i} 0 R >>".encode())
        objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


PAGES = [["Cover page"], ["Supply voltage VDD 1.71 3.6 V", "I2C address 0x76 or 0x77"]]


@pytest.fixture
def pdf(tmp_path):
    pytest.importorskip("pypdf")
    p = tmp_path / "corpus" / "mod" / "zz" / "part.pdf"
    p.parent.mkdir(parents=True)
    p.write_bytes(_pdf(PAGES))
    return p


@pytest.fixture
def aes_pdf(tmp_path, pdf):
    pypdf = pytest.importorskip("pypdf")
    pytest.importorskip("cryptography")  # dev dependency for AES
    w = pypdf.PdfWriter(clone_from=str(pdf))
    w.encrypt(user_password="", owner_password="owner", algorithm="AES-256")  # noqa: S106 - synthetic test file
    p = pdf.with_name("part-aes.pdf")
    with p.open("wb") as f:
        w.write(f)
    assert pypdf.PdfReader(str(p)).is_encrypted
    return p


def test_text_cache_stores_pypdf_lines(pdf, tmp_path):
    cache = tmp_path / "cache"
    t = ex.PdfText(pdf, cache_dir=cache)
    assert [ln for ln in t.lines(2) if ln] == ["Supply voltage VDD 1.71 3.6 V", "I2C address 0x76 or 0x77"]
    assert t.lines(2) == ex.page_text(ex.open_pdf(pdf), 2).split("\n")  # the same extraction the tests use
    data = json.loads((cache / f"{t.sha}.json").read_text(encoding="utf-8"))
    assert data["pages"]["2"] == t.lines(2) and data["pages_total"] == 2 and data["pypdf"] == t.version
    with pytest.raises(IndexError):
        t.lines(3)


def test_text_cache_is_used_and_version_bound(pdf, tmp_path):
    cache = tmp_path / "cache"
    sha = ex.file_sha256(pdf)
    ver = ex.PdfText(pdf, cache_dir=cache).version
    (cache).mkdir()
    (cache / f"{sha}.json").write_text(json.dumps({"pypdf": ver, "pages_total": 2, "pages": {"1": ["from cache"]}}),
                                       encoding="utf-8")
    ex._memory.cache_clear()
    assert ex.PdfText(pdf, sha, cache_dir=cache).lines(1) == ["from cache"]
    (cache / f"{sha}.json").write_text(json.dumps({"pypdf": "0.0", "pages_total": 2, "pages": {"1": ["stale"]}}),
                                       encoding="utf-8")
    ex._memory.cache_clear()
    assert ex.PdfText(pdf, sha, cache_dir=cache).lines(1)[0] == "Cover page"
    ex._memory.cache_clear()


def test_encrypted_pdf_is_read(aes_pdf, tmp_path):
    ex._memory.cache_clear()
    assert ex.PdfText(aes_pdf, cache_dir=tmp_path / "c").lines(2)[0] == "Supply voltage VDD 1.71 3.6 V"


# --- scripts/excerpt.py -------------------------------------------------------------------------------------------
def _excerpt_cli(*args, env=None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "excerpt.py"), *map(str, args)],
                          capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False,
                          timeout=120)


def test_excerpt_cli_prints_a_segment_with_header(pdf):
    sha = ex.file_sha256(pdf)
    corpus = pdf.parents[2]
    r = _excerpt_cli(pdf, "--page", 2, "--grep", "VDD", "--header", "mod-zz-part,https://example.com/p.pdf,2026-11-08",
                     "--document", "Example part datasheet rev 1", env={"CB_CORPUS_DIR": str(corpus)})
    assert r.returncode == 0, r.stderr
    import pypdf
    assert r.stdout.splitlines() == [
        "# source_id: mod-zz-part", "# document: Example part datasheet rev 1", "# url: https://example.com/p.pdf",
        f"# corpus: mod/zz/part.pdf sha256 {sha}", "# retrieved: 2026-11-08",
        f"# extracted: pypdf {pypdf.__version__}, PdfReader(pdf).pages[N - 1].extract_text()",
        "@@ page 2", "Supply voltage VDD 1.71 3.6 V"]
    e = ex.parse_text(r.stdout)
    assert e.corpus() == ("mod/zz/part.pdf", sha) and e.page_segments(2) == [["Supply voltage VDD 1.71 3.6 V"]]


def test_excerpt_cli_pages_find_and_errors(pdf):
    r = _excerpt_cli(pdf, "--page", 1, "--page", 2)
    assert r.stdout.splitlines() == ["@@ page 1", "Cover page", "@@ page 2", *PAGES[1]]
    r = _excerpt_cli(pdf, "--find", "0x77")
    assert r.returncode == 0 and r.stdout.splitlines() == ["page 2: I2C address 0x76 or 0x77"]
    assert _excerpt_cli(pdf, "--find", "0x99").returncode == 1
    assert _excerpt_cli(pdf, "--page", 3).returncode == 2
    assert _excerpt_cli(pdf).returncode == 2


def test_excerpt_cli_reads_encrypted_pdfs(aes_pdf):
    r = _excerpt_cli(aes_pdf, "--page", 2, "--grep", "0x7[67]")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["@@ page 2", "I2C address 0x76 or 0x77"]


def test_excerpt_cli_output_matches_the_corpus_test_extraction(pdf):
    """excerpt.py output passes the strict corpus comparison (round trip)."""
    e = ex.parse_text(_excerpt_cli(pdf, "--page", 2).stdout)
    ex._memory.cache_clear()
    assert ex.lines_in_order(e.page_segments(2)[0], ex.PdfText(pdf, cache_dir=pdf.parent / "c").lines(2)) is None


# --- scripts/fetch_corpus.py --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fc():
    return _load_script("fetch_corpus")


class _Resp:
    def __init__(self, body: bytes, encoding: str | None = None):
        self.body = body
        self.headers = Message()
        if encoding:
            self.headers["Content-Encoding"] = encoding

    def read(self, n: int = -1):
        body, self.body = self.body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_MADE: list[urllib.error.HTTPError] = []


def _http_error(code: int, retry_after: str | None = None):
    h = Message()
    if retry_after:
        h["Retry-After"] = retry_after
    _MADE.append(urllib.error.HTTPError("https://example.com/x", code, "err", h, None))
    return _MADE[-1]


@pytest.fixture(autouse=True)
def _close_http_errors():
    """Fake HTTPErrors carry a body; close every one a test made (an unclosed one warns when collected)."""
    yield
    while _MADE:
        _MADE.pop().close()


def test_fetch_retries_429_and_5xx_with_backoff(fc):
    calls, sleeps = [], []
    script = [_http_error(429), _http_error(503), _http_error(500), _Resp(b"ok")]

    def opener(req, timeout):
        calls.append(req.full_url)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    assert fc.fetch("https://example.com/x", attempts=6, sleep=sleeps.append, opener=opener) == b"ok"
    assert len(calls) == 4 and len(sleeps) == 3
    assert 1 <= sleeps[0] <= 2 and 2 <= sleeps[1] <= 4 and 4 <= sleeps[2] <= 8


def test_fetch_gives_up_after_six_attempts_and_not_on_404(fc):
    calls, sleeps = [], []

    def busy(req, timeout):
        calls.append(1)
        raise _http_error(502)

    with pytest.raises(urllib.error.HTTPError):
        fc.fetch("https://example.com/x", sleep=sleeps.append, opener=busy)
    assert len(calls) == fc.ATTEMPTS == 6 and len(sleeps) == 5

    calls.clear()

    def missing(req, timeout):
        calls.append(1)
        raise _http_error(404)

    with pytest.raises(urllib.error.HTTPError):
        fc.fetch("https://example.com/x", sleep=sleeps.append, opener=missing)
    assert len(calls) == 1


def test_backoff_delay(fc):
    assert [fc.backoff_delay(n, rand=lambda: 0.0) for n in range(1, 6)] == [1, 2, 4, 8, 16]
    assert fc.backoff_delay(3, rand=lambda: 1.0) == 8
    assert fc.backoff_delay(10, rand=lambda: 1.0) == fc.MAX_DELAY_S
    assert fc.backoff_delay(1, _http_error(429, "7")) == 7
    assert fc.backoff_delay(1, _http_error(429, "900")) == fc.MAX_DELAY_S


def test_gzip_is_unpacked_before_hashing(fc):
    raw = b"%PDF-1.4 synthetic"
    packed = gzip.compress(raw)
    assert fc.decode_body(packed, "gzip", "mod/zz/a.pdf") == raw
    assert fc.decode_body(packed, None, "mod/zz/a.pdf") == raw  # magic 1f 8b without header
    assert fc.decode_body(packed, None, "mod/zz/a.tar.gz") == packed  # a pinned archive stays as is
    assert fc.decode_body(raw, None, "mod/zz/a.pdf") == raw
    got = fc.fetch("https://example.com/a.pdf", "mod/zz/a.pdf", opener=lambda req, timeout: _Resp(packed, "gzip"))
    assert hashlib.sha256(got).hexdigest() == hashlib.sha256(raw).hexdigest()


def test_mod_manifest_paths(fc):
    assert fc.path_problem("mod-env", "mod/env/bosch/bme280.pdf") is None
    assert fc.path_problem("mod-env", "mod/env/bme280.pdf") is None
    assert "mod/env/" in fc.path_problem("mod-env", "mod/display/x.pdf")
    assert "mod/env/" in fc.path_problem("mod-env", "espressif/x.pdf")
    assert "mod/env/" in fc.path_problem("mod-env", "mod/env")
    assert fc.path_problem("pins", "espressif/x.pdf") is None
    assert fc.path_problem("pins", "../x.pdf") and fc.path_problem("pins", "/etc/x")


def test_run_writes_into_the_given_corpus(fc, tmp_path, capsys):
    raw = b"%PDF-1.4 synthetic file"
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    good = {"url": "https://example.com/a.pdf", "path": "mod/zz/a.pdf", "sha256": hashlib.sha256(raw).hexdigest()}
    (manifests / "mod-zz.json").write_text(json.dumps({"files": [good, {**good, "path": "elsewhere/a.pdf"}]}),
                                           encoding="utf-8")
    (manifests / "mod-yy.json").write_text(json.dumps({"files": [{"url": "https://example.com/b.pdf",
                                                                  "path": "mod/yy/b.pdf"}]}), encoding="utf-8")
    corpus = tmp_path / "corpus"
    def gz(u, p):  # the real fetch with a gzip response: unpacked before the hash
        return fc.fetch(u, p, opener=lambda req, timeout: _Resp(gzip.compress(raw), "gzip"))

    rc = fc.run(["mod-zz"], False, corpus=corpus, manifests=manifests, fetcher=gz)
    out = capsys.readouterr().out
    assert rc == 1 and (corpus / "mod/zz/a.pdf").read_bytes() == raw and "BAD PATH mod-zz.json: elsewhere/a.pdf" in out
    assert fc.run(["mod-zz"], False, corpus=corpus, manifests=manifests,
                  fetcher=lambda u, p: pytest.fail("no download when the hash matches")) == 1
    assert "ok      mod/zz/a.pdf" in capsys.readouterr().out
    assert fc.run(["mod-yy"], True, corpus=corpus, manifests=manifests, fetcher=lambda u, p: raw) == 0
    pinned = json.loads((manifests / "mod-yy.json").read_text(encoding="utf-8"))["files"][0]["sha256"]
    assert pinned == hashlib.sha256(raw).hexdigest()

    def broken(u, p):
        raise urllib.error.URLError("down")

    (corpus / "mod/zz/a.pdf").unlink()
    assert fc.run(["mod-zz"], False, corpus=corpus, manifests=manifests, fetcher=broken) == 1
    assert "FAILED  mod/zz/a.pdf" in capsys.readouterr().out
    assert fc.run(["nope"], False, corpus=corpus, manifests=manifests) == 1


def test_cb_corpus_dir_overrides_the_target(tmp_path):
    code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('f',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.CORPUS)")
    script = str(ROOT / "scripts" / "fetch_corpus.py")
    r = subprocess.run([sys.executable, "-c", code, script], capture_output=True, text=True, check=True,
                       env={**os.environ, "CB_CORPUS_DIR": str(tmp_path)}, timeout=60)
    assert r.stdout.strip() == str(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "CB_CORPUS_DIR"}
    r = subprocess.run([sys.executable, "-c", code, script], capture_output=True, text=True, check=True, env=env,
                       timeout=60)
    assert r.stdout.strip().endswith("tests/.corpus")


def test_a_trickling_download_hits_the_wall_clock_deadline_and_is_retried(fc):
    """CI 08.11.2026: a vendor server sent bytes slowly enough that the socket timeout never fired (job cancelled
    after 20 min). The wall-clock deadline turns that into a retried TimeoutError."""
    class Slow(_Resp):
        def read(self, n: int = -1):
            return b"x"  # never ends

    ticks = iter(range(0, 10**6, 100))
    sleeps: list[float] = []
    with pytest.raises(TimeoutError):
        fc.fetch("https://example.com/slow.pdf", attempts=2, sleep=sleeps.append,
                 opener=lambda req, timeout: Slow(b""), clock=lambda: next(ticks))
    assert len(sleeps) == 1
    assert fc.read_all(_Resp(b"abc"), "u") == b"abc"

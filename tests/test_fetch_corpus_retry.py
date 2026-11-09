"""scripts/fetch_corpus.py: retry budget per error kind, the ti.com hint on a hash mismatch, atomic writes.

- A timeout (wall-clock deadline in read_all, socket timeout, URLError caused by a timeout) gets TIMEOUT_ATTEMPTS = 2
  attempts; HTTP 429/5xx keep ATTEMPTS = 6. Fake clock and fake sleep, no network.
- A hash mismatch for a file straight from ti.com/lit/ prints a hint to pin a web.archive.org ``id_`` snapshot; other
  hosts and archived ti.com copies get no hint.
- A fetched file replaces the target by rename, so a hard link to the old file keeps the old bytes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def fc():
    spec = importlib.util.spec_from_file_location("cb_script_fetch_corpus_retry", ROOT / "scripts" / "fetch_corpus.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Trickle:
    """A response that never ends: one byte per read."""
    headers = Message()

    def read(self, n: int = -1) -> bytes:
        return b"x"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _counting(calls: list, action):
    def opener(req, timeout):
        calls.append(req.full_url)
        return action()
    return opener


def _raise(err):
    def action():
        raise err
    return action


_MADE: list[urllib.error.HTTPError] = []


def _http(code: int) -> urllib.error.HTTPError:
    _MADE.append(urllib.error.HTTPError("https://example.com/x", code, "err", Message(), None))
    return _MADE[-1]


@pytest.fixture(autouse=True)
def _close_http_errors():
    """Fake HTTPErrors carry a body; close every one a test made (an unclosed one warns when collected)."""
    yield
    while _MADE:
        _MADE.pop().close()


def test_budget_constants(fc):
    assert fc.ATTEMPTS == 6 and fc.TIMEOUT_ATTEMPTS == 2


def test_a_deadline_timeout_gets_two_attempts(fc):
    calls, sleeps = [], []
    ticks = iter(range(0, 10**7, 100))
    with pytest.raises(TimeoutError):
        fc.fetch("https://example.com/slow.pdf", sleep=sleeps.append, opener=_counting(calls, _Trickle),
                 clock=lambda: next(ticks))
    assert len(calls) == 2 and len(sleeps) == 1


@pytest.mark.parametrize("err", [TimeoutError("timed out"), urllib.error.URLError(TimeoutError("timed out"))],
                         ids=["socket", "urlerror"])
def test_a_socket_timeout_gets_two_attempts(fc, err):
    calls, sleeps = [], []
    with pytest.raises(type(err)):
        fc.fetch("https://example.com/slow.pdf", sleep=sleeps.append, opener=_counting(calls, _raise(err)))
    assert len(calls) == 2 and len(sleeps) == 1


def test_503_keeps_six_attempts(fc):
    calls, sleeps = [], []
    with pytest.raises(urllib.error.HTTPError):
        fc.fetch("https://example.com/x", sleep=sleeps.append, opener=_counting(calls, _raise(_http(503))))
    assert len(calls) == 6 and len(sleeps) == 5


def test_timeouts_count_on_top_of_other_retries(fc):
    """503, 503, timeout, timeout: the second timeout ends the run although 6 attempts were allowed."""
    calls, sleeps = [], []
    script = [_http(503), _http(503), TimeoutError("deadline"), TimeoutError("deadline"), _http(503)]

    def opener(req, timeout):
        calls.append(1)
        raise script.pop(0)

    with pytest.raises(TimeoutError):
        fc.fetch("https://example.com/x", sleep=sleeps.append, opener=opener)
    assert len(calls) == 4 and len(sleeps) == 3


def test_one_timeout_then_success(fc):
    script = [TimeoutError("deadline"), _http(502)]

    class Ok(_Trickle):
        def __init__(self):
            self.body = b"%PDF ok"

        def read(self, n: int = -1) -> bytes:
            body, self.body = self.body, b""
            return body

    def opener(req, timeout):
        if script:
            raise script.pop(0)
        return Ok()

    assert fc.fetch("https://example.com/x.pdf", sleep=lambda s: None, opener=opener) == b"%PDF ok"


def _manifest(tmp_path: Path, url: str, want: str) -> Path:
    manifests = tmp_path / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / "mod-zz.json").write_text(json.dumps({"files": [{"url": url, "path": "mod/zz/a.pdf",
                                                                  "sha256": want}]}), encoding="utf-8")
    return manifests


@pytest.mark.parametrize("url, hint", [
    ("https://www.ti.com/lit/ds/symlink/pcf8574.pdf", True),
    ("https://www.ti.com/lit/pdf/scps068", True),
    ("https://web.archive.org/web/20261011000902id_/https://www.ti.com/lit/ds/symlink/pcf8574.pdf", False),
    ("https://example.com/lit/ds/x.pdf", False),
    ("https://www.ti.com/product/PCF8574", False),
])
def test_a_ti_lit_hash_mismatch_suggests_a_wayback_snapshot(fc, tmp_path, capsys, url, hint):
    manifests = _manifest(tmp_path, url, "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=lambda u, p: b"%PDF new")
    out = capsys.readouterr().out
    assert rc == 1 and "MISMATCH mod/zz/a.pdf" in out
    assert ("web.archive.org/web/<timestamp>id_/" + url in out) is hint
    assert ("hint" in out) is hint


def test_a_fetched_file_replaces_a_hard_link_instead_of_writing_through_it(fc, tmp_path):
    new = b"%PDF-1.4 new"
    manifests = _manifest(tmp_path, "https://example.com/a.pdf", hashlib.sha256(new).hexdigest())
    shared = tmp_path / "shared.pdf"
    shared.write_bytes(b"%PDF-1.4 old")
    target = tmp_path / "corpus" / "mod" / "zz" / "a.pdf"
    target.parent.mkdir(parents=True)
    os.link(shared, target)
    assert fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=lambda u, p: new) == 0
    assert target.read_bytes() == new and shared.read_bytes() == b"%PDF-1.4 old"
    assert [p.name for p in target.parent.iterdir()] == ["a.pdf"]  # no temporary file left behind

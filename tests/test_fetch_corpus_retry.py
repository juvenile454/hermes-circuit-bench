"""scripts/fetch_corpus.py: retry budget per error kind, the snapshot hint on a failed download, atomic writes.

- A timeout (wall-clock deadline in read_all, socket timeout, URLError caused by a timeout) gets TIMEOUT_ATTEMPTS = 2
  attempts; HTTP 429/5xx keep ATTEMPTS = 6. Fake clock and fake sleep, no network.
- A hash mismatch on any host, and HTTP 403 or 404, print a hint to pin a web.archive.org ``id_`` snapshot of the same
  revision; files straight from ti.com/lit/ get the re-stamping reason on top. A URL that already points into
  web.archive.org gets no hint, and neither does a failure that has nothing to do with the document (5xx, network).
- A fetched file replaces the target by rename, so a hard link to the old file keeps the old bytes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import urllib.error
from email.message import Message
from pathlib import Path

import pytest
import yaml

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


SNAPSHOT_FORM = "hint    pin a web.archive.org snapshot https://web.archive.org/web/<timestamp>id_/{url} of the same document revision"
TI_REASON = "re-stamps files under /lit/"
ARCHIVED = "https://web.archive.org/web/20261011000902id_/https://www.ti.com/lit/ds/symlink/pcf8574.pdf"


@pytest.mark.parametrize("url", [
    "https://documentation.espressif.com/esp32-c3_datasheet_en.pdf",
    "https://www.vishay.com/docs/83605/6n137.pdf",
    "https://example.com/lit/ds/x.pdf",
    "https://www.ti.com/product/PCF8574",
])
def test_a_hash_mismatch_outside_ti_lit_suggests_a_wayback_snapshot(fc, tmp_path, capsys, url):
    manifests = _manifest(tmp_path, url, "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=lambda u, p: b"%PDF new")
    out = capsys.readouterr().out
    assert rc == 1 and "MISMATCH mod/zz/a.pdf" in out
    assert SNAPSHOT_FORM.format(url=url) + " (CONTRIBUTING.md)" in out
    assert TI_REASON not in out


@pytest.mark.parametrize("url", ["https://www.ti.com/lit/ds/symlink/pcf8574.pdf", "https://www.ti.com/lit/pdf/scps068"])
def test_a_ti_lit_hash_mismatch_keeps_the_restamping_reason(fc, tmp_path, capsys, url):
    manifests = _manifest(tmp_path, url, "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=lambda u, p: b"%PDF new")
    out = capsys.readouterr().out
    assert rc == 1 and "MISMATCH mod/zz/a.pdf" in out
    assert SNAPSHOT_FORM.format(url=url) + " (CONTRIBUTING.md)" in out
    assert "hint    ti.com re-stamps files under /lit/ daily" in out


@pytest.mark.parametrize("code", [403, 404])
@pytest.mark.parametrize("url", [
    "https://www.vishay.com/docs/83605/6n137.pdf",
    "https://www.ti.com/lit/ds/symlink/pcf8574.pdf",
])
def test_http_403_and_404_suggest_a_wayback_snapshot(fc, tmp_path, capsys, url, code):
    def fetcher(u, p):
        raise _http(code)
    manifests = _manifest(tmp_path, url, "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=fetcher)
    out = capsys.readouterr().out
    assert rc == 1 and f"FAILED  mod/zz/a.pdf: HTTP Error {code}" in out
    assert SNAPSHOT_FORM.format(url=url) + " (CONTRIBUTING.md)" in out
    assert (TI_REASON in out) is ("ti.com/lit/" in url)


@pytest.mark.parametrize("code", [403, 404])
def test_a_failure_for_an_archived_url_gets_no_hint(fc, tmp_path, capsys, code):
    def fetcher(u, p):
        raise _http(code)
    manifests = _manifest(tmp_path, ARCHIVED, "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=fetcher)
    out = capsys.readouterr().out
    assert rc == 1 and "FAILED" in out and "hint" not in out


def test_a_hash_mismatch_for_an_archived_url_gets_no_hint(fc, tmp_path, capsys):
    manifests = _manifest(tmp_path, ARCHIVED, "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=lambda u, p: b"%PDF new")
    out = capsys.readouterr().out
    assert rc == 1 and "MISMATCH" in out and "hint" not in out


@pytest.mark.parametrize("code", [429, 500, 503])
def test_other_failures_get_no_hint(fc, tmp_path, capsys, code):
    def fetcher(u, p):
        raise _http(code)
    manifests = _manifest(tmp_path, "https://www.vishay.com/docs/83605/6n137.pdf", "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=fetcher)
    out = capsys.readouterr().out
    assert rc == 1 and "FAILED" in out and "hint" not in out


def test_a_network_error_gets_no_hint(fc, tmp_path, capsys):
    def fetcher(u, p):
        raise urllib.error.URLError("name resolution failed")
    manifests = _manifest(tmp_path, "https://www.vishay.com/docs/83605/6n137.pdf", "0" * 64)
    rc = fc.run(["mod-zz"], False, corpus=tmp_path / "corpus", manifests=manifests, fetcher=fetcher)
    out = capsys.readouterr().out
    assert rc == 1 and "FAILED" in out and "hint" not in out


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


# --- workflows: the scheduled run in ci.yml and the cold corpus fetch in corpus-drift.yml -----------------------------

WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> dict:
    wf = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    wf["on"] = wf.pop(True, wf.get("on"))  # YAML 1.1 reads the bare key `on` as True
    return wf


def _action_pins(name: str) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for m in re.finditer(r"uses: ([\w.-]+/[\w.-]+)@(\S+)", (WORKFLOWS / name).read_text(encoding="utf-8")):
        pins.setdefault(m.group(1), set()).add(m.group(2))
    return pins


def test_ci_runs_on_a_schedule_inside_the_cache_expiry():
    (entry,) = _workflow("ci.yml")["on"]["schedule"]
    minute, hour, day, month, weekdays = entry["cron"].split()
    assert (day, month) == ("*", "*") and minute.isdigit() and hour.isdigit()
    days = sorted(int(d) for d in weekdays.split(","))
    assert len(days) >= 2
    gaps = [(b - a) % 7 for a, b in zip(days, days[1:] + days[:1], strict=True)]
    assert max(gaps) < 7, "a cache entry that nobody restored for 7 days is deleted"
    assert "7 days" in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_corpus_drift_workflow_is_a_cold_monthly_fetch_that_blocks_nothing():
    wf = _workflow("corpus-drift.yml")
    assert set(wf["on"]) == {"schedule", "workflow_dispatch"}
    (entry,) = wf["on"]["schedule"]
    _minute, _hour, day, month, weekday = entry["cron"].split()
    assert day == "1" and month == "*" and weekday == "*"
    assert wf["permissions"] == {"contents": "read"}
    (job,) = wf["jobs"].values()
    assert job["runs-on"] == "ubuntu-latest" and job["timeout-minutes"] <= 60
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert 'CB_CORPUS_DIR="$RUNNER_TEMP/' in runs and "python3 scripts/fetch_corpus.py" in runs
    assert "--pin" not in runs
    uses = [s["uses"] for s in job["steps"] if "uses" in s]
    assert uses and not any(u.startswith("actions/cache@") for u in uses), "cold means no cache step"


def test_corpus_drift_actions_use_the_pins_of_ci():
    ci, drift = _action_pins("ci.yml"), _action_pins("corpus-drift.yml")
    assert drift
    for action, pins in drift.items():
        assert all(re.fullmatch(r"[0-9a-f]{40}", p) for p in pins), action
        assert pins == ci[action], action


@pytest.mark.parametrize("name", ["ci.yml", "corpus-drift.yml"])
def test_workflow_comments_name_only_public_files(name):
    comments = "\n".join(line.split("#", 1)[1] for line in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines()
                         if line.lstrip().startswith("#"))
    assert "docs/" not in comments
    for path in re.findall(r"\b(?:scripts|tests)/[\w./*-]+", comments):
        assert list(ROOT.glob(path.rstrip("."))), path

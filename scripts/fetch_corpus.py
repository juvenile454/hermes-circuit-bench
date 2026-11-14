#!/usr/bin/env python3
"""Fetch pinned source files for citation tests into tests/.corpus/ (main checkout; worktrees link to it).

Manifests: tests/corpus/<name>.json = {"files": [{"url": "...", "path": "esp-idf/v6.1/esp32s3.inc", "sha256": "..."}]}
  scripts/fetch_corpus.py              all manifests
  scripts/fetch_corpus.py pins calc    only these
  scripts/fetch_corpus.py --pin pins   download and write missing sha256 values into the manifest (review them!)
A file that is present with the right hash is not downloaded again. A hash mismatch fails. A full run of all
manifests downloads about 300 MB from many hosts; name manifests to fetch a subset.

- CB_CORPUS_DIR overrides the target directory (default: <main checkout>/tests/.corpus).
- HTTP 429 and 5xx (and network errors) are retried: 6 attempts, exponential backoff with jitter (a numeric
  Retry-After is honoured, capped at 60 s). A timeout (the wall-clock deadline of 180 s per download, or a socket
  timeout) gets 2 attempts only: a host that is that slow rarely recovers within the run. A download that still fails
  is reported (FAILED) and the run goes on.
- gzip bodies (Content-Encoding: gzip, or the magic bytes 1f 8b for a path that is not itself .gz/.tgz) are
  unpacked before the SHA-256 is checked: the hash pins the file as stored.
- A module manifest mod-<name>.json may only place files under mod/<name>/.
- A file is written to a temporary name and then renamed over the target, so a hard-linked copy of the corpus keeps
  its old file.
- A hash mismatch, and an HTTP 403 or 404 (hosts that turn scripts away or move a file), print a hint to pin a
  web.archive.org snapshot (https://web.archive.org/web/<timestamp>id_/<url>) of the same document revision
  instead; a URL that already points into web.archive.org gets none. ti.com serves files under /lit/ with a new
  stamp every day, so their hash never stays the same: for such a URL the hint says so as well.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent.parent
MAIN = Path(subprocess.run(["git", "-C", str(HERE), "worktree", "list", "--porcelain"], capture_output=True, text=True,
                           check=True).stdout.split("\n", 1)[0].removeprefix("worktree "))
MANIFESTS = HERE / "tests" / "corpus"
CORPUS = Path(os.environ["CB_CORPUS_DIR"]) if os.environ.get("CB_CORPUS_DIR") else MAIN / "tests" / ".corpus"
ATTEMPTS = 6
TIMEOUT_ATTEMPTS = 2  # a timeout costs up to DEADLINE_S per attempt: fewer attempts than for 429/5xx
BASE_DELAY_S = 1.0
MAX_DELAY_S = 60.0
DEADLINE_S = 180.0  # wall clock per download: a server that trickles bytes never trips the socket timeout (CI 08.11.)
CHUNK = 1 << 16
GZIP_MAGIC = b"\x1f\x8b"
GZIP_SUFFIXES = (".gz", ".tgz", ".gzip")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def retryable(err: BaseException) -> bool:
    if isinstance(err, urllib.error.HTTPError):
        return err.code == 429 or 500 <= err.code < 600
    return isinstance(err, urllib.error.URLError | TimeoutError | ConnectionError)


def is_timeout(err: BaseException) -> bool:
    """A timeout: the wall-clock deadline of read_all, a socket timeout, or a URLError caused by one."""
    return isinstance(err, TimeoutError) or isinstance(getattr(err, "reason", None), TimeoutError)


def backoff_delay(attempt: int, err: BaseException | None = None, rand: Callable[[], float] = random.random) -> float:
    """Seconds to wait after failed attempt ``attempt`` (1-based): 1, 2, 4, 8, 16 s plus up to 100 % jitter;
    a numeric Retry-After header wins (capped)."""
    headers = getattr(err, "headers", None)
    retry_after = headers.get("Retry-After") if headers is not None else None
    if retry_after and str(retry_after).strip().isdigit():
        return min(float(retry_after), MAX_DELAY_S)
    base = BASE_DELAY_S * 2 ** (attempt - 1)
    return min(base + base * rand(), MAX_DELAY_S)


def decode_body(data: bytes, content_encoding: str | None, path: str = "") -> bytes:
    """Unpack a gzip response (header or magic bytes) unless the pinned file itself is a .gz archive."""
    if path.lower().endswith(GZIP_SUFFIXES):
        return data
    if (content_encoding or "").strip().lower() in ("gzip", "x-gzip") or data[:2] == GZIP_MAGIC:
        return gzip.decompress(data)
    return data


def read_all(r: object, url: str, clock: Callable[[], float] = time.monotonic, deadline_s: float = DEADLINE_S) -> bytes:
    """The body in chunks; TimeoutError (retried) when it takes longer than ``deadline_s`` in total."""
    start, parts = clock(), []
    while chunk := r.read(CHUNK):  # type: ignore[attr-defined]
        parts.append(chunk)
        if clock() - start > deadline_s:
            raise TimeoutError(f"download slower than {deadline_s:.0f} s")
    return b"".join(parts)


def fetch(url: str, path: str = "", *, attempts: int = ATTEMPTS, timeout_attempts: int = TIMEOUT_ATTEMPTS,
          sleep: Callable[[float], None] = time.sleep, opener: Callable[..., object] = urllib.request.urlopen,
          clock: Callable[[], float] = time.monotonic) -> bytes:
    """The body of ``url``; up to ``attempts`` attempts for 429/5xx/network errors, of which at most
    ``timeout_attempts`` may end in a timeout."""
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-circuit-bench-corpus/1"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
    timeouts = 0
    for attempt in range(1, attempts + 1):
        try:
            with opener(req, timeout=60) as r:  # type: ignore[attr-defined]
                return decode_body(read_all(r, url, clock), r.headers.get("Content-Encoding"), path)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            timeouts += is_timeout(err)
            if attempt == attempts or not retryable(err) or timeouts >= timeout_attempts:
                raise
            _close(err)
            delay = backoff_delay(attempt, err)
            print(f"retry   {url}: {err} (attempt {attempt}/{attempts}, waiting {delay:.1f} s)", file=sys.stderr)
            sleep(delay)
    raise AssertionError("unreachable")


def _close(err: BaseException) -> None:
    """Close the response body an HTTPError carries (an unclosed one warns when it is collected)."""
    if isinstance(err, urllib.error.HTTPError):
        err.close()


def ti_lit_url(url: str) -> bool:
    """A file straight from ti.com/lit/ (not an archived copy): its bytes change daily."""
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    return (host == "ti.com" or host.endswith(".ti.com")) and u.path.startswith("/lit/")


def archived_url(url: str) -> bool:
    """A web.archive.org copy: a failure there is not cured by pinning another snapshot."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host == "archive.org" or host.endswith(".archive.org")


def snapshot_hint(url: str) -> list[str]:
    """Hint lines for a document that cannot be pinned as it is (none for an archived copy)."""
    if archived_url(url):
        return []
    snapshot = f"https://web.archive.org/web/<timestamp>id_/{url}"
    lines = [f"hint    pin a web.archive.org snapshot {snapshot} of the same document revision (CONTRIBUTING.md)"]
    if ti_lit_url(url):
        lines.append("hint    ti.com re-stamps files under /lit/ daily")
    return lines


def write_atomic(target: Path, data: bytes) -> None:
    """Write to a temporary file next to ``target`` and rename it over the target (never in place)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def path_problem(manifest_name: str, rel: str) -> str | None:
    """Why ``rel`` may not be a corpus path of manifest ``manifest_name`` (None: fine)."""
    p = PurePosixPath(rel)
    if not rel or p.is_absolute() or ".." in p.parts or "\\" in rel:
        return "absolute or escaping path"
    if manifest_name.startswith("mod-"):
        wp = manifest_name.removeprefix("mod-")
        if p.parts[:2] != ("mod", wp) or len(p.parts) < 3:
            return f"files of manifest {manifest_name} belong under mod/{wp}/"
    return None


def run(names: list[str], pin: bool, *, corpus: Path | None = None, manifests: Path | None = None,
        fetcher: Callable[[str, str], bytes] | None = None) -> int:
    corpus = CORPUS if corpus is None else corpus
    manifests = MANIFESTS if manifests is None else manifests
    fetcher = fetcher or (lambda url, path: fetch(url, path))
    files = sorted(manifests.glob("*.json")) if not names else [manifests / f"{n}.json" for n in names]
    bad = 0
    for manifest in files:
        if not manifest.is_file():
            print(f"NO MANIFEST {manifest.name}")
            bad += 1
            continue
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        changed = False
        for entry in spec.get("files", []):
            problem = path_problem(manifest.stem, entry["path"])
            if problem:
                print(f"BAD PATH {manifest.name}: {entry['path']} ({problem})")
                bad += 1
                continue
            rel = Path(entry["path"])
            target = corpus / rel
            want = entry.get("sha256")
            if target.is_file() and want and sha256(target.read_bytes()) == want:
                print(f"ok      {rel}")
                continue
            try:
                data = fetcher(entry["url"], entry["path"])
            except (OSError, EOFError, ValueError) as err:  # URLError is an OSError; broken gzip: OSError/EOFError
                print(f"FAILED  {rel}: {err}")
                if isinstance(err, urllib.error.HTTPError) and err.code in (403, 404):
                    for line in snapshot_hint(entry["url"]):
                        print(line)
                _close(err)
                bad += 1
                continue
            got = sha256(data)
            if want and got != want:
                print(f"MISMATCH {rel}: expected {want}, got {got}")
                for line in snapshot_hint(entry["url"]):
                    print(line)
                bad += 1
                continue
            if not want:
                if not pin:
                    print(f"UNPINNED {rel}: sha256 {got} (run with --pin to record it)")
                    bad += 1
                    continue
                entry["sha256"] = got
                changed = True
            write_atomic(target, data)
            print(f"fetched {rel} ({len(data)} bytes)")
        if changed:
            manifest.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    pin = "--pin" in args
    sys.exit(run([a for a in args if a != "--pin"], pin))

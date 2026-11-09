"""Shared citation-excerpt parser and PDF text cache.

Excerpt format (tests/corpus/excerpts/*.txt):
- ``# key: value`` lines before the first segment are metadata (keys ``[a-z_0-9]+``: source_id, document, url,
  corpus = ``<path> sha256 <hex>``, retrieved, extracted, plus free notes); other ``#`` lines there are comments;
- ``@@ <label>`` starts a segment (``page N``: lines of pypdf's text of PDF page N; ``html``; ``lines A-B``);
- every other non-empty line belongs to the current segment, verbatim (also lines starting with ``#``).

PDF text cache: ``<corpus>/.text/<sha256>.json`` = {"pypdf": version, "pages_total": n, "pages": {"N": [lines]}}
with the lines of ``PdfReader(pdf).pages[N - 1].extract_text().split("\\n")`` (exactly what the tests compare
against); pages are added on first use, the file is replaced atomically (worktrees share the corpus). A different
pypdf version ignores the cache. Encrypted PDFs (AES, e.g. Bosch, Microchip) open with the empty user password;
that needs the dev dependency ``cryptography``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = ROOT / "tests" / "corpus"
EXCERPTS = MANIFESTS / "excerpts"
CORPUS = Path(os.environ["CB_CORPUS_DIR"]) if os.environ.get("CB_CORPUS_DIR") else ROOT / "tests" / ".corpus"
META_KEY = re.compile(r"[a-z_0-9]+")
PAGE_LABEL = re.compile(r"page (\d+)")
CORPUS_META = re.compile(r"(\S+) sha256 ([0-9a-f]{64})")


@dataclass
class Excerpt:
    name: str  # file name, e.g. "mod-env-bme280.txt"
    meta: dict[str, str]
    segments: list[tuple[str, list[str]]]
    comments: list[str] = field(default_factory=list)

    @property
    def source_id(self) -> str | None:
        return self.meta.get("source_id")

    @property
    def lines(self) -> list[str]:
        return [line for _, seg in self.segments for line in seg]

    def corpus(self) -> tuple[str, str] | None:
        """(corpus path, sha256) from the ``corpus`` header, or None."""
        m = CORPUS_META.fullmatch(self.meta.get("corpus", ""))
        return (m.group(1), m.group(2)) if m else None

    def page_segments(self, page: int) -> list[list[str]]:
        return [seg for label, seg in self.segments if label == f"page {page}"]

    def pages(self) -> list[int]:
        return sorted({int(m.group(1)) for label, _ in self.segments if (m := PAGE_LABEL.fullmatch(label))})


def parse_text(text: str, name: str = "<excerpt>") -> Excerpt:
    meta: dict[str, str] = {}
    comments: list[str] = []
    segments: list[tuple[str, list[str]]] = []
    for line in text.split("\n"):
        if line.startswith("# ") and not segments:
            key, sep, value = line[2:].partition(": ")
            if sep and META_KEY.fullmatch(key):
                meta[key] = value
            else:
                comments.append(line[2:])
        elif line.startswith("@@ "):
            segments.append((line[3:], []))
        elif segments and line:
            segments[-1][1].append(line)
    return Excerpt(name, meta, segments, comments)


def parse(path_or_name: str | Path) -> Excerpt:
    path = Path(path_or_name)
    if not path.is_absolute() and not path.exists():
        path = EXCERPTS / path
    return parse_text(path.read_text(encoding="utf-8"), path.name)


def excerpts(pattern: str = "*.txt", directory: Path = EXCERPTS) -> list[Excerpt]:
    """Every excerpt file matching ``pattern`` that carries a ``source_id`` header, sorted by file name."""
    out = [parse(p) for p in sorted(directory.glob(pattern))]
    return [e for e in out if e.source_id]


def by_source(pattern: str = "*.txt", directory: Path = EXCERPTS) -> dict[str, list[Excerpt]]:
    out: dict[str, list[Excerpt]] = {}
    for e in excerpts(pattern, directory):
        out.setdefault(e.source_id or "", []).append(e)
    return out


def manifest_entries(directory: Path = MANIFESTS, pattern: str = "*.json") -> list[tuple[str, dict[str, Any]]]:
    """(manifest stem, entry) for every file entry of every manifest, manifests sorted by name."""
    return [(m.stem, e) for m in sorted(directory.glob(pattern))
            for e in json.loads(m.read_text(encoding="utf-8")).get("files", [])]


def entry_for_path(path: str, directory: Path = MANIFESTS) -> dict[str, Any] | None:
    return next((e for _, e in manifest_entries(directory) if e.get("path") == path), None)


# --- in-order matching ---------------------------------------------------------------------------------------------
def find_parts_in_order(parts: list[str], lines: list[str]) -> bool:
    """Every part is a substring of a line, the parts in this order (not necessarily adjacent; two parts may sit on
    the same line, the second after the first)."""
    li, col = 0, 0
    for part in parts:
        while li < len(lines):
            at = lines[li].find(part, col)
            if at >= 0:
                col = at + len(part)
                break
            li, col = li + 1, 0
        else:
            return False
    return True


def lines_in_order(needles: list[str], hay: list[str], *, rstrip: bool = True) -> str | None:
    """None if every needle equals a hay line (in order, gaps allowed); else the first needle not found.
    ``rstrip``: trailing whitespace does not count (editors strip it)."""
    norm = (lambda s: s.rstrip()) if rstrip else (lambda s: s)
    pos = 0
    for n in needles:
        want = norm(n)
        while pos < len(hay) and norm(hay[pos]) != want:
            pos += 1
        if pos == len(hay):
            return n
        pos += 1
    return None


# --- PDF text ------------------------------------------------------------------------------------------------------
def open_pdf(path: str | Path):
    """pypdf reader (ImportError without pypdf). Encrypted files are opened with the empty user password."""
    import pypdf  # dev tool only, never a plugin dependency
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings, not relevant for the text layer
    return pypdf.PdfReader(str(path))  # an encrypted file is decrypted with the empty password (cryptography for AES)


def page_text(reader, page: int) -> str:
    """The exact extraction every excerpt test uses: ``reader.pages[page - 1].extract_text()``."""
    return reader.pages[page - 1].extract_text()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pypdf_version() -> str:
    import pypdf
    return pypdf.__version__


@cache
def _memory(sha: str) -> dict[str, Any]:
    return {}


class PdfText:
    """Lines of pypdf's page text for one PDF, through the on-disk cache."""

    def __init__(self, path: str | Path, sha: str | None = None, cache_dir: Path | None = None):
        self.path = Path(path)
        self.sha = sha or file_sha256(self.path)
        self.cache_file = (CORPUS / ".text" if cache_dir is None else cache_dir) / f"{self.sha}.json"
        self.version = _pypdf_version()
        self._reader = None
        self.data = _memory(self.sha)
        if self.data.get("pypdf") != self.version:
            self.data.clear()
            self.data.update(self._read_cache() or {"pypdf": self.version, "pages_total": None, "pages": {}})

    def _read_cache(self) -> dict[str, Any] | None:
        try:
            d = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) and d.get("pypdf") == self.version and isinstance(d.get("pages"), dict) else None

    def _write_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            old = self._read_cache()
            if old:  # another process may have added pages meanwhile
                self.data["pages"] = {**old["pages"], **self.data["pages"]}
            tmp = self.cache_file.with_name(f".{self.cache_file.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.cache_file)
        except OSError:
            pass  # read-only corpus: the cache is an optimisation only

    def reader(self):
        if self._reader is None:
            self._reader = open_pdf(self.path)
        return self._reader

    def pages_total(self) -> int:
        if not self.data.get("pages_total"):
            self.data["pages_total"] = len(self.reader().pages)
            self._write_cache()
        return int(self.data["pages_total"])

    def lines(self, page: int) -> list[str]:
        key = str(page)
        if key not in self.data["pages"]:
            if not 1 <= page <= self.pages_total():
                raise IndexError(f"{self.path.name}: no page {page} (1..{self.pages_total()})")
            self.data["pages"][key] = page_text(self.reader(), page).split("\n")
            self._write_cache()
        return list(self.data["pages"][key])

    def text(self, page: int) -> str:
        return "\n".join(self.lines(page))

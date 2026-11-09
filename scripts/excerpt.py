#!/usr/bin/env python3
"""Print a citation-excerpt segment from a PDF's text layer, exactly as pypdf extracts it.

  scripts/excerpt.py <pdf> --page N [--page M]... [--grep REGEX]... [--header source_id,url,retrieved] [--document TEXT]
  scripts/excerpt.py <pdf> --find TEXT

- ``--page N``: one ``@@ page N`` segment per page with the lines of ``PdfReader(pdf).pages[N - 1].extract_text()``
  (the same extraction as tests/excerpts.py), in document order, verbatim; empty / whitespace-only lines dropped.
- ``--grep REGEX`` (repeatable): keep only lines matching any of the expressions (re.search). Quote short: only the
  lines you cite.
- ``--header source_id,url,retrieved``: print the ``#`` header first (source_id, document, url, corpus path relative to
  the corpus directory with sha256, retrieved, extracted). ``--document`` sets the document line (default: the PDF's
  /Title, else a TODO).
- ``--find TEXT``: list ``page N: <line>`` for every line containing TEXT (exit 1 if none).
Encrypted PDFs (AES) open with the empty password; pypdf needs the dev dependency ``cryptography`` for them.
The corpus directory is $CB_CORPUS_DIR or <main checkout>/tests/.corpus (as in scripts/fetch_corpus.py).
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def corpus_dir() -> Path:
    if os.environ.get("CB_CORPUS_DIR"):
        return Path(os.environ["CB_CORPUS_DIR"])
    try:
        out = subprocess.run(["git", "-C", str(HERE), "worktree", "list", "--porcelain"], capture_output=True,
                             text=True, check=True).stdout
        return Path(out.split("\n", 1)[0].removeprefix("worktree ")) / "tests" / ".corpus"
    except (OSError, subprocess.CalledProcessError):
        return HERE / "tests" / ".corpus"


def open_pdf(path: Path):
    try:
        import pypdf
    except ImportError:
        sys.exit("pypdf is missing: it is a development dependency (pip install 'pypdf>=6.21.4,<7')")
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    return pypdf.PdfReader(str(path)), pypdf.__version__


def page_lines(reader, page: int) -> list[str]:
    """pypdf's lines of PDF page ``page`` (1-based), exactly as the excerpt tests split them."""
    return reader.pages[page - 1].extract_text().split("\n")


def corpus_path(pdf: Path) -> str:
    root = corpus_dir().resolve()
    real = pdf.resolve()
    try:
        return real.relative_to(root).as_posix()
    except ValueError:
        return str(pdf)


def header(pdf: Path, reader, version: str, spec: str, document: str | None) -> list[str]:
    try:
        sid, rest = spec.split(",", 1)
        url, retrieved = rest.rsplit(",", 1)
    except ValueError:
        sys.exit("--header expects source_id,url,retrieved")
    if document is None:
        try:
            title = (reader.metadata or {}).get("/Title")
        except Exception:  # noqa: BLE001 - broken metadata must not stop an excerpt
            title = None
        document = str(title).strip() if title and str(title).strip() else "TODO manufacturer, title, revision, date"
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return [
        f"# source_id: {sid.strip()}",
        f"# document: {document}",
        f"# url: {url.strip()}",
        f"# corpus: {corpus_path(pdf)} sha256 {sha}",
        f"# retrieved: {retrieved.strip()}",
        f"# extracted: pypdf {version}, PdfReader(pdf).pages[N - 1].extract_text()",
    ]


def segment(reader, page: int, greps: list[re.Pattern[str]]) -> list[str]:
    out = [f"@@ page {page}"]
    for line in page_lines(reader, page):
        if not line.strip():
            continue
        if greps and not any(g.search(line) for g in greps):
            continue
        out.append(line)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--page", type=int, action="append", default=[], help="PDF page (1-based), repeatable")
    ap.add_argument("--grep", action="append", default=[], help="keep lines matching REGEX, repeatable")
    ap.add_argument("--header", help="source_id,url,retrieved: print the '#' header first")
    ap.add_argument("--document", help="document line of the header")
    ap.add_argument("--find", help="list the pages with a line containing TEXT")
    args = ap.parse_args(argv)
    if not args.pdf.is_file():
        ap.error(f"no such file: {args.pdf}")
    if not args.page and args.find is None:
        ap.error("give --page N or --find TEXT")
    reader, version = open_pdf(args.pdf)
    total = len(reader.pages)
    if args.find is not None:
        hits = [f"page {n}: {line}" for n in range(1, total + 1) for line in page_lines(reader, n) if args.find in line]
        print("\n".join(hits) if hits else f"not found: {args.find!r}")
        return 0 if hits else 1
    try:
        greps = [re.compile(g) for g in args.grep]
    except re.error as e:
        ap.error(f"bad --grep: {e}")
    bad = [p for p in args.page if not 1 <= p <= total]
    if bad:
        ap.error(f"page {bad[0]} out of range 1..{total}")
    out: list[str] = header(args.pdf, reader, version, args.header, args.document) if args.header else []
    for p in args.page:
        out.extend(segment(reader, p, greps))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Test helpers are imported by module name (``import modkit``), never through a ``tests`` package: the Hermes
tests run next to the Hermes checkout, whose own ``tests`` package would shadow ours."""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BAD = re.compile(r"^\s*(from\s+tests(\.|\s+import)|import\s+tests\b)", re.M)


def test_no_test_file_imports_the_tests_package():
    assert [p.name for p in sorted(TESTS.glob("*.py")) if BAD.search(p.read_text(encoding="utf-8"))] == []

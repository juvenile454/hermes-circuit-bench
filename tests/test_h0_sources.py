"""The sources of the shared-bus rule are known and quoted from the pinned files."""
import hashlib
import json
import logging
from pathlib import Path

import pytest

from circuit_bench.bench_core import sources

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / ".corpus"
SPI_RST = "esp-idf/v6.1/docs/en/api-reference/peripherals/spi_master.rst"
SPI_QUOTE = ("Each Device shares the MOSI, MISO, and SCLK signals but is only active on the bus when the Host asserts "
             "the Device's individual CS line.")
I2C_QUOTES = {3: "Each device connected to the bus is software addressable by a unique address",
              4: "The number of ICs that can be connected to the same bus is limited only by a maximum bus capacitance."}


def _squash(s: str) -> str:
    return "".join(s.split())


def test_sources_known():
    assert "spi_master.rst" in sources.get("idf-v6.1-spi-master")["url"]
    assert "pages 3-4" in sources.get("nxp-um10204")["note"]


def test_manifest_pins_the_spi_page():
    spec = json.loads((ROOT / "corpus" / "harden.json").read_text(encoding="utf-8"))
    [entry] = spec["files"]
    assert entry["path"] == SPI_RST and entry["source_id"] == "idf-v6.1-spi-master" and len(entry["sha256"]) == 64
    assert "fff9895c82d744c7237be8847347bdd1b07c6643" in entry["url"]


def test_excerpt_carries_the_i2c_quotes():
    text = _squash((ROOT / "corpus" / "excerpts" / "calc-nxp-um10204.txt").read_text(encoding="utf-8"))
    for quote in I2C_QUOTES.values():
        assert _squash(quote) in text


@pytest.mark.corpus
def test_spi_quote_in_pinned_rst():
    path = CORPUS / SPI_RST
    if not path.is_file():
        pytest.skip("corpus file missing (scripts/fetch_corpus.py harden)")
    spec = json.loads((ROOT / "corpus" / "harden.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == spec["files"][0]["sha256"]
    assert SPI_QUOTE in path.read_text(encoding="utf-8")


@pytest.mark.corpus
def test_i2c_quotes_in_pinned_pdf():
    pypdf = pytest.importorskip("pypdf")  # dev tool only
    pdf = CORPUS / "calc" / "nxp-um10204-rev7.pdf"
    if not pdf.is_file():
        pytest.skip("corpus file missing (scripts/fetch_corpus.py calc)")
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = pypdf.PdfReader(str(pdf))
    for page, quote in I2C_QUOTES.items():
        assert _squash(quote) in _squash(reader.pages[page - 1].extract_text()), page

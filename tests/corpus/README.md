# Corpus manifests

The citation tests check pinned values in `circuit_bench/data/` against the documents they cite. This folder holds
what the tests need for that, not the documents themselves.

## Layout

- `<name>.json`: one manifest per topic (`pins`, `boards`, `calc`, `electrical`, `mod-<family>`, …), read by
  `scripts/fetch_corpus.py`. Each entry has the download `url`, the local `path`, the file's `sha256` and usually a
  `source_id` that links it to `circuit_bench/data/sources/`. A `note` says when the URL is a mirror or a redirect
  of the maker's address.
- `excerpts/`: short text excerpts of the sources. `#` lines are metadata (source id, document title and version,
  URL, SHA-256 of the pinned file, retrieval date, extraction method); segments start with `@@ page N` (or
  `@@ lines A-B`) and hold whole lines copied verbatim from that page or file.

`scripts/fetch_corpus.py` downloads the pinned files into `tests/.corpus/` (git-ignored) and fails on a hash
mismatch. Tests that need them are marked `corpus` and skip when a file is missing; CI fetches the corpus first.
For a PDF source, commit a text excerpt under `excerpts/` and pin the PDF's SHA-256 in the manifest.

## Provenance and licences

The full documents are not part of this repository; only the excerpts are. By kind of source:

- **Manufacturer datasheets, application notes and product pages** (Espressif, TI, Microchip, NXP, Bosch
  Sensortec, Vishay, Sensirion, onsemi, Infineon, Wireless-Tag and others): short excerpts of the lines a value rests
  on, quoted for citation and test purposes. Copyright stays with the manufacturer. URL, document version,
  retrieval date and the SHA-256 of the exact file are in the excerpt header and the manifest. Where the maker's own
  URL is gone or blocks downloads, the manifest points to a Wayback Machine copy (`web.archive.org`) or to a copy
  hosted by a third party (for example SparkFun or Adafruit), and the source entry says so.
- **Source code and documentation on GitHub** (espressif/esp-idf, espressif/esp-dev-kits, espressif/esptool,
  platformio/platform-espressif32): fetched from `raw.githubusercontent.com` at a pinned commit, under the licence
  of each repository. Nothing from these repositories is copied into this folder; esptool (GPL-2.0) is read as a
  text file only and never imported.
- **Wikipedia** (`excerpts/calc-eseries-wikipedia.txt`): lines of the article
  [E series of preferred numbers](https://en.wikipedia.org/w/index.php?title=E_series_of_preferred_numbers&oldid=1383955633),
  revision 1383955633, for the IEC 60063 E-series values. Wikipedia text is licensed under
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); the excerpt stays under that licence and names
  its source.

Rights holders who want an excerpt changed or removed can open an issue.

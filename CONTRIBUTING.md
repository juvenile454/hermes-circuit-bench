# Contributing to Circuit Bench

Thanks for helping. Circuit Bench gives people pin verdicts and part values they build real circuits from, so the
bar is: every fact has a source, every value is computed in code, and nothing touches real hardware unasked.

AI coding agents: read [AGENTS.md](AGENTS.md) first; it lists the same rules in short form.

## Ground rules

- **Low voltage only.** 3.3/5 V logic and small DC loads. No mains (230 V/120 V) circuits, examples or calculators.
- **Facts need a source.** A new pin rule, limit, module value or solder hint needs a URL and a retrieval date in
  `circuit_bench/data/sources/`, and a short verbatim excerpt of the lines it rests on (see below). Something you
  could not verify is a hint, never a rule.
- **Code computes, the model does not.** Values come from `circuit_bench/bench_core/`; results carry units,
  assumptions and sources. Only `passed` counts as checked.
- **No downloads at runtime, no binaries in the repository.** The plugin never fetches rules or toolchains and never
  updates itself. `pio`, `esptool` and `addr2line` are the user's tools and are called as CLI programs only;
  esptool (GPL-2.0) is never imported.
- **Synthetic test data only.** No real MAC addresses, USB serial numbers, IP addresses, names or paths in fixtures
  and logs; use the synthetic values the tests already use.

## Development setup

Linux or macOS, Python ≥ 3.11, Node 22, [uv](https://docs.astral.sh/uv/). Use a clean environment (no `PYTHONPATH`
pointing into another installation).

```
uv venv .venv && . scripts/dev_deps.sh
uv pip install --python .venv/bin/python -r circuit_bench/pyproject.toml $DEV_DEPS
.venv/bin/python scripts/fetch_corpus.py   # cold: about 300 MB from many hosts, about 15 minutes
```

To fetch only some manifests, name them, e.g. `.venv/bin/python scripts/fetch_corpus.py mod-iox mod-npower`. Tests
marked `corpus` skip when their files are missing.

## Checks before a pull request

```
.venv/bin/ruff check .
CIRCUIT_BENCH_HW=off .venv/bin/python -m pytest tests
node --test tests-js/*.mjs
node scripts/build-desktop.mjs --check
```

CI runs the same on Python 3.11 and 3.14 and with the lowest declared dependency versions, runs pytest, the node
tests and the build check on macOS, and validates the plugin against the Hermes releases in its matrix.

## Hardware safety in tests

Tests never open real serial ports and never run real `pio`, `esptool` or `addr2line`: `tests/conftest.py` sets
`CIRCUIT_BENCH_HW=off` and an audit hook refuses real serial devices and tool processes for the whole session. Use
the simulated board (`sim://esp32s3-n16r8`) and the fake CLIs in `tests/fakes/`. Tests marked `toolchain` run real
offline builds and `addr2line` only when you opt in with `CB_TOOLCHAIN_TESTS=1`. Never add a test that uploads,
flashes or erases.

## Sources and excerpts

1. Add the source entry (`id`, `title`, `url`, `retrieved`, `note`; module sources also `class`) to the matching
   file in `circuit_bench/data/sources/`.
2. Pin the document in a manifest under `tests/corpus/` (URL, local path, SHA-256) and fetch it with
   `scripts/fetch_corpus.py`.
3. Write the excerpt with `scripts/excerpt.py <pdf> --page N --grep REGEX --header source_id,url,retrieved` into
   `tests/corpus/excerpts/`; quote only the lines you cite.
4. Cite the source id next to the value. The citation tests check that the quoted lines are in the pinned file.

Details and licences: [tests/corpus/README.md](tests/corpus/README.md). Pin data is generated from the pinned
ESP-IDF sources by `scripts/gen_pins.py` (`--check` compares); do not edit `circuit_bench/data/pins/` by hand.

## When a pinned file no longer matches

A pinned vendor file can change after it was pinned: the vendor serves a newer revision, refuses downloads from
scripts, answers `404`, or re-stamps the file daily (`ti.com` does for files under `/lit/`: the bytes change from day to
day). Then `scripts/fetch_corpus.py` reports a hash mismatch, or an HTTP `403` or `404`, and prints a hint pointing
here. The monthly workflow `corpus-drift.yml` is configured to fetch every pinned file cold (no cache) and to fail in
the same way; it blocks no push or pull request.

1. Find a [Wayback Machine](https://web.archive.org/) capture of **the same document revision** that the value and the
   excerpt rest on. Check the revision on the document itself (revision or date on the first page) and every quoted
   line; a capture of a newer revision is a new source, not a replacement: its values need the full review above.
2. Use the raw form `https://web.archive.org/web/<timestamp>id_/<url>` (14-digit timestamp, `id_` after it). It serves
   the original bytes, without the banner and the link rewriting of the archive's viewer.
3. In the manifest under `tests/corpus/`, set `url` to that address and remove the old `sha256`. Run
   `scripts/fetch_corpus.py --pin <name>` and review the value it writes. `<name>` is the manifest's file name without
   folder and `.json` (`mod-prox` for `tests/corpus/mod-prox.json`); a path is not accepted. The SHA-256 is that of the
   unpacked file (a gzip body is unpacked before it is hashed). If the archived file is byte for byte the one you
   pinned before, the hash is unchanged.
4. Check every quoted line again against the archived file. The citation tests (`pytest -m corpus`) compare the
   excerpt with the pinned file; where the file's text differs, regenerate the excerpt with `scripts/excerpt.py` and
   read it. Update `url`, `corpus` (path and SHA-256) and `retrieved` in the excerpt header.
5. Update the source entry in `circuit_bench/data/sources/`: `url`, `retrieved` and the note (name the snapshot and
   the SHA-256). In the module catalog sources (`circuit_bench/data/sources/mod-*.json`) also update `class`: **A** is
   the manufacturer's own file from the manufacturer's domain; **A1** is that same file served only as a
   `web.archive.org` copy, so a module source that was **A** and is now reachable only as an archive copy becomes
   **A1**; **A2** is a manufacturer document hosted by a third party (title "copy hosted by …"); **B** is no
   manufacturer document, a preliminary version, or a module seller. A, A1 and A2 may support a `danger` verdict,
   **B** at most an `info` marked unverified. A snapshot never raises a class: A2 and B stay as they are. Source
   files outside the module catalog (for example `electrical.json`) keep their class; the note names the snapshot.
6. Run the checks above and say in the pull request which files you re-pinned and why.

## Desktop half

- Edit `desktop-src/`, then run `node scripts/build-desktop.mjs`. `circuit_bench/desktop/plugin.js` is generated;
  never edit it by hand. The product bundle must stay below 760 KB (the build check fails above).
- Use the Hermes Desktop plugin SDK only: your own DOM, class names with the `cb-` prefix, no selectors on app
  markup, no patching of app objects.
- The UI is English only for now.

## Agent tools

Tool schemas live in `circuit_bench/schemas.py`: one description per tool of at most 500 characters, budgets are
checked by the tests. Every action returns the result envelope described in the README ("How it works").

## Repository layout

| Path | Contents |
|---|---|
| `circuit_bench/` | the plugin as Hermes installs it (`plugin.yaml`, tools, hook, command, skill, Desktop half) |
| `circuit_bench/bench_core/` | plain Python core without Hermes: pins, calculators, schematics, solder, board, crash |
| `circuit_bench/data/` | pin, board, module and source data, demo project, simulated logs, example firmware |
| `circuit_bench/dashboard/` | backend routes of the Desktop half |
| `desktop-src/` | source of the Desktop half (built into `circuit_bench/desktop/plugin.js`) |
| `tests/`, `tests-js/` | Python and Node tests; `tests/corpus/` holds manifests and excerpts of the cited sources |
| `scripts/` | build, corpus fetch, excerpt and generator scripts; `scripts/banner/` builds the catalog banner |

Test file prefixes (`m0`, `p0`, `fix1`, …) are historical; name new test files after their topic.

## Pull requests

- One topic per pull request; describe what changes for the user and how you tested it.
- Add a line to `CHANGELOG.md` for anything a user can notice.
- By contributing you agree that your contribution is licensed under the MIT License of this repository. Datasheet
  excerpts stay with their rights holders.

## Security

Please do not open public issues for security problems; see [SECURITY.md](SECURITY.md).

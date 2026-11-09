# AGENTS.md

Guide for AI coding agents working in this repository. Humans: see [CONTRIBUTING.md](CONTRIBUTING.md), which has
the same rules with more detail.

## What this is

Circuit Bench, a Hermes Agent plugin for ESP32 work: pin checks, part calculators, schematics, solder order,
PlatformIO build and esptool flash, serial monitor and crash decoding. People build real circuits from its answers.

- `circuit_bench/`: the plugin as Hermes installs it; `circuit_bench/bench_core/` is plain Python without Hermes.
- `circuit_bench/data/`: pin, board, module and source data. `desktop-src/`: source of the Desktop half.
- `tests/`, `tests-js/`: Python and Node tests. `tests/corpus/`: manifests and excerpts of the cited sources.

## Never

- Open a real serial port, or run `pio run -t upload`, `esptool` write/erase commands or anything else that touches
  a connected board. Use the simulated board `sim://esp32s3-n16r8`.
- Import esptool (GPL-2.0); call user tools only as CLI programs, without a shell.
- Add a rule, limit or value without a source (URL, retrieval date) and a verbatim excerpt; never "fix" a test by
  changing a cited value.
- Edit `circuit_bench/desktop/plugin.js` or `circuit_bench/data/pins/` by hand; they are generated.
- Add binaries, downloads at runtime, self-updates or telemetry.
- Add mains-voltage (230 V/120 V) circuits, examples or calculator ranges.
- Put real MAC addresses, USB serial numbers, IPs, names or home paths into fixtures, logs or docs.

## Always

- Run tests with `CIRCUIT_BENCH_HW=off` (`tests/conftest.py` enforces it and refuses real devices).
- Compute values in code, with units, assumptions and sources in the result; never let the model compute them.
- Keep public texts, tool descriptions and UI strings in English; tool descriptions stay within 500 characters.
- Before you report back, run:

```
.venv/bin/ruff check .
CIRCUIT_BENCH_HW=off .venv/bin/python -m pytest tests
node --test tests-js/*.mjs
node scripts/build-desktop.mjs --check
```

- Rebuild the Desktop half after changes in `desktop-src/` (`node scripts/build-desktop.mjs`) and keep it below the
  bundle budget.
- Add a `CHANGELOG.md` line for changes a user can notice.

Sources, excerpts and their licences: [tests/corpus/README.md](tests/corpus/README.md). Security issues go to
[SECURITY.md](SECURITY.md), not into public issues.

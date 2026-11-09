## What and why

<!-- What changes for the user, and why. Link the issue if there is one. -->

## How it was tested

<!-- Commands you ran, and anything you checked by hand (simulated board only). -->

## Checklist

- [ ] `ruff check .`, `pytest tests` (with `CIRCUIT_BENCH_HW=off`), `node --test tests-js/*.mjs` and
      `node scripts/build-desktop.mjs --check` pass
- [ ] Tests added or updated for the change
- [ ] New rules or values have a source (URL, retrieval date) and an excerpt in `tests/corpus/excerpts/`
- [ ] `circuit_bench/desktop/plugin.js` rebuilt with `scripts/build-desktop.mjs`, not edited by hand
- [ ] No real device identifiers (MAC, USB serial number, IP) in logs, fixtures or screenshots
- [ ] `CHANGELOG.md` updated if a user can notice the change

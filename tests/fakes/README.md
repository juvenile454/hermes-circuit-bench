# Fake command line tools

`tests/fakes/bin/` is the first entry on `PATH` in every test (`tests/conftest.py`). Real `esptool`, `pio`
and `*-addr2line` are refused by the audit hook; fakes in this folder are allowed.

Pattern for a fake (each fake extends its own file):
- executable Python script with `#!/usr/bin/env python3`, named like the real tool;
- behaviour comes from a JSON scenario file named in `CB_FAKE_SCENARIO`
  (`{"<subcommand>": {"rc": 0, "stdout": "...", "sleep": 0}}`);
- the fake appends its argv as one JSON line to `CB_FAKE_ARGV_LOG` if that is set, so tests can assert the
  exact command line (e.g. the `write-flash` offsets and images of `board.flash`).

`cb-fake-tool` below is the reference implementation of that pattern.

Note: `clitools.run` passes only PATH, HOME, TMPDIR, USER, LOGNAME and PLATFORMIO_* to tools. Fakes called through
`clitools.run` therefore get their scenario another way: pass it with `env_extra={"CB_FAKE_SCENARIO": ...}`, or (as
the addr2line fakes do) read `<ELF>.a2l.json` next to the ELF given with `-e` (it may name an `argv_log`).
`riscv32-esp-elf-addr2line` is a symlink to the xtensa fake; the fake derives its prefix from argv[0].
`tests/fakes/bin/esptool` and `pio` also read `cb-fake-scenario.json` next to argv[0] and log their argv
there; the fixture `fake_tools` in `tests/board_fixtures.py` links them into a temporary bin folder per test.

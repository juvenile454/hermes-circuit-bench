# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/juvenile454/hermes-circuit-bench/security/advisories/new) (repository
tab **Security → Report a vulnerability**). Do not open a public issue for them.

Include the Circuit Bench version (or commit), the Hermes version, your OS, what you did and what happened. Leave
out MAC addresses, serial numbers and other details of your own devices unless they are needed to reproduce the
problem. The maintainer aims to reply within seven days; fixes ship as a new release and a new pinned commit in the
Hermes plugin catalog.

## Supported versions

Only the latest release (currently 0.1.x) gets fixes.

## In scope

- A way to flash, erase or open a real serial port without the approvals and switches described below.
- A way to start PlatformIO (a build, or any call that runs a project's scripts) from the agent without Hermes
  asking (outside the documented `/yolo`, `hermes -z` and `approvals.mode: off` cases).
- Path traversal or writes outside `$HERMES_HOME/plugin-data/circuit-bench/`, the firmware folder you chose or the
  `out_dir` you named.
- The Desktop half reaching beyond the Hermes Desktop plugin SDK, or its backend routes answering without the app's
  session token.
- Wrong safety-relevant output, for example a missing low-voltage, laser or lithium-cell warning.

Out of scope: problems in Hermes itself, PlatformIO, esptool or the Espressif toolchains (report them upstream),
and the code of a firmware project you build: a build runs that project's scripts by design.

## Security model

1. Every agent build that starts PlatformIO, every real flash, and every board detection and monitor while **Ask
   before opening serial ports** is on (the default), goes through Hermes' approval; a `pre_tool_call` hook asks or
   blocks and never approves by itself. Cron jobs cannot run such builds, nor flash, detect or monitor real boards.
2. **Allow flashing real boards** is off by default; a flash writes only the approved, unchanged build to the
   detected board (port, MAC and firmware hash are checked again by the tool).
3. **Access real hardware** off, or `CIRCUIT_BENCH_HW=off`, makes real ports unreachable; only `sim://` boards
   remain.
4. The plugin makes no network calls, never updates itself, sends no telemetry and stores no credentials.
5. Low voltage only (3.3 V and 5 V logic, small DC loads); calculators refuse inputs above 60 V and no part of
   Circuit Bench covers mains wiring.

Known gap: A session-scoped `/yolo` and one-shot runs (`hermes -z`, which bypass approvals by design) are not visible
to plugins: there Hermes passes agent builds, flashes and port openings without asking. Keep **Allow flashing real
boards** off while you use them. The full list is in the README sections "Safety" and "Disclosure".

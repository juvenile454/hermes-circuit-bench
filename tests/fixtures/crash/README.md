# Crash fixtures (synthetic)

Synthetic serial logs for `tests/test_crash_*.py`, written by hand after the examples in ESP-IDF v6.1
(Fatal Errors for ESP32-S3 and ESP32-C3, Watchdogs, Error Handling, IDF Monitor) and the v6.1 sources that print
them (`circuit_bench/data/sources/crash.json`). Addresses, task names and paths are made up; no real device logs.
`*.a2l.json` are scenario files for the fake `*-addr2line` (`tests/fakes/bin/`), keyed by address.
The `ELF file SHA256:` line follows `panic.c`/`esp_app_desc.c` of v6.1 and is **unverified** until checked against
real logs from HW-1.

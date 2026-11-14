# Changelog

All notable changes to Circuit Bench. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.1.1] — 2026-11-14

Safety and accuracy fixes to the agent half, two small additions to the calculators, and the source files of the
citation tests pinned again. No new tools, no new dependencies, no new network access. One run on a real board
(detect, build, flash, monitor and crash decode on an ESP32-S3 over its native USB port, Linux); apart from that the
flash and serial paths were tested with fake tools and a simulated board.

### Fixed

- **Unreadable plugin settings no longer turn real hardware on.** In 0.1.0, when the plugin settings could not be
  read from Hermes' configuration, the plugin used its defaults, which include `hardware_access: true`. Now real
  hardware and flashing stay off (`hardware_access` and `allow_flash` `false`) and port approval stays on
  (`approve_serial` `true`), while numbers and paths keep their defaults. `/bench doctor` marks the check `settings` as
  `FAIL` (the Bench's doctor dialog shows it as a failed row) and shows the warning `settings_unreadable` (it starts
  with `the plugin settings could not be read from Hermes' configuration, so real boards stay off`), and agent calls for
  real boards end with `sim_only` and a hint that names the cause. A readable configuration without an entry for the
  plugin still gives the defaults.
- **Agent handlers are tied to the approval hook.** `bench_board` `detect`, `monitor` and `flash` on a real port, and
  a `build` that starts PlatformIO (a real build, or a `sim://` build when `pio` and every package it needs are
  installed), now run only if the plugin's approval hook let exactly that call through for the same task, action and
  target; otherwise the tool answers `not_confirmed`. One hook pass serves one run, also when no question is asked
  (**Ask before opening serial ports** off). In 0.1.0 only a flash was tied to the question; the other three only
  checked that the hook was registered.
- **Shorter life for the approval record.** The record that lets a handler run now lives `approvals.timeout` + 60 s,
  kept between 120 and 3600 s (360 s when the setting is absent, unreadable or no number); in 0.1.0 a flash
  record was stored before the question and kept for 3600 s. Every hook pass first removes the unused records of its
  task, one record serves one handler run, and a pass that blocks, needs no record or fails inside leaves none behind.
- **Flash writes from a private snapshot.** `bench_board flash` (agent tool and Bench) now copies every file it will
  write into a private folder `tmp/flash-<random>` in the plugin data folder (mode `0700`, files `0600`), compares
  the copies with the hashes recorded at build time (`elf_mismatch` on a difference), passes only the copies to
  `esptool`, and removes the folder on every exit (a folder left behind by a killed process is removed by a later
  flash once it is older than an hour); a file that cannot be copied ends the flash with `tool_failed` before
  `esptool` starts. Every written file named `firmware.bin`, `bootloader.bin` or `partitions.bin` (compared
  without case) is checked at its private copy, whatever folder or spelling PlatformIO's metadata names it by. In
  0.1.0 these files were hashed in the build folder and then written from there. `boot_app0.bin` and extra images of a
  project have no recorded hash and are written as they were when copied; see SECURITY.md, "Known gaps".
- **Flash approval covers the build.** The approval record of an agent flash holds the images and the time of the last
  build as well as the ELF, port and MAC; a build made while the question is open is not flashed: the same ELF with
  other images or time ends with `not_confirmed`, another ELF with `elf_mismatch`.
- **Approval questions show hidden characters and long paths, and put the folder last.** In 0.1.0 the folder name went
  into the question for a build or a flash unshortened and unfiltered. Now the question starts with its fixed wording
  and the checked values (env, chip, MAC, port, ELF hash), and the firmware folder, the only free text, comes last and
  in quotes (`Firmware folder: "<path>"` for a flash, `Folder: "<path>"` for a build), so a folder name cannot read
  like the rest of the question. Control characters, line breaks, Unicode direction marks, space variants other than
  U+0020, every `Default_Ignorable_Code_Point` (zero-width characters, variation selectors and others) and `"` are
  shown as `\uXXXX` (`\UXXXXXXXX` above U+FFFF). In the folder every other quotation mark (all characters with the
  Unicode property `Quotation_Mark` except the apostrophe U+0027) and the characters that look like `"` (primes and a
  few others) are shown that way too, so nothing in a folder name can look like the end of the quoted field; a folder
  `Lab’s` (typographic apostrophe, U+2019) now appears as `Lab\u2019s`. Letters stay as they are: look-alike letters,
  and letters of right-to-left scripts, which can change the displayed order of the path parts in a folder name. The
  chip shows only its fixed name and revision. A path longer than 120 characters is shortened in the middle, also in its
  last part, so the shown path is never longer than 120 characters, and the question then ends with ` (path shortened)`,
  which also appears when a character was only replaced. The rule key for "always" of a build still uses the full folder
  path and the env; that of a flash is made of port, MAC and ELF hash. A build env that is no PlatformIO name is refused
  before the question.
- **Detect and monitor questions show the port strictly and refuse port URLs first.** In 0.1.0 the port went into the
  question of a detection or a serial monitor unfiltered, and a port URL other than `sim://` was only refused by the
  handler after the user had approved: `x:// on sim://esp32? Simulated board, nothing is reset. OK` appeared in the
  question `Detect the board on … with esptool?`. Now the port in all three questions (flash, detect, monitor) keeps
  only letters, digits and `._:/-` as they are and shows every other character as `\uXXXX`, so
  `/dev/ttyACM0?Simulated,nothing-is-reset.OK` appears as `/dev/ttyACM0\u003fSimulated\u002cnothing-is-reset.OK`. A
  port URL other than `sim://` is blocked by the hook before the question, for a detection, a monitor and a flash,
  also when **Ask before opening serial ports** is off, with the words of the handler: `Circuit Bench blocked board
  detection: unsupported port URL 'rfc2217://h:1' (invalid_args); use a local device path or a sim:// port.` (`the
  serial monitor` or `the flash` in place of `board detection`). The question and the rule key of a normal port such as
  `/dev/ttyACM0` or `COM3` are unchanged.
- **Messages to the model show hidden characters.** The message and hint of an error answer and the message of a block
  by the hook show format and direction characters, line and paragraph separators, lone surrogates, DEL, C1 controls
  and every `Default_Ignorable_Code_Point` as `\uXXXX`; input is not refused for them. Spaces such as the no-break
  space stay as they are. Warnings, assumptions and serial lines are unchanged.
- **Hint for a call without an approval pass.** When the approval hook is active but a call has no pass of it (expired,
  or another task), the error hint says `call bench_board <action> again: Hermes asks the user first; sim:// ports
  still work`.
- **A simulated build without `pio` no longer reports `chip_unchecked`.** A simulated build (`sim://` port) that does
  not start PlatformIO, because `pio` or a package it needs is missing, compiles nothing, so the info warning is gone.
  A wrong chip is still refused, other warnings stay, and builds that do start `pio` keep their pre-check.
- **Names with a trailing line break are refused.** The name checks ended in `$` and were applied with `re.match`, and
  `$` also matches right before a final line break: a build env such as `s3` followed by a line break passed the check
  and `board.build` started `pio` with it, and `project.create` accepted a project id with a final line break and
  created a project whose id and folder name contain it. The input checks of the core now compare the whole text
  (`fullmatch`), so these names, and the same ending in other checked texts (ISO times, serial port names, event
  names, pin roles and others), are refused with `invalid_args`. Valid names are unchanged. The agent tool
  `bench_board` removes outer whitespace from its text arguments before any check, so an env given there with a
  trailing line break reaches the question, the rule key and the build as the plain name; an env with a line break
  inside is blocked by the hook before the question.
- **Pin labels for modules.** `add_module`, `connect` and `add_parts` (with a module) now accept common breakout
  labels in `conn` and map them to a pin of the catalog entry, so `conn={SDA, SCL, GND}` works for `bme280` where
  0.1.0 refused `SDA`. Bus labels (`SDA`, `SCL`, `SCK`/`SCLK`/`CLK`, `MOSI`/`SDI`/`DIN`/`SI`, `MISO`/`SDO`/`DOUT`/`SO`,
  `CS`/`SS`/`NSS`/`CSN`) count when exactly one pin of the module's active variant carries that signal and no other
  pin's name starts with the label; `VCC`/`VDD` and `GND`/`VSS` only stand in for each other. A real pin name always
  wins (on the `l298n`, `VSS` is the logic supply, not ground). An ambiguous label is refused with its candidates, for
  example `'CLK' fits more than one pin of enc28j60 (CLKOUT, SCK): name the pin`; `VCC` is refused the same way on a
  module with two supply pins, such as `bme280` (`VDD`, `VDDIO`), so `conn={SDA, SCL, VCC, GND}` still needs `VDD` and
  `VDDIO` named. The project stores the catalog pin name, and every mapping appears in the answer under `assumptions`
  with code `pin_alias`, for example `SDA → SDI` (`bme280: I²C data pin, catalog pin SDI (SDA in I²C mode)`).
- **`ads1220` gets its serial clock pin.** The catalog entry had no pin for the SPI clock input; it now has `SCLK`
  (datasheet p. 4), so `SCK` and `SCLK` map to it. `CLK` stays the external clock input. A test now requires a clock
  pin for every entry with SPI and data and clock pins for every entry with I²C.
- **Pin-current note names the comparison.** The LED and NPN calculators no longer say `GPIO current limits are not
  checked here (unverified)` when the pin current can be compared: at or below the ESP32-S3 value the `gpio_current`
  note (`info`) now reads `The driving pin sources 10.0 mA, below the 40.0 mA high-level source current of an ESP32-S3
  pin (a typical value, not a maximum; chip not given).` Above that value it stays the caution `The driving pin would
  have to source …`, and without pin data the old sentence stays. A current that is a little above or below the limit
  but would round to it shows more digits (`39.9996 mA, below the 40.0 mA …`).
- **Unknown part numbers name the closest known part.** The message now says which known part is most similar and that
  it is a different type with its own ratings, for example `no datasheet data for part '2N2222' (closest: 2N2222A, a
  different type with its own ratings; known: 2N2222A)`. The calculation does not use the data of that part, and no
  alias is created.
- **`unknown_board` says what to do next.** Its hint lists the known boards and ends with `or leave devkit out: the
  chip checks still run, pins.broken_out and pins.board are skipped`. Where a board is asked for by id (the Bench's
  board layout), `devkit` cannot be left out, so the hint only lists the boards.

### Changed

- `bench_calc divider` takes a new optional input `target` with the values `esp_pin` (default) and `other`. With
  `target=other` the check `calc.divider.pin_max` is `not_checked` (`the output does not feed an ESP pin
  (target=other)`) and the warning `divider_overvoltage` is not raised, so a 12 V → 5 V divider (7k/5k) that feeds
  something other than an ESP pin no longer reports a failed check and a `danger` warning. With `target=other` the
  pin limit is not applied: check the limit of whatever the divider feeds. Without `target` the answer is unchanged.
- `led_strip` gives a second, larger current as a planning value for `ws2812b`: 60 × `WS2812B` at 5 V still show
  `2.20 A` from the datasheet test condition, and the answer adds `result.i_planning` of `3.60 A` (60 mA per pixel at
  full white; source class B, `rule of thumb, worst case at full white, not a datasheet value`) and says to size the
  supply for the larger current. `apa102c` has the same planning value, which equals its datasheet value at full
  brightness (`brightness` 1, the default: `3.60 A` for 60 pixels) and is the larger one below it; its summary also
  says to size the supply for the larger current. `sk6812` has no planning value and answers as before. The warning
  `high_current` (from 1 A) uses the larger value and names the planning value only when that is the larger one, not
  for `apa102c` at full brightness (`3.60 A at full setting (rule of thumb, worst case at full white, not a datasheet
  value: 60.0 mA per pixel): …`).
- The agent's serial monitor now listens at most for Hermes' deadline for a tool call minus 20 s, and never shorter
  than 1 s; the deadline is `timeouts.tools.sequential_call`, else `timeouts.tools.concurrent_batch`, else the
  environment variable `HERMES_CONCURRENT_TOOL_TIMEOUT_S`, else 420 s. A shortened run carries the warning
  `monitor_capped` (`info`), for example with `monitor_max_seconds` at `3600` and a call for 3000 s: `the monitor was
  shortened from 3000 s to 400 s: Hermes ends a tool call after 420 s (Hermes default) and 20 s are kept free for
  the answer; listen again to see more`. The `monitor_max_seconds` limit (default `120`, valid `1` to `3600`)
  applies first. This is the agent path only; the Bench console and stream are
  not affected.
- Eight cited vendor files that could no longer be fetched as pinned (a newer revision is served, the vendor refuses
  script downloads or answers `404`, or the file is re-stamped) are now pinned to `web.archive.org` copies of the same
  document revision; the matching sources carry `retrieved` `2026-11-13`. For the ESP32-C3, ESP32-C6, ST7735S,
  GC9A01A and 6N137 datasheets the archived file has the same SHA-256 as before; the DRV5032 datasheet and two
  WT32-ETH01 wiki pages have a new pinned SHA-256. Fetching the whole corpus cold into an empty folder was verified
  locally on 2026-11-13. When `scripts/fetch_corpus.py` finds a hash mismatch or an HTTP `403` or `404` for a pinned
  file, it now suggests a `web.archive.org` snapshot for every vendor (see CONTRIBUTING.md).
- CI is configured to run on a schedule, Mondays and Thursdays at 04:17 UTC, so there are never more than four days
  between two runs; this keeps the cached test corpus alive, because GitHub deletes a cache entry that nobody restored
  for 7 days.
- A new workflow, `corpus-drift.yml`, is configured to fetch every pinned source file of the citation tests cold (into
  an empty directory, with no cache) on the 1st of each month and on a manual run. A hash mismatch, a `403` or a `404`
  fails that run. Nothing else depends on it, so a red run blocks no push or pull request.
- CI is configured to also test against Hermes v0.23.1 (commit `3b421578588243f920886e6fe79a6faa87ea026e`) in
  addition to v0.22.5 and v0.23.0, and the macOS job runs on v0.23.1. Each Hermes checkout is compared with the commit
  SHA of its release tag, so a moved tag fails the job. The minimum stays Hermes ≥ 0.22.5. The plugin's end-to-end
  probe also passed locally against Hermes v0.22.5, v0.23.0, v0.23.1 and Hermes main.

## [0.1.0] — 2026-11-10

First release: an agent half for Hermes and an optional Desktop half for Hermes Desktop. Requires Hermes ≥ 0.22.5;
validated in CI against Hermes v0.22.5 and v0.23.0, and against the Hermes development branch before release.

### Bench in Hermes Desktop

- Page **Circuit Bench** (`/bench`) with a sidebar entry, a board chip in the status bar, a serial pane, command
  palette entries (open, serial monitor, new project, manage projects, demo, detect, build, doctor), the `::bench`
  chat card, the theme **Bench Phosphor** (listed, never switched on by itself) and a settings page (Bench look,
  console timestamps). From Hermes 0.22.6 schematics in the chat get the Bench's own card; 0.22.5 shows Hermes'
  built-in image.
- Six stations in build order: 01 PLAN, 02 CALC, 03 WIRE, 04 SOLDER, 05 FLASH, 06 DEBUG.
- Board model: every board is drawn as a schematic hardware model (PCB, module can with antenna keep-out, header
  strips, ports, buttons, LEDs, regulator, USB-UART bridge) behind the interactive pins. Placed parts come from a
  cited `drawing` block per board (quotes from the manufacturer's user guide); a connector form is drawn only when
  the guide names it. Pin states use colour, shape and word. FLASH and DEBUG show a live twin of the board driven
  only by real events; one SIMULATED badge marks every simulated result.
- Station details: polarity pictograms in SOLDER, mini schematics in CALC, net colours and a coupled wiring table in
  WIRE, image sizes and grouped hashes in the flash dialog, highlighted registers and frames in DEBUG.
- Project manager (**▤ Projects** in the header): open, create or delete bench projects. Deleting moves the project
  folder to the bench trash (`plugin-data/circuit-bench/trash/`); nothing is erased and firmware folders outside the
  project are not touched. A new project starts empty.
- Remove parts again: ✕ per row in the 02 CALC parts list with an inline confirmation; calculations, circuits and
  solder steps stay, the solder plan shows as stale.
- Module catalog dialog, module rows in the assignment table and a bus card (addresses, mux channels, rail
  currents) in 01 PLAN; the newer calculators appear in 02 CALC as generic cards; 03 WIRE has a module block.

### Agent half

- Seven tools in the toolset `circuit-bench`: `bench_project`, `bench_pins`, `bench_calc`, `bench_schematic`,
  `bench_solder`, `bench_board`, `bench_crash`.
- Bundled skill `esp32-bench`, the `/bench` command (`doctor`, `ports`, `projects`) and a `pre_tool_call` hook that
  makes Hermes ask before every `bench_board` build that starts PlatformIO, before a flash on a real board, and
  before detect and monitor on real ports while **Ask before opening serial ports** is on (the default), or blocks them.
- `/bench doctor` checks tools and versions, serial group, ports, dependencies, the data folder and the hardware
  switch.
- Module tools: `bench_pins modules`/`module`; `bench_project` `add_module`, `connect` (also changes `address`,
  `facts`, `variant`, `qty`) and `set_rails`. Project answers carry the module warnings and `module_counts`.

### Chips and boards

- Pin rules for ESP32, ESP32-S2, ESP32-S3, ESP32-C3 and ESP32-C6, generated from ESP-IDF v6.1 (pinned commit) and
  the Espressif module datasheets: strapping pins, flash and PSRAM pins per module variant, USB-JTAG, UART0,
  input-only pins, ADC2 with Wi-Fi. Each verdict names its rule and source.
- Module variants: ESP32-S3-WROOM-1 N4, N8, N16, N4R2, N8R2, N16R2, N4R8, N8R8, N16R8 (not N16R16VA); ESP32-C6
  WROOM-1 and MINI-1; ESP32 WROOM-32E and WROVER-E (GPIO16/17 free on the WROOM, reserved on the WROVER).
- Seven boards with header layouts and wiring tables: ESP32-S3-DevKitC-1 v1.1, ESP32-DevKitC V4,
  ESP32-C3-DevKitM-1, ESP32-S2-DevKitC-1, ESP32-C6-DevKitC-1 v1.2, ESP32-C6-DevKitM-1 and the Wireless-Tag
  WT32-ETH01 V1.4 (LAN8720A Ethernet; GPIO0 carries the Ethernet clock and is blocked; supply warning: 3V3 or 5V,
  never both).
- One chip register for architecture, toolchain prefix, esptool chip name and PlatformIO MCU, used by detection,
  build, flash and crash decoding.
- Build and flash refuse a chip mismatch between the detected chip, the chip the firmware was built for and the
  project chip (`chip_mismatch`), and an Arduino build for the ESP32-C6 on a platform older than espressif32 8.0.0
  (`platform_too_old`), before `pio` runs. Changing the project chip drops the last build.

### Module catalog and checks

- 180 common chips and modules in 30 families (sensors, displays, addressable LEDs, level shifters, I/O expanders
  and muxes, ADCs, power monitors, RTCs, motor drivers, regulators and chargers, CAN/RS-485, radios, Ethernet, GNSS,
  cellular). Every value carries page and verbatim line from the chip maker's datasheet (184 pinned files with
  SHA-256). Source classes: maker file, Wayback copy, maker document hosted by a third party, and class B (hints
  only).
- Module checks in `bench_pins check`: 15 generic rules plus 98 family rules and a note for unknown modules. The
  generic rules cover I²C address conflicts and reserved addresses, address-select pins, bus speed, pin roles,
  shorted bus lines, SPI chip selects, open pins, supply range, logic levels in and out, the rail current budget,
  required parts and hazards. Address conflicts are a caution (the bus cannot reach both devices; no damage). One
  cause gives one warning. Dangers come first and stay visible when the answer is compacted; cut findings are
  counted, and the answer stays below 8 KB.
- Breakout boards: module values are chip values. A board's regulator, pull-ups or decoupling count only as the user
  confirms them in the part's `facts` (`regulator`, `pullups`, `pullups_to`, `level_shifter`, `onboard`). Until
  then a breakout finding is at most a caution that says what to confirm.
- Net convention: several devices on one I²C/SPI bus with the same `net` are no pin conflict; one net per signal
  line; without a `net` the role name is the net, and a module pin wired to a role name sits on that role's net.

### Calculators, schematics, soldering

- 16 calculators, listed by `bench_calc list`: `led`, `npn` (onsemi 2N2222A datasheet data), `mosfet` (AO3400A,
  IRLZ44N), `divider`, `i2c_pullup` (estimates the bus capacitance when `c_bus` is not given and says so), `ldo`
  (AMS1117-3.3), `ina_shunt`, `current_sense`, `rtd`, `ntc`, `adc_ext`, `current_limit`, `led_strip`, `opto`,
  `buck`, `charger`; each with formula, steps, E-series value, assumptions and sources.
- Schematic blocks (SVG) `led`, `npn_low_side`, `button_pullup`, `divider`, `module` and `level_shifter`, with
  wiring tables from board header to part.
- Solder plans from a parts list (low before tall, robust before heat-sensitive, mechanical parts last) with
  polarity, heat and safety hints; steps can be ticked off.

### Build, flash, serial, crashes

- Port list with USB kinds (listing never opens a port), detection with esptool, PlatformIO builds with explicit
  targets.
- **Build approval:** every agent build that starts PlatformIO asks through Hermes' approval, because it
  runs the project's own build scripts; "always" covers exactly that folder and env. Such builds are refused in
  cron jobs and without the plugin's hook. A build for a `sim://` board asks in the same way when it really runs
  PlatformIO (`pio` and every package installed); otherwise it is simulated, runs nothing and never asks. The
  Bench's **Build firmware** button does not ask.
- Flash writes every image: bootloader, partition table, `boot_app0` and the app with `esptool write-flash` at the
  offsets PlatformIO reports, with `--chip` of the image; ELF and image hashes are checked against the approved
  build. No rebuild while flashing, no erase beyond the written sectors, no custom upload commands
  (`upload_protocol = custom`, `upload_command` and erase flags are refused). A build without bootloader and partition
  table is refused (`elf_missing`) instead of writing the app alone.
- Detection and flash refuse with `port_busy` (PID and program named) when another program has the serial port open
  (Linux, from `/proc/<pid>/fd`; the device is never opened for the check): a second reader swallows esptool's
  replies and leaves the board half-written.
- Serial broker with panic capture; the monitor reopens a port after a board reset re-enumerates it, and old panics
  from before a flash no longer count as current. **Restart board** in 06 DEBUG starts the firmware when a board
  waits in download mode after a flash; a crash loop that blocks the bootloader gets the BOOT/RESET hint. The
  monitor recognises every crash the decoder knows (assert, `ESP_ERROR_CHECK`, stack overflow, heap corruption,
  UBSan, …); a reboot loop of one crash keeps one log with a repeat count, and old logs are pruned (200 per kind).
- Crash decoder for Xtensa and RISC-V panics (ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6): frames resolved to
  function and `file:line` with the toolchain's `addr2line`, with the cause explained. **Fix with Hermes** puts a fix
  request into the chat composer; nothing is sent until you press Enter.

### Simulation

- Simulated board `sim://esp32s3-n16r8` with recorded, synthetic serial logs, demo project `laser-trigger` and an
  example firmware with a deliberate crash for the "Fix with Hermes" exercise. Every simulated result is labelled
  SIMULATED (`simulated: true`). The demo build is a real offline `pio` build when PlatformIO and all needed
  packages are already installed, otherwise it is simulated.

### Safety

- **Allow flashing real boards** (`allow_flash`) is off by default; every agent flash of a real board needs Hermes'
  approval bound to port, MAC and firmware hash; the Bench always shows its own confirmation dialog.
- **Access real hardware** (`hardware_access`) off, or `CIRCUIT_BENCH_HW=off`, makes real ports unreachable.
- Detect, monitor and flash are refused in cron jobs; agent flashes of real boards are refused while Hermes may
  approve without a person (`approvals.mode: off`, `HERMES_YOLO_MODE`, an approving `single_query_mode` /
  `unattended_mode`). In those modes agent builds run without a question.
- A session-scoped `/yolo` and one-shot runs (`hermes -z`, which bypass approvals by design) are not visible to
  plugins: there Hermes passes agent builds, flashes and port openings without asking. Keep **Allow flashing real
  boards** off while you use them.
- Board identity on flash: another USB device on the approved port is refused before any tool runs; esptool is
  stopped at a `MAC:` line of another board (before it writes); detection holds the port lock like a flash.
- Unreadable settings fall back to their safe value and `/bench doctor` names them; approval modes are read the
  way Hermes reads them (a YAML `yes` is not an auto-approval).
- PlatformIO telemetry is switched off for the plugin's calls unless you set the variable yourself.
- Calculators refuse inputs above 60 V; solder plans catch AC ratings (`250VAC`) and lithium cell formats.
  Low-voltage, laser and lithium-cell warnings in calculator, schematic and solder plan.

### Known limits

- Real boards tested on Linux only: ESP32-S3-DevKitC-1 (N16R8) over its USB-Serial/JTAG port (crash, decode, fix,
  flash, boot, board identity refusals without writing) and WT32-ETH01 V1.4 (detect, build, flash, boot, Ethernet
  link with DHCP). macOS is covered by CI in simulation mode (pytest, node tests, Hermes v0.23.0 validate, simulated
  flow); Windows is not supported.
- ESP32-C3, ESP32-S2 and ESP32-C6 are checked offline only (pin and board data against the pinned sources, offline
  builds and crash decoding with real toolchains), not on a real board.
- Session-scoped `/yolo` and one-shot runs (`hermes -z`) pass agent builds, flashes and port openings without
  asking; see Safety above.
- Only PlatformIO projects; no ESP-IDF `idf.py`, no erase beyond the written sectors, no custom upload commands.
  Only the 180 catalog entries can be added as modules. Bench jobs do not survive a restart of the Hermes backend.
- See the README section "Limits" for the full list.

[0.1.1]: https://github.com/juvenile454/hermes-circuit-bench/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/juvenile454/hermes-circuit-bench/releases/tag/v0.1.0

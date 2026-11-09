# Changelog

All notable changes to Circuit Bench. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/juvenile454/hermes-circuit-bench/releases/tag/v0.1.0

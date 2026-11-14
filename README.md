![Circuit Bench: an ESP32 workbench in Hermes Desktop](docs/screenshots/banner.png)

# Circuit Bench

[![CI](https://github.com/juvenile454/hermes-circuit-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/juvenile454/hermes-circuit-bench/actions/workflows/ci.yml)

An ESP32 workbench for Hermes: from pin choice to running firmware, with every pin verdict and every part value
computed in code and shown with its source.

## Try it in 60 seconds (no hardware)

1. Install it from the catalog in Hermes Desktop (this turns the Bench on), or run
   `hermes plugins install circuit-bench --enable` and switch on **Desktop** in the Circuit Bench row under
   **Capabilities → Plugins**. Not in your catalog yet? Install from the repository:
   `hermes plugins install "https://github.com/juvenile454/hermes-circuit-bench#circuit_bench" --enable`.
   Without a terminal (script, SSH, an agent) add `--yes-deps`.
2. Open **Circuit Bench** in the sidebar and click **Load demo project** (or ask Hermes): `laser-trigger`, a
   simulated ESP32-S3 N16R8 (`sim://esp32s3-n16r8`) with pins, parts, schematics, a solder plan and a firmware that
   crashes on purpose. In **05 FLASH**: **Detect**, **Build firmware**, **Flash ›** and confirm.
3. In **06 DEBUG**, click **Open monitor ›**: a `StoreProhibited` panic decoded to `write_sensor_buffer`. **Fix with
   Hermes** drafts a request in the composer (nothing is sent before Enter); Hermes proposes a fix, builds after
   your OK, and after the next flash the monitor shows `boot ok`.

No board, no PlatformIO; simulated results are labelled SIMULATED.

**▶ [Watch the 90-second demo](https://github.com/juvenile454/hermes-circuit-bench/releases/tag/v0.1.0)**

![Hermes fixes a firmware crash; the Bench beside the chat shows FIXED](docs/screenshots/hero-agent.png)

*Scripted model for a reproducible screenshot; the tool calls and results are real.*

| | |
|---|---|
| ![01 PLAN: a blocked pin](docs/screenshots/01-plan-blocked.png) | ![02 CALC: calculator result](docs/screenshots/02-calc.png) |
| 01 PLAN: blocked pin, rule and source | 02 CALC: formula, steps, assumptions, source |
| ![03 WIRE: schematic](docs/screenshots/03-wire.png) | ![04 SOLDER: soldering order](docs/screenshots/04-solder.png) |
| 03 WIRE: schematic and wiring table | 04 SOLDER: order with polarity and heat warnings |
| ![05 FLASH: confirmation dialog](docs/screenshots/05-flash-dialog.png) | ![06 DEBUG: decoded panic](docs/screenshots/06-panic.png) |
| 05 FLASH: nothing written before you confirm | 06 DEBUG: panic decoded to function and line |

All images show the simulated demo board (`sim://`); no real hardware, names or addresses.

**Contents:** [What it does](#what-it-does) · [Install](#install) · [With a real board](#with-a-real-board) ·
[Safety](#safety) · [Disclosure](#disclosure) · [How it works](#how-it-works) · [Limits](#limits) ·
[Contributing](#contributing) · [Licence and thanks](#licence-and-thanks)

## What it does

Hermes and the Bench share one project, in six stations:

| Station | What you get |
|---|---|
| **01 PLAN** | GPIO choices checked against Espressif data (strapping, flash and PSRAM pins per module variant, USB-JTAG, UART0, input-only, ADC2 with Wi-Fi); each verdict names rule and source; free pins suggested. |
| **02 CALC** | 16 calculators (LED resistor, transistor and MOSFET switches, divider, I²C pull-ups, LDO, current shunts, RTD/NTC, buck, charger, …) with formula, steps, E-series value, assumptions, sources. |
| **03 WIRE** | Schematic per building block (SVG), wiring table from header to part. |
| **04 SOLDER** | Solder order (low before tall, robust before heat-sensitive) with polarity and safety hints. |
| **05 FLASH** | Detect with esptool, build with PlatformIO, flash the build you approved. |
| **06 DEBUG** | Serial monitor with panic detection; backtrace decoded to function and `file:line`; **Fix with Hermes**. |

**Modules:** 180 common chips and modules in 30 families (sensors, displays, LEDs, I/O expanders, ADCs, RTCs,
motor drivers, regulators, radios, Ethernet, GNSS, cellular, …), each value with page and verbatim line from the
maker's datasheet. Wired modules run 15 generic rules (I²C addresses, bus speed, pin roles, shorted bus lines, chip
selects, open pins, supply range, logic levels, rail current, required parts, hazards) plus 98 family rules and a
note for unknown modules, shown on a bus card. One cause gives one warning; dangers come first.

**▤ Projects** opens, creates or deletes projects (deleted ones go to the bench trash). Without Hermes Desktop
the same seven tools work in the CLI and on messaging platforms; `/bench doctor`, `/bench ports` and
`/bench projects` check the setup.

## Install

```
hermes plugins install circuit-bench --enable
```

Or from the repository:
`hermes plugins install "https://github.com/juvenile454/hermes-circuit-bench#circuit_bench" --enable`.
Without `--enable`, answer "Enable now?" with y; otherwise the tools and the Bench backend stay off.
Hermes asks before installing the dependencies (`schemdraw` ≥ 0.21, < 0.24, `pyserial` ≥ 3.5, < 4). Without a
terminal (scripts, SSH, an agent) it cannot ask and skips them, and the plugin stays off: add `--yes-deps`.
Requires Hermes ≥ 0.22.5; from 0.22.6 schematics in the chat get the Bench's own card.

**Desktop half.** Installing from Hermes Desktop (catalog install dialog with **Enable after install**, or the
**Agent** switch of the row under **Capabilities → Plugins**) also turns the Desktop half on. After
`hermes plugins install` on the command line, the Desktop half stays off until you switch on **Desktop** in the
Circuit Bench row under **Capabilities → Plugins** (or turn the Agent switch off and on).

**For real boards** (not for the simulation): [PlatformIO Core](https://platformio.org/install/cli) (`pio`: `PATH`,
`~/.platformio/penv/bin` or `~/.local/bin`) and [esptool](https://github.com/espressif/esptool) (`PATH` or
`~/.local/bin`), or their paths in the settings; `addr2line` comes with PlatformIO's toolchains. Linux:
`sudo usermod -aG dialout $USER` (`uucp` on Arch), then log in again. `/bench doctor` checks tools, versions,
serial group, ports, dependencies, data folder and hardware switch (the simulation needs none of the tools).

**Settings** (Settings → Plugins → Circuit Bench → Agent settings): **Allow flashing real boards** (`allow_flash`,
off), **Ask before opening serial ports** (`approve_serial`, on), **Access real hardware** (`hardware_access`, on;
off: only `sim://`), baud rate 115200, monitor and build limits 120 s and 900 s, `pio`/`esptool` paths. The Bench
page has **Bench look** (Phosphor or Follow app theme) and console timestamps.

## With a real board

1. Install `pio` and `esptool`, run `/bench doctor`, turn on **Allow flashing real boards**.
2. Plug in the board: the status bar shows `LINK` (seen, not opened; listing never opens a port).
3. **Detect** in 05 FLASH runs esptool on that port. **Detection resets the board.**
4. Choose a PlatformIO project (`platformio.ini`) or **Use example project**, **Build firmware**, **Flash ›**. The
   dialog checks port, MAC and hash against detection and build; nothing is written before **Flash board ›**.
5. From the chat, Hermes asks before every build that starts PlatformIO and before every real flash (see Safety).

Firmware with its own USB stack (USB ID `303a:4001`) blocks the automatic bootloader reset: hold BOOT, tap RESET,
release BOOT and retry, or use the UART port. The WT32-ETH01 (no USB) needs a
3.3 V USB-to-UART adapter; hold IO0 at GND while you pull EN low. **Power it from 3V3 or 5V, never both**
(datasheet V1.4, note 2), with at least 500 mA. Build and flash refuse a chip mismatch between board, build and
project (`chip_mismatch`) and an ESP32-C6 Arduino build below `espressif32@8.0.0` (`platform_too_old`).

## Safety

- **Low voltage only:** 3.3/5 V logic and small DC loads, no mains (230 V/120 V). Mains in a solder plan (also
  `10A 250VAC` relay ratings) is a danger warning, calculators refuse inputs above 60 V, the divider schematic and
  relay/motor calculation warn. No substitute for datasheets or a qualified person.
- **Lasers:** never look into the beam. Calculator, schematic and solder plan warn, the NPN calculator also on a
  missing base pull-down (the laser could switch on while the pin floats during boot, reset or flashing). Test with
  an LED first.
- **Lithium cells:** the solder plan warns never to solder onto a cell (leak, fire); use a holder, connect it last.
- **Builds** run the project's own scripts, so every agent build that starts PlatformIO asks through
  Hermes: *Build env \<env\> with PlatformIO? This runs the project's own build scripts (platformio.ini,
  extra_scripts) with your user rights. Nothing is uploaded to a board. Folder: "\<path\>"* The checked value (the env)
  comes first; the folder, the only free text in the question, comes last and in quotes, so a folder name cannot read
  like the rest of the question. "Always" covers exactly that folder and env. An env that is no PlatformIO name
  (ASCII letters, digits and `_ . : -`, at most 64 characters, the first one not `. : -`) is refused before the
  question. In the question these characters are shown as `\uXXXX` (`\UXXXXXXXX`
  above U+FFFF): control characters, line breaks, Unicode direction marks, space variants other than a plain space,
  and every character with the Unicode property `Default_Ignorable_Code_Point` (zero-width characters, variation
  selectors and others) and `"` in the folder name. In the folder name every other quotation mark (all characters
  with the Unicode property `Quotation_Mark` except the apostrophe `'`) and the characters that look like `"` (primes
  and a few others) are shown that way too, so nothing in a folder name can look like the end of the quoted field;
  a folder `Lab’s` (typographic apostrophe, U+2019) therefore appears as `Lab\u2019s`. Letters stay as they are:
  look-alike letters, and letters of right-to-left scripts (Hebrew, Arabic), which can change the displayed order of the
  path parts in a folder name; the quotation marks of the field stay in place, and "always" of a build keeps the real
  folder path. A path longer than 120 characters is shortened in the middle, so the shown path is never longer than 120
  characters; the question then ends with ` (path shortened)`, which also appears when a character was only replaced.
  Such builds are refused in cron jobs and without the plugin's hook; a folder without `platformio.ini` is refused
  without a question. A build for a `sim://` board asks in the same way when it really runs PlatformIO (`pio` and every
  package installed); otherwise it is simulated, runs nothing and never asks. The Bench's **Build firmware** click does
  not ask again.
- **Flashing** is locked in layers:
  - **Allow flashing real boards** is off by default and blocks every real flash, from agent and Bench.
  - Every agent flash of a real board needs Hermes' approval naming env, chip, MAC, port and firmware hash, and the
    firmware folder last and in quotes; "always" covers only that firmware on that board and port. The approval record
    also holds the images and the time of the last build: a build made while the question is open is not flashed (same
    ELF with other images or time: `not_confirmed`; another ELF: `elf_mismatch`).
  - **The handlers are bound to the hook:** `bench_board` `detect`, `monitor` and `flash` on a real port, and a
    `build` that starts PlatformIO, run only if the plugin's approval hook let exactly that call through for the same
    task, action and target; otherwise the tool answers `not_confirmed`. One hook pass serves one run, also when no
    question is asked (**Ask before opening serial ports** off). The binding does not replace the other locks, it
    does not stop code in the same process (another plugin) that fakes the arguments or calls the plugin's
    internals, and it holds per task, action and target, not per single call.
  - **The port in a question** (flash, detection and serial monitor) keeps only letters, digits and `._:/-` as they
    are; every other character is shown as `\uXXXX`. A port URL other than `sim://` (for example `rfc2217://host:4000`
    or `socket://…`) is blocked by the hook before the question, also when **Ask before opening serial ports** is off
    (`invalid_args`, `unsupported port URL …`): the plugin talks only to local boards.
  - **Flashing writes from a private snapshot:** every file a flash writes is first copied into a private folder
    (see Disclosure), and `firmware.bin`, `bootloader.bin` and `partitions.bin` are checked at the copy against the
    hashes recorded at build time (`elf_mismatch` on a difference). `boot_app0.bin` and extra images of a project
    have no recorded hash and are written as they were when copied. The check goes by file name, not by flash
    address, the private folder is not protected against other processes of your own user, and the copies are made
    after `pio project metadata`, which runs the project's own scripts.
  - The Bench always shows its own confirmation dialog, also for simulated boards.
  - Only the detected board is flashed: another USB device on the port (VID, PID, serial number) is refused before
    any tool runs; esptool is stopped at a `MAC:` line of another board, printed before it writes. Only complete
    image sets are written (bootloader, partition table, app).
  - Cron jobs cannot detect, monitor or flash, not even simulated boards.
  - When Hermes may approve without a person (`approvals.mode: off`, `HERMES_YOLO_MODE`, an approving
    `approvals.single_query_mode` / `approvals.unattended_mode`), the agent cannot flash real boards, nor open real
    ports while **Ask before opening serial ports** is on; agent builds then run unasked. The Bench still can, through
    its dialog and clicks.
  - A session-scoped `/yolo` and one-shot runs (`hermes -z`, which bypass approvals by design) are not visible to
    plugins: there Hermes passes agent builds, flashes and port openings without asking. Keep **Allow flashing real
    boards** off while you use them.
  - **Access real hardware** off, or `CIRCUIT_BENCH_HW=off`, makes real ports unreachable.
  - An unreadable setting falls back to its safe value (hardware and flashing off, port approval on);
    `/bench doctor` names it. If the plugin settings cannot be read from Hermes' configuration at all, hardware
    access and flashing (`hardware_access`, `allow_flash`) stay off and port approval (`approve_serial`) stays on,
    while numbers and paths keep their defaults: `/bench doctor` marks the check `settings` as `FAIL` (the Bench's
    doctor dialog shows it as a failed row) and shows the warning `settings_unreadable` (it starts with `the plugin
    settings could not be read from Hermes' configuration, so real boards stay off`), and agent calls for real boards
    end with `sim_only` and a hint that names the cause. A readable configuration without a plugin entry still gives the
    defaults, including `hardware_access` on.
- **Texts the model reads:** the message and hint of an error answer and the message of a block by the hook show
  format and direction characters, line and paragraph separators, lone surrogates, DEL, the C1 control characters
  and every `Default_Ignorable_Code_Point` as `\uXXXX` (`\UXXXXXXXX` above U+FFFF). Line breaks and tabs stay. The
  input is not refused for these characters (zero-width joiners occur in real folder names). Warnings, assumptions
  and serial lines are not filtered, and look-alike letters stay as they are.

## Disclosure

What Circuit Bench does on your machine (catalog rule 13):

- **Serial ports:** opened only when asked: agent detection or monitor (after approval while **Ask before opening serial
  ports** is on, the default) or a click in the Bench.
  Opening can restart the board through DTR/RTS (set inactive unless a reset is requested; some boards restart
  anyway); detection always resets it. Nothing opens automatically. A Bench port stays open until **Close
  monitor** or a backend stop. Before a detection or flash it checks on Linux which other programs have the port
  open (reads the `/proc/<pid>/fd` links of your processes, never opens the device) and refuses with `port_busy`,
  naming PID and a shortened command line.
- **Subprocesses:** your `pio`, `esptool` and the toolchain's `addr2line` as CLI programs: no shell, a minimal
  environment (`PATH`, `HOME`, `TMPDIR`, `USER`, `LOGNAME`, `PLATFORMIO_*`), own process group, time limit. esptool
  is never imported; the doctor only asks for versions.
- **Firmware writes:** private copies of the approved build, written with `esptool write-flash`: bootloader,
  partition table, `boot_app0` and app at the offsets from `pio project metadata`, with `--chip` of the image
  (another chip stops esptool). Every file is first copied into `tmp/flash-<random>` in the plugin data folder (mode
  `0700`, files `0600`); the ELF is hashed in place and the copies of `firmware.bin`, `bootloader.bin` and
  `partitions.bin` (compared without case) are checked against the hashes recorded at build time. `esptool` gets only
  the copies, and the folder is removed on every exit (leftovers older than an hour at the next flash); a file that
  cannot be copied ends the flash with `tool_failed` before esptool starts. Files without a recorded hash
  (`boot_app0.bin` from the framework package, extra images) are written as copied, and the check goes by file name,
  not by flash address. No build while flashing, no erase beyond the written sectors. `upload_protocol = custom`,
  `upload_command` and erase flags in the effective configuration are refused.
- **Your project's code runs:** builds, `pio project metadata` (also for flash) and uploads run
  the project's PlatformIO scripts (`extra_scripts`) with your user rights; agent builds ask first. Use folders you
  trust. Crash decoding from the chat runs only `addr2line` on the ELF of the last build. Every `pio run` names its
  targets, so `targets` in `platformio.ini` does not run.
- **Network:** none from the plugin; it downloads nothing and never updates itself. PlatformIO may download
  platforms, toolchains and libraries on a first build; its telemetry is off for these calls
  (`PLATFORMIO_SETTING_ENABLE_TELEMETRY=No`) unless you set that variable.
- **Simulation:** the demo build is a real offline `pio` build when all packages are installed (an agent build
  then asks first), otherwise simulated; board and upload are always simulated.
- **Files:** projects, schematics, logs, panic captures, locks and simulator state live in
  `$HERMES_HOME/plugin-data/circuit-bench/` (mode `0700`; deleted projects go to `trash/`; a real flash adds the
  temporary `tmp/flash-<random>`). Outside it the plugin
  reads the firmware folder you choose, an ELF you name and the installed PlatformIO packages (`~/.platformio`, for
  `addr2line` and offline demo builds). PlatformIO writes build output into the firmware folder; `bench_schematic`
  writes an SVG copy into a folder you name (`out_dir`).
- **Hermes configuration:** its own settings, `approvals.*` (including `approvals.timeout`),
  `timeouts.tools.sequential_call`, `timeouts.tools.concurrent_batch`, `HERMES_YOLO_MODE` and
  `HERMES_CONCURRENT_TOOL_TIMEOUT_S`, read only.
- **Background threads:** a reader per open port, a port watcher (every 2 s while the Bench is in use), a thread
  per Bench detect, build or flash job.
- **Approvals:** a `pre_tool_call` hook makes Hermes ask before every `bench_board` build that starts PlatformIO,
  before real flashes, and before detects and monitors on real ports while **Ask before opening serial ports** is on
  (the default), or blocks them; it never approves. The handler of each such call runs only after the hook let that
  call through (`not_confirmed` otherwise; see Safety); the approval record that lets a handler run lives in memory
  only and serves exactly one run. **Known gap:** A session-scoped `/yolo` and one-shot runs (`hermes -z`, which
  bypass approvals by design) are not visible to plugins: there Hermes passes agent builds, flashes and port
  openings without asking. Keep **Allow flashing real boards** off while you use them.
- **Chat:** **Ask Hermes** and **Fix with Hermes** only draft into the composer (new chat if needed, or clipboard);
  they never send.
- **Desktop:** plugin SDK and own DOM only. Routes under `/api/plugins/circuit-bench/` use the app's session token;
  the serial stream is a WebSocket when `plugins.isolation` is `in_process` (default), otherwise the Bench polls.
- No telemetry and no credentials, and it never runs a shell.

## How it works

- **Deterministic core:** `circuit_bench/bench_core/` is plain Python, tested outside Hermes; tools and Desktop
  backend call the same functions. Pin verdicts and part values come from this code, not from the model.
- **Result contract:** every action returns `ok`, `summary`, `result`, `checks` (`passed`, `failed`, `skipped`,
  `not_checked`), `warnings`, `assumptions`, `sources` and `simulated`. Only `passed` counts as checked.
- **Sources** (date and URL in `circuit_bench/data/sources/`): ESP-IDF v6.1 (pinned commit `fff9895c`), Espressif
  datasheets and board guides (pinned esp-dev-kits commit), Wireless-Tag's WT32-ETH01 documents, esptool 5.6.0,
  platform-espressif32, part datasheets and IEC 60063; module data from 184 pinned datasheet files with SHA-256
  (Wayback and third-party copies marked). Cited vendor files that could no longer be fetched as pinned are now
  pinned to `web.archive.org` copies of the same document revision; a cold fetch of every pinned source file of the
  citation tests was verified locally on 2026-11-13. Rules of thumb are labelled.
- **Tools** (toolset `circuit-bench`):

  | Tool | Actions |
  |---|---|
  | `bench_project` | `create`, `get`, `list`, `set_board`, `assign`, `unassign`, `set_firmware`, `add_parts`, `remove_parts`, `note`, `add_module`, `connect`, `set_rails`, `demo` |
  | `bench_pins` | `check`, `suggest`, `info`, `modules`, `module` |
  | `bench_calc` | `list`, `led`, `npn`, `divider`, `i2c_pullup`, `mosfet`, `ldo`, `ina_shunt`, `current_sense`, `rtd`, `ntc`, `adc_ext`, `current_limit`, `led_strip`, `opto`, `buck`, `charger` |
  | `bench_schematic` | `render` (`led`, `npn_low_side`, `button_pullup`, `divider`, `module`, `level_shifter`) |
  | `bench_solder` | `plan`, `step` |
  | `bench_board` | `ports`, `detect`, `build`, `flash`, `monitor` |
  | `bench_crash` | `decode` |

- **Skill** `esp32-bench`: values only from the tools, sources cited, warnings repeated, builds and flashes only
  when asked. In Hermes Desktop the agent can write `::bench{project="laser-trigger" view="pins"}`
  as a paragraph: a chat card with **Open in Bench** (`view`: `pins`, `calc`, `wire`, `solder`, `flash`, `crash`).

![A ::bench card in the chat: the pin map of laser-trigger with Open in Bench](docs/screenshots/chat-directive.png)

## Limits

- Chips: ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6. Module variants: ESP32-S3-WROOM-1 N4, N8, N16, N4R2, N8R2,
  N16R2, N4R8, N8R8, N16R8 (not N16R16VA); ESP32-C6 WROOM-1 and MINI-1; ESP32 WROOM-32E and WROVER-E (GPIO16/17
  free on the WROOM, reserved on the WROVER, a caution while unknown).
- Boards: ESP32-S3-DevKitC-1 v1.1, ESP32-DevKitC V4 (WROOM-32E), ESP32-C3-DevKitM-1, ESP32-S2-DevKitC-1,
  ESP32-C6-DevKitC-1 v1.2, ESP32-C6-DevKitM-1, Wireless-Tag WT32-ETH01 V1.4 (LAN8720A Ethernet; GPIO0 carries the
  Ethernet clock and is blocked; the maker does not state the PSRAM of its WT32-S1, so the variant stays unknown).
- **Real boards tested (Linux):** ESP32-S3-DevKitC-1 N16R8 over USB-Serial/JTAG (crash, decode, fix, flash, boot)
  and WT32-ETH01 V1.4 (detect, build, flash, boot, Ethernet with DHCP, via an ESP32-S3 board's USB-to-UART bridge).
  **ESP32-C3, ESP32-S2 and ESP32-C6 are checked offline only** (data against pinned sources, offline builds, crash
  decoding with real toolchains).
- Board identity (USB serial number, esptool 5.6.0 `MAC:` line), tested on the ESP32-S3-DevKitC-1: another serial
  number was refused before any tool ran, another MAC stopped esptool before its stub upload (`verify-flash`:
  unchanged). Boards without a USB serial number (e.g. CH340) are compared by MAC only (untested on a real bridge);
  without a `MAC:` line (Secure Download Mode) the check stays `not_checked`.
- A crash loop can keep the board out of its bootloader (the Bench says: hold BOOT, tap RESET). After a flash from
  download mode, **Restart board** in 06 DEBUG starts the firmware.
- MOSFET and regulator values only for AO3400A, IRLZ44N and AMS1117-3.3 from AMS (clones differ), transistor data
  only for the onsemi 2N2222A (TO-18; otherwise give `hfe_min`); without them those checks stay `not_checked`.
- Not checked: the divider's ADC range (no sourced ADC input range yet), the gate current peak of the MOSFET
  switch. A divider output above the pin's 3.6 V maximum is a danger warning (unless `target` is `other`, below); an
  LED or base current above the 40 mA a pin typically drives is a caution. ADC2 with Wi-Fi on the ESP32-S3 is a hint
  only. Firmware means PlatformIO projects: no ESP-IDF `idf.py`, no erase beyond the written sectors, no custom
  upload commands.
- Discrete parts in a project (resistors, LEDs, transistors) get no electrical check of their own: pin rules and
  catalog-module rules run (module rules count the pull-ups, series resistors and diodes they need), and the answer
  says so. Size them with the calculators.
- The `divider` calculator takes an optional `target`: `esp_pin` (default) or `other`. With `target=other` the output
  does not feed an ESP pin, so the pin limit is not applied (`calc.divider.pin_max` is `not_checked`, no
  `divider_overvoltage` warning): check the limit of whatever it feeds. Other values are refused (`invalid_args`);
  the Desktop divider form has no `target` field.
- Bus devices share SDA/SCL or SCK/MOSI/MISO when each assignment names the same `net`; chip selects stay one per
  device. Without a `net` the role name is the net; a module pin wired to a role name sits on that net.
- **Pin labels:** `conn` in `add_module`, `connect` and `add_parts` (with a module) accepts common breakout labels and
  maps them to a pin of the catalog entry. Bus labels (`SDA`, `SCL`, `SCK`/`SCLK`/`CLK`, `MOSI`/`SDI`/`DIN`/`SI`,
  `MISO`/`SDO`/`DOUT`/`SO`, `CS`/`SS`/`NSS`/`CSN`) follow the pin's cited signal: they count when exactly one pin of
  the module's active variant carries that signal and no other pin's name starts with the label. `VCC`/`VDD` and
  `GND`/`VSS` only stand in for each other, and only for a pin that is itself named like one of them. An ambiguous
  label is refused with its candidates, for example `'CLK' fits more than one pin of enc28j60 (CLKOUT, SCK): name the
  pin` or `'VCC' fits more than one pin of bme280 (VDD, VDDIO): name the pin`. The second case is common: a module
  with two supply pins (many sensor breakouts) needs both named, for example `VDD` and `VDDIO`. A real pin name always
  wins: on the `l298n`, `VSS` is the logic supply, not ground. `VIN`, `3V3`, `5V`, `RX` and `TX` are never labels.
  The project stores the catalog pin name; every mapping appears in the answer under `assumptions` with code
  `pin_alias` (for example `SDA → SDI`), and an unknown pin lists the module's pins with their labels. Labels apply
  to module parts only.
- **Module values are chip values from the maker's datasheet.** A breakout's regulator, pull-ups or decoupling count
  only once confirmed in the part's `facts`; until then a breakout finding is at most a caution. Class-B sources (no
  maker document, preliminary sheets such as the TTP223) give hints only. Values are never interpolated; values
  whose conditions the project does not meet stay `not_checked`.
- Only the 180 catalog entries can be added as modules. The newer calculators size only the parts they name (e.g.
  LM2596-ADJ and MP1584 for `buck`, MCP73831 and TP4056 for `charger`).
- The board variant suggested after detection is unverified (esptool does not report octal or quad PSRAM).
- Session-scoped `/yolo` and one-shot runs (`hermes -z`) pass agent builds, flashes and port openings without asking
  (see [Safety](#safety)). Bench jobs do not survive a backend restart.
- Hermes ends a tool call after 420 s by default (`timeouts.tools.sequential_call`); a first build of a new platform
  can take longer: start it from the Bench (05 FLASH) or raise that timeout.
- **Monitor length:** the agent's serial monitor listens at most for Hermes' deadline for a tool call minus 20 s, and
  never shorter than 1 s. The deadline is `timeouts.tools.sequential_call`, else `timeouts.tools.concurrent_batch`,
  else the environment variable `HERMES_CONCURRENT_TOOL_TIMEOUT_S`, else 420 s; the `monitor_max_seconds` limit
  (default 120, valid 1 to 3600) applies first. A shortened run carries the info warning `monitor_capped` (listen
  again to see more). With the default settings and Hermes' default deadline (420 s) nothing is shortened. The Bench
  console and stream are not affected.
- One simulated board (`sim://esp32s3-n16r8`) playing recorded, synthetic serial logs.
- Real boards are tested on Linux only; macOS is covered by CI in simulation mode (tests, Hermes validate, simulated
  flow). Windows is not supported (POSIX-only Python modules).

## Contributing

Issues and pull requests are welcome: bug reports with `/bench doctor` output, feature, board and module requests
with a datasheet link. Setup, checks and the source rule are in [CONTRIBUTING.md](CONTRIBUTING.md); AI coding agents
read [AGENTS.md](AGENTS.md). Security problems: [SECURITY.md](SECURITY.md).

## Licence and thanks

MIT License, see [LICENSE](LICENSE); third-party notices in [circuit_bench/NOTICE](circuit_bench/NOTICE). The licence
covers the code and this project's own texts and images. Short datasheet quotations in `circuit_bench/data/` and the
excerpts in `tests/corpus/excerpts/` are cited as evidence and stay with their rights holders; the Wikipedia excerpt
is CC BY-SA 4.0. Details: [tests/corpus/README.md](tests/corpus/README.md).

Thanks to Espressif for the ESP-IDF and esp-dev-kits documentation, to [schemdraw](https://schemdraw.readthedocs.io/)
(MIT) and [pyserial](https://github.com/pyserial/pyserial) (BSD), and to PlatformIO and esptool, which Circuit Bench
calls but does not bundle. The banner figure is Giambologna's *Flying Mercury* after a photograph in the Rijksmuseum
(RP-F-00-9348, CC0). Built for the Nous Research Hermes Agent Plugin Hackathon.

---
name: esp32-bench
description: "Use when the user works on an ESP32 circuit or board."
version: 0.1.1
---

# ESP32 bench (Circuit Bench)

Guide a small ESP32 build from idea to running firmware. The tools compute and check; you explain, ask, decide.

## Tools

`bench_project`, `bench_pins`, `bench_calc`, `bench_schematic`, `bench_solder`, `bench_board`, `bench_crash`; if
deferred, find them with `tool_search` (query `bench`) and run them via `tool_call`. Each takes an `action`.

## Rules

- Never guess pins, values or limits. Pins come from `bench_pins`, values from `bench_calc`. If a tool cannot
  answer, say so; do not fill the gap from memory.
- Only call something checked when it appears in `checks` with status `passed`. `failed`, `skipped` and
  `not_checked` are not checks you may claim. A rule of thumb stays a rule of thumb: say so.
- Cite the `sources` (title + URL) you rely on. Show units as returned (`display`).
- Repeat every `danger` and `caution` warning in plain words, before the next step.
- Low voltage only (3.3 V / 5 V logic, small DC loads). Refuse mains (230 V / 120 V) wiring and point to a qualified
  electrician. Lasers: warn about eye safety (never look into the beam, keep the enable line off at boot). Li-ion/LiPo
  cells: warn about short circuits, charging and fire risk. Relays switching mains: refuse the mains side.
- Results marked `simulated: true` come from a simulated board: say "simulated" when you report them.
- Lead with the outcome, then evidence, then the next step. Tables for pins and parts, numbers with units. Never
  schedule builds, flashes, detection or monitoring as cron jobs.

## Chips and DevKits

Chips: `esp32`, `esp32s2`, `esp32s3`, `esp32c3`, `esp32c6`. DevKits (`devkit`) and their chip:

| devkit | chip | notes |
|---|---|---|
| `esp32-s3-devkitc-1` | `esp32s3` | variant such as `n16r8` |
| `esp32-devkitc-v4` | `esp32` | variant `wroom-32e` or `wrover-e` |
| `esp32-c3-devkitm-1` | `esp32c3` | |
| `esp32-s2-devkitc-1` | `esp32s2` | |
| `esp32-c6-devkitc-1` | `esp32c6` | ESP32-C6-WROOM-1 (variant `wroom-1`) |
| `esp32-c6-devkitm-1` | `esp32c6` | ESP32-C6-MINI-1 (variant `mini-1`) |
| `wt32-eth01` | `esp32` | Ethernet board, see below |

- Ask for the ESP module variant if unknown: PSRAM and flash pins depend on it (C6 without one: in-package flash
  pins stay `caution`).
- C6 with Arduino needs `platform = espressif32@8.0.0` or newer in `platformio.ini`, else `platform_too_old`.
- WT32-ETH01: no USB, no buttons. Flash via a 3.3 V USB-to-UART adapter on PROG (RX to TXD, TX to RXD, GND); hold
  IO0 at GND while EN is pulled low and released, flash, free IO0, reset. Supply ≥ 500 mA on 3V3 **or** 5V,
  never both (danger). GPIO0 is the Ethernet clock (blocked). The WT32-ETH01 was tested on a real board.
- C3, S2 and C6 are checked offline only (data, build, decode), not on a real board: say so when you use them.

## Flow: PLAN → CALC → WIRE → SOLDER → FLASH → DEBUG

1. **PLAN** — `bench_project create` (id like `laser-trigger`; chip, variant, devkit from the table).
   - Pins: `bench_project assign` (`assignments: [{role, mode, pin, net}]`; adds or replaces roles); the answer
     carries the pin checks of all assignments. For a blocked or caution pin, run `bench_pins suggest` and propose an
     alternative; let the user choose. With several requests its `allocation` gives each role a pin of its own
     (`beyond_suggestions` picks passed the same checks); `limit` shows up to 10 per role, `more` counts the rest.
     `bench_pins check`/`info` explain a verdict of pins and catalog modules only. Discrete
     parts get no check of their own (assumption `discrete_parts`): never call a circuit checked because pins are ok.
   - Modules and buses: each line its own net, e.g. `I2C_SDA`, `I2C_SCL` (`net`; without it the role name is the
     net); modules connect to those nets or to `GPIO<n>`. SPI devices keep their own CS. Find modules
     with `bench_pins modules` (`q`, `category`), read `bench_pins module` (`id`), add with
     `bench_project add_module` (`module`, `ref`, `conn` pin->net, `address`, `facts`); `connect` changes it in place
     (`conn`, `address`, `facts`, `variant`, `qty`); `set_rails` adds rails (VMOT). Their answers carry the module
     warnings (`mod_*`: addresses, levels, supply, 3V3 budget, missing parts). Level shifting: two `bss138` modules or
     a `pca9306` via `add_module`. `conn` also takes breakout labels (`SDA`, `CS`, `GND`), mapped to the chip pin
     (assumption `pin_alias`); an ambiguous one is refused: name the pin.
   - Breakout facts and current budget: values are chip datasheet facts; ask what is on board and record it with
     `facts` (`pullups`, `regulator`, `onboard`); never assume breakout parts. Several breakouts with pull-ups on one
     bus: ask each value (`pullups`); the check takes them in parallel. Put the measured current or the
     `bench_calc led_strip` result into `facts.i_max` (A, whole part) for the budget check.
2. **CALC** — size parts with `bench_calc` (`list` names all, e.g. `led`, `npn`, `i2c_pullup`, `ldo`, `led_strip`; units
   such as `"3V3"`, `"20mA"`, `"4k7"`; above 60 V refused). `divider` `target` `other`: the output feeds no ESP pin, the
   pin limit is `not_checked`. `npn` without `r_base` sizes R_B for `forced_beta` (default 10, 2N2222A saturation
   ratio), rounded down to E12. `project` stores the result (`mosfet`/`ldo` then use its chip). Add parts with
   `bench_project add_parts` and `conn` pin->net (R/C `1`/`2`, electrolytic/battery `+`/`-`, diode `A`/`K`), or
   `connect` ref later; `remove_parts` drops them.
3. **WIRE** — `bench_schematic render` with the calculated values (`block`, `params`, `project`, `role` or `gpio`). It
   returns `svg_path`, a `MEDIA:` line to pass on and a wiring table. The `level_shifter` block only draws the BSS138
   I²C type (AN10441), not for LED data; draw buffers like 74AHCT125 with `module` (`part`=U1).
4. **SOLDER** — Run `bench_solder plan` with `project` once the parts are complete, and again after `add_parts`,
   `remove_parts` or `add_module`; the Bench SOLDER station stays empty until then. Walk through them; tick them off
   with `bench_solder step` (`project`, `step_id`, `done`). Stress polarity (electrolytics, diodes, LEDs) and
   heat-sensitive parts.
5. **FLASH** — `bench_board ports`, then `bench_board detect` (`port`, `project`; it resets the board), `bench_board
   build` (`project`; folder from `bench_project set_firmware`), then `bench_board flash` (`project`, `elf_sha256` from
   that build). Build and flash only when the user asked for it, never just to try something. Hermes asks the user to
   approve every build that runs PlatformIO (the project's scripts run; never in cron; on `sim://` too when `pio`
   really runs), flash and port opening; a flash approval names exactly that firmware; `allow_flash` must be on for
   real boards (`sim://` is not affected).
   If a flash is refused (e.g. `flash_disabled`, `unattended_blocked`, `sim_only`), explain reason and hint:
   `elf_mismatch` build again, pass the new `elf_sha256`; `chip_mismatch` (detected chip or env MCU is not the project
   chip) detect again or fix `set_board` or the env's board; `not_confirmed`: a precondition is missing (project,
   detected board, successful build, approval) or the board changed: follow the hint. `elf_missing`: the build output
   is incomplete: build again. `platform_too_old`: pin the hint's platform. Never work around a refusal (no shell
   `esptool`/`pio`).
6. **DEBUG** — `bench_board monitor` (`port`, `seconds`) shows serial lines and detects panics. On a panic:
   `bench_crash decode` (`log_ref` from the monitor, or `log`). Pass `project` to `bench_crash` so it finds the ELF
   (functions, files, lines). Read the source at the reported `file:line` → propose a concrete fix → after the user
   agrees, change the code and `bench_board build` → ask again before `bench_board flash` with the new `elf_sha256`.

### Simulated board

Without hardware, `bench_project demo` creates the simulated project `laser-trigger` (or your `id`) on a `sim://` board.
Its firmware crashes on purpose (`DEMO_CRASH 1`, StoreProhibited): the panic → decode → fix → build → flash → `boot ok`
loop runs only with this demo firmware. Other firmware is not emulated: after its flash the monitor shows only the ROM
boot (`rom_boot_only`, warning `sim_not_demo_firmware`); say so and never present those lines as the user's output. If
the project exists, `demo` returns it unchanged (maybe fixed); a new `id` gives a fresh crashing copy. A simulated flash
writes nothing (`board.flash.verified` is `not_checked`). Without `pio` builds are simulated: only real boards need it.

## Desktop Bench directive

Only in the Hermes Desktop app and if the project exists, add the directive as its own paragraph after your answer:

::bench{project="laser-trigger" view="pins"}

`view` is one of `pins`, `calc`, `wire`, `solder`, `flash`, `crash` (PLAN to DEBUG). Use the real project id. On
other platforms (CLI, Telegram, …) write no directive: answer with text and tables only.

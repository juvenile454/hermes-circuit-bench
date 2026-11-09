#!/usr/bin/env python3
"""Generate circuit_bench/data/pins/<chip>.json from the pinned corpus.

  scripts/gen_pins.py                write the JSON files
  scripts/gen_pins.py --check        regenerate in memory and compare byte by byte (exit 1 on a difference)
  scripts/gen_pins.py --corpus DIR   read the corpus from DIR (default tests/.corpus, see scripts/fetch_corpus.py pins)

Inputs are the files of tests/corpus/pins.json; their SHA-256 is verified first. Facts come only from them:
- GPIO table and footnotes of ESP-IDF v6.1 docs/en/api-reference/peripherals/gpio/<chip>.inc
  (columns GPIO, Analog Function, RTC GPIO or LP GPIO, Comment[s]);
- soc_caps.h: valid and output-capable GPIO masks (cross-check of the table and of input-only pins);
- adc_channel.h: ADC channel <-> GPIO; any difference to the table aborts;
- register/soc/io_mux_reg.h: IO MUX pin functions;
- cap_touch_sens/<chip>.inc: touch channel <-> GPIO;
- DevKitC-1 v1.1 user guide (RST) and the ESP32-S3-WROOM-1 datasheet excerpt for S3 rules and module variants;
- ESP32-DevKitC V4 user guide and its ordering table (esp-dev-kits) for the ESP32 GPIO16/17 rule and module variants;
- ESP32-C3-DevKitM-1 user guide (esp-dev-kits) for the C3 UART0 rule;
- ESP32-S2-DevKitC-1 and ESP32-C6-DevKitC-1 v1.2 user guides (esp-dev-kits) for the S2 USB OTG/UART0 and C6 UART0
  rules;
- ESP32-C6-WROOM-1 and ESP32-C6-MINI-1 datasheet excerpts for the C6 module variants (chip with or without
  in-package flash).
The chip list and titles come from the chip register (circuit_bench/data/chips.json via bench_core.chips).
The rules are written by hand in RULES below. Each carries a verbatim `evidence` quote that must appear in the file of
its source (for the gpio .inc: in the footnotes). Comment tokens of the table must be covered by rules exactly.
Nothing here runs at plugin runtime (catalogue rule 3).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from circuit_bench.bench_core import chips as chip_register  # noqa: E402  (needs ROOT on sys.path)

MANIFEST = ROOT / "tests" / "corpus" / "pins.json"
MANIFEST_DIR = MANIFEST.parent
DEFAULT_CORPUS = ROOT / "tests" / ".corpus"
OUT_DIR = ROOT / "circuit_bench" / "data" / "pins"
SOURCES_DIR = ROOT / "circuit_bench" / "data" / "sources"

IDF_REPO = "espressif/esp-idf"
IDF_TAG = "v6.1"
IDF_TAG_OBJECT = "4dc1c65503e98e9a6b4c3c5646237280ba79829b"  # annotated tag object, not a commit
IDF_COMMIT = "fff9895c82d744c7237be8847347bdd1b07c6643"  # commit the tag points to

# chip id -> title, in register order (data/chips.json); every chip needs a RULES entry
CHIPS = {cid: chip_register.title(cid) for cid in chip_register.ids()}
DEVKIT_SOURCE = "devkitc1-s3-v1.1"
DATASHEET_SOURCE = "ds-esp32-s3-wroom-1"
ESP32_DEVKIT_SOURCE = "devkitc-esp32-v4"  # ESP32-DevKitC V4 user guide (footnote [3]: GPIO16/17 per module)
ESP32_ORDERING_SOURCE = "devkitc-esp32-v4-ordering"  # its ordering table: module, flash, PSRAM per part number
C3_DEVKIT_SOURCE = "devkitm1-c3-v1"  # ESP32-C3-DevKitM-1 user guide (J3: TX/RX = U0TXD/U0RXD)
ADC_ONESHOT_SOURCE = "idf-v6.1-adc-oneshot"
S2_DEVKIT_SOURCE = "devkitc1-s2"  # ESP32-S2-DevKitC-1 user guide (J3: USB_D-/USB_D+, U0TXD/U0RXD)
C6_DEVKIT_SOURCE = "devkitc1-c6-v1.2"  # ESP32-C6-DevKitC-1 v1.2 user guide (J3: U0TXD/U0RXD)
C6_WROOM_SOURCE = "ds-esp32-c6-wroom-1"  # ESP32-C6-WROOM-1 datasheet excerpt: chip ESP32-C6, Table 3-1
C6_MINI_SOURCE = "ds-esp32-c6-mini-1"  # ESP32-C6-MINI-1 datasheet excerpt: chip ESP32-C6FH4/FH8, Table 3-1
MODULE_SOURCES = (C6_WROOM_SOURCE, C6_MINI_SOURCE)
# In SOC_GPIO_VALID_GPIO_MASK but not in the gpio/<chip>.inc table. The table is authoritative.
MASK_EXTRA = {"esp32": {20}}
# Comment tokens of the table that are data, not rules.
DATA_TOKENS = {"esp32c3": {"RTC"}}
OUTPUT_MODES = ["out", "pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs", "i2c_sda", "i2c_scl"]
STRAPPING_MSG = ("Strapping pin: its level at reset is part of the boot configuration (see the {} datasheet). "
                 "Avoid loads or pull resistors that change it at reset.")

# --- hand-written rules ------------------------------------------------------------------------------------------
# pins: list or "ADC2" (all ADC2 pins of the table). _comment: table comment tokens this rule covers (list: on all its
# pins; dict: token -> pins).
# note: key of the .inc footnote that must contain `evidence`. _also: further verbatim quotes [(source_id, quote)] the
# rule rests on (checked, not written). Keys starting with "_" are not written to the JSON.
RULES: dict[str, list[dict]] = {
    "esp32": [
        {"id": "esp32.strapping", "title": "strapping pin", "severity": "caution", "pins": [0, 2, 5, 12, 15],
         "modes": ["*"], "message": "Strapping pin: its level at reset is part of the boot configuration (see the "
                                    "ESP32 datasheet). Avoid loads or pull resistors that change it at reset.",
         "source_id": "idf-v6.1-gpio-esp32", "_comment": ["Strapping pin"], "_note": "Strapping pin",
         "evidence": "GPIO0, GPIO2, GPIO5, GPIO12 (MTDI), and GPIO15 (MTDO) are strapping pins"},
        # GPIO6-11 on every module; GPIO16/17 depend on the module (esp32.psram_16_17), so the SPI0/1 token of the
        # table is covered by both rules together
        {"id": "esp32.spi_flash", "title": "SPI flash/PSRAM", "severity": "blocked", "pins": [6, 7, 8, 9, 10, 11],
         "modes": ["*"], "message": "GPIO6-11 are usually connected to the SPI flash/PSRAM inside the module. "
                                    "Espressif: should not be used for other purposes.",
         "source_id": "idf-v6.1-gpio-esp32", "_comment": ["SPI0/1"], "_note": "SPI0/1",
         "evidence": "GPIO6-11 and GPIO16-17 are usually connected to the SPI flash and PSRAM integrated on the module "
                     "and therefore should not be used for other purposes"},
        {"id": "esp32.psram_16_17", "title": "WROVER PSRAM", "severity": "blocked", "pins": [16, 17],
         "when": {"psram": "spi"}, "modes": ["*"],
         "message": "GPIO16/17 are reserved for internal use on ESP32-WROVER modules (PSRAM). ESP-IDF: GPIO16-17 are "
                    "usually connected to the SPI flash and PSRAM of the module. ESP32-DevKitC V4 guide: usable only "
                    "on boards with ESP32-WROOM and ESP32-SOLO-1 modules.",
         "source_id": ESP32_DEVKIT_SOURCE, "_comment": ["SPI0/1"],
         "evidence": "The pins GPIO16 and GPIO17 are available for use only on the boards with the modules ESP32-WROOM "
                     "and ESP32-SOLO-1. The boards with ESP32-WROVER modules have the pins reserved for internal use."},
        {"id": "esp32.jtag", "title": "JTAG", "severity": "caution", "pins": [12, 13, 14, 15], "modes": ["*"],
         "message": "JTAG pin (GPIO12-15), usually used for inline debugging.",
         "source_id": "idf-v6.1-gpio-esp32", "_comment": ["JTAG"], "_note": "JTAG",
         "evidence": "GPIO12-15 are usually used for inline debug"},
        {"id": "esp32.input_only", "title": "input only", "severity": "blocked", "pins": [34, 35, 36, 37, 38, 39],
         "modes": OUTPUT_MODES, "message": "Input-only pin (GPIO34-39): it cannot drive an output.",
         "source_id": "idf-v6.1-gpio-esp32", "_comment": ["GPI"], "_note": "GPI",
         "evidence": "GPIO34-39 can only be set as input mode"},
        {"id": "esp32.no_pulls", "title": "no internal pull", "severity": "blocked", "pins": [34, 35, 36, 37, 38, 39],
         "modes": ["in_pullup", "in_pulldown"],
         "message": "GPIO34-39 have no internal pull-up/pull-down. Use mode 'in' with an external resistor.",
         "source_id": "idf-v6.1-gpio-esp32", "_comment": ["GPI"], "_note": "GPI",
         "evidence": "do not have software-enabled pullup or pulldown functions"},
        {"id": "esp32.uart0", "title": "UART0 (flashing)", "severity": "caution", "pins": [1, 3], "modes": ["*"],
         "message": "UART0 TXD (GPIO1) / RXD (GPIO3), usually used for flashing and debugging.",
         "source_id": "idf-v6.1-gpio-esp32", "_comment": {"TXD": [1], "RXD": [3]},
         "evidence": "TXD & RXD are usually used for flashing and debugging"},
        {"id": "esp32.adc2_wifi", "title": "ADC2 with Wi-Fi", "severity": "blocked", "pins": "ADC2", "when": {"wifi": True},
         "modes": ["adc"], "message": "ADC2 pins cannot be used while Wi-Fi is on. Use an ADC1 pin (GPIO32-39).",
         "source_id": "idf-v6.1-gpio-esp32", "_note": "ADC2",
         "evidence": "ADC2 pins cannot be used when Wi-Fi is used"},
        {"id": "esp32.gpio36_39_irq", "title": "GPIO36/39 interrupt", "severity": "info", "pins": [36, 39],
         "modes": ["in", "in_pullup", "in_pulldown"],
         "message": "Do not use the interrupt of GPIO36/GPIO39 while ADC or Wi-Fi/Bluetooth with sleep mode is enabled "
                    "(ESP32 ECO and workarounds, GPIO-3.11).",
         "source_id": "idf-v6.1-gpio-esp32",
         "evidence": "Please do not use the interrupt of GPIO36 and GPIO39 when using ADC or Wi-Fi and Bluetooth with "
                     "sleep mode enabled"},
    ],
    "esp32s2": [
        {"id": "s2.strapping", "title": "strapping pin", "severity": "caution", "pins": [0, 45, 46], "modes": ["*"],
         "message": STRAPPING_MSG.format("ESP32-S2"),
         "source_id": "idf-v6.1-gpio-esp32s2", "_comment": ["Strapping pin"], "_note": "Strapping pin",
         "evidence": "GPIO0, GPIO45 and GPIO46 are strapping pins"},
        {"id": "s2.spi_flash", "title": "SPI flash/PSRAM", "severity": "blocked", "pins": [26, 27, 28, 29, 30, 31, 32],
         "modes": ["*"], "message": "Used for the SPI flash and PSRAM of the module. Espressif: not recommended for "
                                    "other uses.",
         "source_id": "idf-v6.1-gpio-esp32s2", "_comment": ["SPI0/1"], "_note": "SPI0/1",
         "evidence": "GPIO26-32 are usually used for SPI flash and PSRAM and not recommended for other uses"},
        {"id": "s2.jtag", "title": "JTAG", "severity": "caution", "pins": [39, 40, 41, 42], "modes": ["*"],
         "message": "JTAG pin (GPIO39-42: MTCK, MTDO, MTDI, MTMS), usually used for inline debugging.",
         "source_id": "idf-v6.1-gpio-esp32s2", "_comment": ["JTAG"], "_note": "JTAG",
         "evidence": "GPIO39-42 are usually used for inline debug"},
        # input only with a fixed pull-down (i2c_* and in_pulldown are named here too, so
        # the reason is the fixed pull-down and not only the engine's generic no_output/no_pulls)
        {"id": "s2.input_only", "title": "input only", "severity": "blocked", "pins": [46],
         "modes": ["out", "pwm", "uart_tx", "spi_mosi", "spi_sck", "spi_cs", "i2c_sda", "i2c_scl", "in_pullup",
                   "in_pulldown"],
         "message": "GPIO46 is input only and fixed to pull-down: it cannot drive an output, and its pull-down is "
                    "always on (no pull-up, no switchable pull). Use mode 'in'.",
         "source_id": "idf-v6.1-gpio-esp32s2", "_comment": ["GPI"], "_note": "GPI",
         "evidence": "GPIO46 is fixed to pull-down and is input only"},
        # the gpio/esp32s2.inc table has no comment on GPIO19/20; the DevKitC-1 header table names USB_D-/USB_D+,
        # soc_caps.h has SOC_USB_OTG_SUPPORTED
        {"id": "s2.usb_otg", "title": "USB OTG", "severity": "caution", "pins": [19, 20], "modes": ["*"],
         "message": "USB OTG D- (GPIO19) / D+ (GPIO20), on the ESP32-S2-DevKitC-1 wired to the ESP32-S2 USB port "
                    "(flashing and USB communication). Using them as GPIOs gives up native USB.",
         "source_id": S2_DEVKIT_SOURCE, "evidence": "RTC_GPIO19, GPIO19, U1RTS, ADC2_CH8, CLK_OUT2, USB_D-",
         "_also": [(S2_DEVKIT_SOURCE, "RTC_GPIO20, GPIO20, U1CTS, ADC2_CH9, CLK_OUT1, USB_D+"),
                   (S2_DEVKIT_SOURCE, "ESP32-S2 full-speed USB OTG interface"),
                   ("idf-v6.1-soccaps-esp32s2", "#define SOC_USB_OTG_SUPPORTED")]},
        {"id": "s2.uart0", "title": "UART0 (console)", "severity": "caution", "pins": [43, 44], "modes": ["*"],
         "message": "UART0 U0TXD (GPIO43) / U0RXD (GPIO44): console and flashing over the USB-to-UART bridge.",
         "source_id": S2_DEVKIT_SOURCE, "evidence": "U0TXD, GPIO43, CLK_OUT1",
         "_also": [(S2_DEVKIT_SOURCE, "U0RXD, GPIO44, CLK_OUT2")]},
        {"id": "s2.adc2_wifi", "title": "ADC2 with Wi-Fi (unverified)", "severity": "info", "pins": "ADC2",
         "when": {"wifi": True}, "modes": ["adc"], "unverified": True,
         "message": "ADC2 is shared with Wi-Fi. Whether ADC2 readings work while Wi-Fi is on is unverified; prefer an "
                    "ADC1 pin (GPIO1-10).",
         "source_id": ADC_ONESHOT_SOURCE, "evidence": "ADC2 is also used by Wi-Fi",
         "_also": [(ADC_ONESHOT_SOURCE, ":esp32 or esp32s2 or esp32s3: - ADC2 is also used by Wi-Fi")]},
    ],
    "esp32s3": [
        {"id": "s3.strapping", "title": "strapping pin", "severity": "caution", "pins": [0, 3, 45, 46], "modes": ["*"],
         "message": "Strapping pin: its level at reset is part of the boot configuration (see the ESP32-S3 datasheet). "
                    "Avoid loads or pull resistors that change it at reset.",
         "source_id": "idf-v6.1-gpio-esp32s3", "_comment": ["Strapping pin"], "_note": "Strapping pin",
         "evidence": "GPIO0, GPIO3, GPIO45 and GPIO46 are strapping pins"},
        {"id": "s3.spi_flash", "title": "SPI flash/PSRAM", "severity": "blocked", "pins": [26, 27, 28, 29, 30, 31, 32],
         "modes": ["*"], "message": "Used for the SPI flash and PSRAM of the module. Espressif: not recommended for "
                                    "other uses.",
         "source_id": "idf-v6.1-gpio-esp32s3", "_comment": ["SPI0/1"], "_note": "SPI0/1",
         "evidence": "GPIO26 ~ GPIO32 are usually used for SPI flash and PSRAM and not recommended for other uses"},
        {"id": "s3.octal_psram", "title": "octal PSRAM", "severity": "blocked", "pins": [33, 34, 35, 36, 37],
         "when": {"psram": "octal"}, "modes": ["*"],
         "message": "Wired to the octal PSRAM bus (SPIIO4–7, SPIDQS). Espressif: not recommended for other uses.",
         "source_id": "idf-v6.1-gpio-esp32s3", "_comment": ["SPI0/1"], "_note": "SPI0/1",
         "evidence": "GPIO33 ~ GPIO37 are connected to SPIIO4 ~ SPIIO7 and SPIDQS"},
        {"id": "s3.usb_jtag", "title": "USB-JTAG", "severity": "caution", "pins": [19, 20], "modes": ["*"],
         "message": "Used by USB-Serial/JTAG by default (USB D-/D+). Using it as a GPIO disables USB-JTAG.",
         "source_id": "idf-v6.1-gpio-esp32s3", "_comment": ["USB-JTAG"], "_note": "USB-JTAG",
         "evidence": "GPIO19 and GPIO20 are used by USB-JTAG by default"},
        {"id": "s3.uart0", "title": "UART0 (console)", "severity": "caution", "pins": [43, 44], "modes": ["*"],
         "message": "UART0 U0TXD (GPIO43) / U0RXD (GPIO44): console and flashing over the USB-to-UART bridge.",
         "source_id": DEVKIT_SOURCE, "evidence": "U0TXD, GPIO43"},
        {"id": "s3.pad_jtag", "title": "pad JTAG", "severity": "info", "pins": [39, 40, 41, 42], "modes": ["*"],
         "message": "Pad JTAG (MTCK/MTDO/MTDI/MTMS); relevant only if pad JTAG is used.",
         "source_id": DEVKIT_SOURCE, "evidence": "MTCK, GPIO39"},
        {"id": "s3.adc2_wifi", "title": "ADC2 with Wi-Fi (unverified)", "severity": "info", "pins": "ADC2",
         "when": {"wifi": True}, "modes": ["adc"], "unverified": True,
         "message": "ADC2 is shared with Wi-Fi. Whether ADC2 readings work while Wi-Fi is on is unverified; prefer an "
                    "ADC1 pin (GPIO1-10).",
         "source_id": ADC_ONESHOT_SOURCE, "evidence": "ADC2 is also used by Wi-Fi"},
    ],
    "esp32c3": [
        {"id": "c3.strapping", "title": "strapping pin", "severity": "caution", "pins": [2, 8, 9], "modes": ["*"],
         "message": "Strapping pin: its level at reset is part of the boot configuration (see the ESP32-C3 datasheet). "
                    "Avoid loads or pull resistors that change it at reset.",
         "source_id": "idf-v6.1-gpio-esp32c3", "_comment": ["Strapping pin"], "_note": "Strapping pin",
         "evidence": "GPIO2, GPIO8 and GPIO9 are strapping pins"},
        {"id": "c3.spi_flash", "title": "SPI flash", "severity": "blocked", "pins": [12, 13, 14, 15, 16, 17],
         "modes": ["*"], "message": "Used for the SPI flash. Espressif: not recommended for other uses.",
         "source_id": "idf-v6.1-gpio-esp32c3", "_comment": ["SPI0/1"], "_note": "SPI0/1",
         "evidence": "GPIO12 ~ GPIO17 are usually used for SPI flash and are not recommended for other uses"},
        {"id": "c3.usb_jtag", "title": "USB-JTAG", "severity": "caution", "pins": [18, 19], "modes": ["*"],
         "message": "Used by USB-Serial/JTAG by default (USB D-/D+). Using it as a GPIO disables USB-JTAG.",
         "source_id": "idf-v6.1-gpio-esp32c3", "_comment": ["USB-JTAG"], "_note": "USB-JTAG",
         "evidence": "GPIO18 and GPIO19 are used by USB-JTAG by default"},
        # the gpio/esp32c3.inc table has no comment on GPIO20/21; the DevKitM-1 header table names them U0RXD/U0TXD
        {"id": "c3.uart0", "title": "UART0 (console)", "severity": "caution", "pins": [20, 21], "modes": ["*"],
         "message": "UART0 U0TXD (GPIO21) / U0RXD (GPIO20): console and flashing over the USB-to-UART bridge.",
         "source_id": C3_DEVKIT_SOURCE, "evidence": "GPIO21, U0TXD"},
        {"id": "c3.adc2", "title": "ADC2 oneshot", "severity": "caution", "pins": "ADC2", "modes": ["adc"],
         "message": "ESP-IDF no longer supports ADC2 oneshot mode on the ESP32-C3 (unstable results, see the "
                    "ESP32-C3 errata). Use an ADC1 pin (GPIO0-4).",
         "source_id": ADC_ONESHOT_SOURCE,
         "evidence": "ADC2 oneshot mode is no longer supported, due to hardware limitations"},
    ],
    "esp32c6": [
        {"id": "c6.strapping", "title": "strapping pin", "severity": "caution", "pins": [4, 5, 8, 9, 15], "modes": ["*"],
         "message": STRAPPING_MSG.format("ESP32-C6"),
         "source_id": "idf-v6.1-gpio-esp32c6", "_comment": ["Strapping pin"], "_note": "Strapping pin",
         "evidence": "GPIO4, GPIO5, GPIO8, GPIO9, and GPIO15 are strapping pins"},
        {"id": "c6.spi_flash", "title": "SPI flash", "severity": "blocked", "pins": [24, 25, 26, 27, 28, 29, 30],
         "modes": ["*"], "message": "Used for the SPI flash. Espressif: not recommended for other uses.",
         "source_id": "idf-v6.1-gpio-esp32c6", "_comment": ["SPI0/1"], "_note": "SPI0/1",
         "evidence": "GPIO24 ~ GPIO30 are usually used for SPI flash and not recommended for other uses"},
        {"id": "c6.usb_jtag", "title": "USB-JTAG", "severity": "caution", "pins": [12, 13], "modes": ["*"],
         "message": "Used by USB-Serial/JTAG by default (USB D-/D+). Using it as a GPIO disables USB-JTAG.",
         "source_id": "idf-v6.1-gpio-esp32c6", "_comment": ["USB-JTAG"], "_note": "USB-JTAG",
         "evidence": "GPIO12 and GPIO13 are used by USB-JTAG by default"},
        # the gpio/esp32c6.inc table has no comment on GPIO16/17; the DevKitC-1 header table names U0TXD/U0RXD
        {"id": "c6.uart0", "title": "UART0 (console)", "severity": "caution", "pins": [16, 17], "modes": ["*"],
         "message": "UART0 U0TXD (GPIO16) / U0RXD (GPIO17): console and flashing over the USB-to-UART bridge.",
         "source_id": C6_DEVKIT_SOURCE, "evidence": "U0TXD, GPIO16, FSPICS0",
         "_also": [(C6_DEVKIT_SOURCE, "U0RXD, GPIO17, FSPICS1")]},
        # chip variants (footnotes of gpio/esp32c6.inc); which chip a module carries comes from its datasheet (VARIANTS)
        {"id": "c6.sip_flash", "title": "not led out (in-package flash)", "severity": "blocked", "pins": [10, 11],
         "when": {"variant": "mini-1"}, "modes": ["*"],
         "message": "Not led out to any chip pin on ESP32-C6 variants with in-package (SiP) flash, such as the "
                    "ESP32-C6FH4/FH8 of the ESP32-C6-MINI-1.",
         "source_id": "idf-v6.1-gpio-esp32c6",
         "evidence": "GPIO10 ~ GPIO11 are not led out to any chip pins"},
        {"id": "c6.no_sip_flash", "title": "not led out (no in-package flash)", "severity": "blocked", "pins": [14],
         "when": {"variant": "wroom-1"}, "modes": ["*"],
         "message": "Not led out to any chip pin on ESP32-C6 variants without in-package flash, such as the ESP32-C6 "
                    "of the ESP32-C6-WROOM-1.",
         "source_id": "idf-v6.1-gpio-esp32c6",
         "evidence": "For chip variants without an in-package flash, GPIO14 is not led out to any chip pins"},
    ],
}

# --- module variants (step 3); each row is checked against the table of its source --------------------------------
# S3: Table 1-1 of the ESP32-S3-WROOM-1 datasheet excerpt (flash, PSRAM size and bus). ESP32: the ordering table of the
# ESP32-DevKitC V4 guide (module, flash, PSRAM size); `evidence` is the verbatim RST row from the part number to the
# PSRAM cell. It names no PSRAM bus width, so the WROVER-E gets psram "spi" (PSRAM on the SPI0/1 bus: gpio/esp32.inc
# "SPI0/1: ... SPI flash and PSRAM", DevKitC guide "SPI flash memory/SPI RAM"), never "quad"/"octal".
# Order: the desktop takes the last variant as the default of a chip (PLAN chip switch, new-project dialog), so the
# standard module of the chip's DevKit comes last (ESP32-DevKitC-32E = ESP32-WROOM-32E, first row of the ordering
# table; data/boards/esp32-devkitc-v4.json module.variant). ESP32-WROOM-32UE / -WROVER-IE differ only in the antenna.
VARIANTS: dict[str, list[dict]] = {
    "esp32": [
        {"id": "wrover-e", "label": "WROVER-E", "module": "ESP32-WROVER-E", "flash_mb": 8, "psram": "spi", "psram_mb": 8,
         "source_id": ESP32_ORDERING_SOURCE, "evidence": "ESP32-DevKitC-VE\n     - ESP32-WROVER-E\n     - 8 MB\n     - 8 MB"},
        {"id": "wroom-32e", "label": "WROOM-32E", "module": "ESP32-WROOM-32E", "flash_mb": 4, "psram": None,
         "psram_mb": 0, "source_id": ESP32_ORDERING_SOURCE,
         "evidence": "ESP32-DevKitC-32E\n     - ESP32-WROOM-32E\n     - 4 MB\n     - ---"},
    ],
    # Table 1-1 order without H4 (same memory as N4, only the temperature range differs) and without N16R16VA (the
    # meaning of "VA" and of footnote 7 is not in the pinned excerpt); n16r8 stays last (DevKitC-1 standard).
    # `evidence` is the whole raw row. The ESP32-S3-WROOM-1U row with the same memory must exist (antenna only).
    "esp32s3": [
        {"id": "n4", "label": "N4", "module": "ESP32-S3-WROOM-1-N4", "flash_mb": 4, "psram": None, "psram_mb": 0,
         "source_id": DATASHEET_SOURCE, "evidence": "ESP32-S3-WROOM-1-N4 4 MB (Quad SPI) - –40 ~85"},
        {"id": "n8", "label": "N8", "module": "ESP32-S3-WROOM-1-N8", "flash_mb": 8, "psram": None, "psram_mb": 0,
         "source_id": DATASHEET_SOURCE, "evidence": "ESP32-S3-WROOM-1-N8 8 MB (Quad SPI) - –40 ~85"},
        {"id": "n16", "label": "N16", "module": "ESP32-S3-WROOM-1-N16", "flash_mb": 16, "psram": None, "psram_mb": 0,
         "source_id": DATASHEET_SOURCE, "evidence": "ESP32-S3-WROOM-1-N16 16 MB (Quad SPI) - –40 ~85"},
        {"id": "n4r2", "label": "N4R2", "module": "ESP32-S3-WROOM-1-N4R2", "flash_mb": 4, "psram": "quad", "psram_mb": 2,
         "source_id": DATASHEET_SOURCE, "evidence": "ESP32-S3-WROOM-1-N4R2 4 MB (Quad SPI) 2 MB (Quad SPI) –40 ~85"},
        {"id": "n8r2", "label": "N8R2", "module": "ESP32-S3-WROOM-1-N8R2", "flash_mb": 8, "psram": "quad", "psram_mb": 2,
         "source_id": DATASHEET_SOURCE, "evidence": "ESP32-S3-WROOM-1-N8R2 8 MB (Quad SPI) 2 MB (Quad SPI) –40 ~85"},
        {"id": "n16r2", "label": "N16R2", "module": "ESP32-S3-WROOM-1-N16R2", "flash_mb": 16, "psram": "quad",
         "psram_mb": 2, "source_id": DATASHEET_SOURCE,
         "evidence": "ESP32-S3-WROOM-1-N16R2 16 MB (Quad SPI) 2 MB (Quad SPI) –40 ~85"},
        {"id": "n4r8", "label": "N4R8", "module": "ESP32-S3-WROOM-1-N4R8", "flash_mb": 4, "psram": "octal",
         "psram_mb": 8, "source_id": DATASHEET_SOURCE,
         "evidence": "ESP32-S3-WROOM-1-N4R8 4 MB (Quad SPI) 8 MB (Octal SPI) –40 ~65"},
        {"id": "n8r8", "label": "N8R8", "module": "ESP32-S3-WROOM-1-N8R8", "flash_mb": 8, "psram": "octal",
         "psram_mb": 8, "source_id": DATASHEET_SOURCE,
         "evidence": "ESP32-S3-WROOM-1-N8R8 8 MB (Quad SPI) 8 MB (Octal SPI) –40 ~65"},
        {"id": "n16r8", "label": "N16R8", "module": "ESP32-S3-WROOM-1-N16R8", "flash_mb": 16, "psram": "octal",
         "psram_mb": 8, "source_id": DATASHEET_SOURCE,
         "evidence": "ESP32-S3-WROOM-1-N16R8 16 MB (Quad SPI) 8 MB (Octal SPI) –40 ~65"},
    ],
    # C6: the variant is the module family, i.e. the chip inside. `evidence` names
    # the chip ("At the core of the modules is ..."); the module comes from the Table 1-1 title of the same excerpt.
    # flash_mb is null: each family comes with several flash sizes (Table 1-1), the board's module names its own.
    # No PSRAM: the ESP32-C6 soc_caps.h has no SOC_SPIRAM_SUPPORTED. _in_package_flash / _not_led_out are checked
    # against the excerpt (chip name, footnote, Table 3-1 pins) and against the rules with when.variant.
    # Order: wroom-1 (ESP32-C6-DevKitC-1, the chip's main DevKit) last = standard.
    "esp32c6": [
        {"id": "mini-1", "label": "MINI-1", "module": "ESP32-C6-MINI-1", "flash_mb": None, "psram": None,
         "psram_mb": 0, "source_id": C6_MINI_SOURCE,
         "evidence": "At the core of the modules is ESP32-C6FH4/ESP32-C6FH8, a 32-bit RISC-V single-core processor.",
         "_in_package_flash": True, "_not_led_out": [10, 11]},
        {"id": "wroom-1", "label": "WROOM-1", "module": "ESP32-C6-WROOM-1", "flash_mb": None, "psram": None,
         "psram_mb": 0, "source_id": C6_WROOM_SOURCE,
         "evidence": "At the core of the modules is ESP32-C6, a 32-bit RISC-V single-core processor.",
         "_in_package_flash": False, "_not_led_out": [14]},
    ],
}


class GenError(Exception):
    pass


# --- corpus ---------------------------------------------------------------------------------------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_corpus(corpus: Path) -> dict[str, dict]:
    """source_id -> {"entry", "data", "text"} with verified SHA-256. ``text`` is the excerpt for PDFs."""
    spec = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for entry in spec["files"]:
        path = corpus / entry["path"]
        if not path.is_file():
            raise GenError(f"corpus file missing: {path} (run scripts/fetch_corpus.py pins)")
        data = path.read_bytes()
        if not entry.get("sha256") or _sha256(data) != entry["sha256"]:
            raise GenError(f"SHA-256 mismatch for {entry['path']}")
        if entry.get("excerpt"):
            text = (MANIFEST_DIR / entry["excerpt"]).read_text(encoding="utf-8")
        else:
            text = data.decode("utf-8")
        sid = entry["source_id"]
        if sid in out:
            raise GenError(f"two corpus files for source {sid}")
        out[sid] = {"entry": entry, "data": data, "text": text}
    return out


def _file_ref(item: dict) -> dict:
    """generated_from.files entry: repo path for GitHub raw URLs, otherwise the URL."""
    e = item["entry"]
    m = re.match(r"https://raw\.githubusercontent\.com/([^/]+/[^/]+)/([0-9a-f]{40})/(.+)$", e["url"])
    if m and m.group(1) == IDF_REPO:
        if m.group(2) != IDF_COMMIT:
            raise GenError(f"{e['path']}: not pinned to {IDF_COMMIT}")
        ref = {"path": m.group(3)}
    elif m:
        ref = {"repo": m.group(1), "commit": m.group(2), "path": m.group(3)}
    else:
        ref = {"url": e["url"]}
        if e.get("excerpt"):
            ref["excerpt"] = f"tests/corpus/{e['excerpt']}"
    ref["sha256"] = e["sha256"]
    ref["source_id"] = e["source_id"]
    return ref


# --- parsers --------------------------------------------------------------------------------------------------------
def parse_list_table(text: str, anchor: str | None = None) -> list[list[str]]:
    lines = text.splitlines()
    i = 0
    if anchor:
        i = next((n for n, line in enumerate(lines) if line.strip() == f".. {anchor}"), -1)
        if i < 0:
            raise GenError(f"anchor .. {anchor} not found")
    start = next((n for n in range(i, len(lines)) if lines[n].strip() == ".. list-table::"), -1)
    if start < 0:
        raise GenError("no list-table found")
    rows: list[list[str]] = []
    for line in lines[start + 1:]:
        s = line.strip()
        if not s or s.startswith(":"):
            continue
        if line.startswith(".. ") or s == "---":
            break
        m = re.match(r"^\s*\* -\s?(.*)$", line)
        if m:
            rows.append([m.group(1).strip()])
            continue
        m = re.match(r"^\s*-\s?(.*)$", line)
        if m and rows:
            rows[-1].append(m.group(1).strip())
            continue
        raise GenError(f"unexpected line in list-table: {line!r}")
    return rows


def parse_notes(text: str) -> list[str]:
    """Bullets of the first '.. note::' block."""
    lines = text.splitlines()
    start = next((n for n, line in enumerate(lines) if re.match(r"^\.\. [Nn]ote::\s*$", line)), -1)
    if start < 0:
        raise GenError("no note block")
    notes: list[str] = []
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):  # gpio/esp32c6.inc indents two of its bullets with a tab
            break
        m = re.match(r"^\s+- (.*)$", line)
        if m:
            notes.append(m.group(1).strip())
        elif notes:
            notes[-1] += " " + line.strip()
    return notes


def note_key(note: str) -> str | None:
    m = re.match(r"^([A-Za-z0-9/&\- ]{1,20}): ", note)
    return m.group(1) if m else None


def parse_defines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*#define\s+(\w+)(\(?)(.*)$", line)
        if not m or m.group(2):  # skip function-like macros
            continue
        value = re.sub(r"/\*.*?\*/", "", m.group(3))
        value = value.split("//", 1)[0].strip()
        out[m.group(1)] = value
    return out


_BINOPS = {ast.BitOr: lambda a, b: a | b, ast.BitAnd: lambda a, b: a & b, ast.LShift: lambda a, b: a << b,
           ast.RShift: lambda a, b: a >> b, ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b}


def eval_macro(name: str, defines: dict[str, str], depth: int = 0) -> int:
    if depth > 8 or name not in defines:
        raise GenError(f"cannot evaluate macro {name}")
    expr = re.sub(r"\b(0x[0-9A-Fa-f]+|\d+)(?:ULL|UL|LL|U|L)\b", r"\1", defines[name])
    expr = re.sub(r"\bBIT\((\d+)\)", r"(1 << \1)", expr)
    expr = re.sub(r"\bBIT(\d+)\b", r"(1 << \1)", expr)

    def ev(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name):
            return eval_macro(node.id, defines, depth + 1)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            return ~ev(node.operand)
        raise GenError(f"unsupported expression in {name}: {defines[name]!r}")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise GenError(f"cannot parse macro {name}: {defines[name]!r}") from None
    return ev(tree)


def bits(mask: int) -> set[int]:
    return {n for n in range(64) if mask >> n & 1}


def parse_gpio_table(text: str) -> tuple[list[dict], int]:
    rows = parse_list_table(text)
    names = {"GPIO": "gpio", "Analog Function": "analog", "RTC GPIO": "rtc", "LP GPIO": "rtc", "Comment": "comment",
             "Comments": "comment"}
    try:
        header = [names[h] for h in rows[0]]
    except KeyError as e:
        raise GenError(f"unknown column {e}") from None
    if header[0] != "gpio" or "comment" not in header:
        raise GenError(f"unexpected columns {rows[0]}")
    out = []
    for row in rows[1:]:
        if len(row) != len(header):
            raise GenError(f"row has {len(row)} cells, header {len(header)}: {row}")
        cell = dict(zip(header, row, strict=True))
        m = re.fullmatch(r"GPIO(\d+)", cell["gpio"])
        if not m:
            raise GenError(f"bad GPIO cell {cell['gpio']!r}")
        g = {"num": int(m.group(1)), "adc": None, "rtc_gpio": None, "rtc_name": None}
        if cell.get("analog"):
            a = re.fullmatch(r"ADC([12])_CH(\d+)", cell["analog"])
            if not a:
                raise GenError(f"bad analog cell {cell['analog']!r}")
            g["adc"] = {"unit": int(a.group(1)), "channel": int(a.group(2))}
        if cell.get("rtc"):  # RTC_GPIOn (RTC GPIO column) or LP_GPIOn (LP GPIO column, ESP32-C6)
            r = re.fullmatch(r"(?:RTC|LP)_GPIO(\d+)", cell["rtc"])
            if not r:
                raise GenError(f"bad RTC cell {cell['rtc']!r}")
            g["rtc_gpio"], g["rtc_name"] = int(r.group(1)), cell["rtc"]
        g["tags"] = [t.strip() for t in re.split(r"[;；]", cell["comment"]) if t.strip()]
        out.append(g)
    m = re.search(r"features (\d+) physical GPIO pins", text)
    if not m:
        raise GenError("GPIO count sentence not found")
    return out, int(m.group(1))


def parse_adc_channels(text: str) -> dict[tuple[int, int], int]:
    out = {}
    for unit, ch, gpio in re.findall(r"#define\s+ADC([12])_CHANNEL_(\d+)_GPIO_NUM\s+(\d+)", text):
        out[(int(unit), int(ch))] = int(gpio)
    back = {}
    for unit, gpio, ch in re.findall(r"#define\s+ADC([12])_GPIO(\d+)_CHANNEL\s+(\d+)", text):
        back[(int(unit), int(ch))] = int(gpio)
    if not out or out != back:
        raise GenError("adc_channel.h: CHANNEL_n_GPIO_NUM and GPIOn_CHANNEL disagree")
    return out


def parse_iomux(text: str) -> dict[int, list[str]]:
    regs = {int(n): pad for n, pad in re.findall(r"#define\s+IO_MUX_GPIO(\d+)_REG\s+PERIPHS_IO_MUX_(\w+?)_U\b", text)}
    pads = sorted(set(regs.values()), key=len, reverse=True)
    funcs: dict[str, list[tuple[int, str]]] = {}
    for full, idx in re.findall(r"#define\s+FUNC_(\w+)\s+(\d+)\b", text):
        pad = next((p for p in pads if full.startswith(p + "_")), None)
        if pad:
            funcs.setdefault(pad, []).append((int(idx), full[len(pad) + 1:]))
    out = {}
    for num, pad in regs.items():
        names = [n for _, n in sorted(funcs.get(pad, []))]
        names = [n for n in names if not (re.fullmatch(r"GPIO\d+_0", n) and n[:-2] in names)]
        out[num] = list(dict.fromkeys(names))
    return out


def parse_touch(text: str) -> dict[int, int]:
    rows = parse_list_table(text, "touch-chan-mapping")
    if rows[0] != ["Channel", "GPIO"]:
        raise GenError(f"unexpected touch columns {rows[0]}")
    out = {}
    for ch, io in rows[1:]:
        c = re.fullmatch(r"CH(\d+)", ch)
        if not c:
            raise GenError(f"bad touch channel {ch!r}")
        if io == "Internal":
            continue
        g = re.fullmatch(r"IO(\d+)", io)
        if not g:
            raise GenError(f"bad touch GPIO {io!r}")
        out[int(g.group(1))] = int(c.group(1))
    return out


def parse_variant_table(text: str) -> dict[str, tuple[int, str | None, int]]:
    """Datasheet Table 1-1/1-2 rows (WROOM-1 and WROOM-1U): part -> (flash MB, PSRAM type, PSRAM MB)."""
    out = {}
    pat = r"^(ESP32-S3-WROOM-1U?-\w+) (\d+) MB \(Quad SPI\) (?:(\d+) MB \((Quad|Octal) SPI\)|-) "
    for part, flash, psram_mb, psram in re.findall(pat, text, flags=re.M):
        out[part] = (int(flash), psram.lower() if psram else None, int(psram_mb or 0))
    if not out:
        raise GenError("datasheet excerpt: no Table 1-1 rows")
    return out


def parse_module_excerpt(text: str) -> dict:
    """ESP32-C6 module datasheet excerpt: module (Table 1-1 title), chip ("At the core of the modules is ..."),
    in-package flash (chip name ESP32-C6FHn and the footnote), GPIOs led out (IOn rows of Table 3-1)."""
    m = re.search(r"^T ?able 1-1\. (ESP32-C6-[A-Z]+-1) \(ANT\) Series Comparison", text, flags=re.M)
    c = re.search(r"At the core of the modules is (ESP32-C6(?:FH\d)?(?:/ESP32-C6FH\d)*), ", text)
    if not m or not c:
        raise GenError("module excerpt: Table 1-1 title or chip sentence not found")
    chips_inside = c.group(1).split("/")
    in_package = [bool(re.fullmatch(r"ESP32-C6FH\d", x)) for x in chips_inside]
    if len(set(in_package)) != 1:
        raise GenError(f"module excerpt: mixed chips {chips_inside}")
    footnote = "The flash is integrated in the chip’s package" in text
    if in_package[0] != footnote:
        raise GenError(f"module excerpt: chip {c.group(1)} vs in-package flash footnote {footnote}")
    ios = {int(n) for n in re.findall(r"^IO(\d+) \d+ I/O/T GPIO\1\b", text, flags=re.M)}
    if not ios:
        raise GenError("module excerpt: no IOn rows of Table 3-1")
    return {"module": m.group(1), "chips": chips_inside, "in_package_flash": in_package[0], "ios": ios}


def parse_ordering_table(text: str) -> dict[str, tuple[int, int]]:
    """esp-dev-kits ordering-info.inc list-table: on-board module -> (flash MB, PSRAM MB); '---' = no PSRAM."""
    rows = parse_list_table(text)
    if not rows or rows[0] != ["Part Number", "On-board Module", "Flash", "PSRAM", "Antenna"]:
        raise GenError(f"ordering table: unexpected columns {rows[0] if rows else None}")
    out: dict[str, tuple[int, int]] = {}
    for row in rows[1:]:
        if len(row) != 5:
            raise GenError(f"ordering table: row has {len(row)} cells: {row}")
        flash = re.fullmatch(r"(\d+) MB", row[2])
        psram = re.fullmatch(r"(\d+) MB|---", row[3])
        if not flash or not psram:
            raise GenError(f"ordering table: bad flash/PSRAM cell in {row}")
        out[row[1]] = (int(flash.group(1)), int(psram.group(1) or 0))
    return out


# --- build ----------------------------------------------------------------------------------------------------------
def _known_sources() -> set[str]:
    ids: set[str] = set()
    for path in sorted(SOURCES_DIR.glob("*.json")):
        ids.update(e["id"] for e in json.loads(path.read_text(encoding="utf-8")))
    return ids


def build(chip: str, corpus: dict[str, dict]) -> dict:
    from circuit_bench.bench_core.contracts import MODES, RULE_SEVERITIES

    if chip not in RULES:
        raise GenError(f"{chip}: no rule table in RULES")
    title = CHIPS[chip]
    used = [f"idf-v6.1-gpio-{chip}", f"idf-v6.1-soccaps-{chip}", f"idf-v6.1-adc-channel-{chip}", f"idf-v6.1-iomux-{chip}"]
    gpio_text = corpus[used[0]]["text"]
    table, count = parse_gpio_table(gpio_text)
    nums = [g["num"] for g in table]
    if len(table) != count or len(set(nums)) != len(nums) or nums != sorted(nums):
        raise GenError(f"{chip}: table has {len(table)} unique sorted GPIOs, text says {count}")

    defines = parse_defines(corpus[used[1]]["text"])
    valid = bits(eval_macro("SOC_GPIO_VALID_GPIO_MASK", defines))
    output = bits(eval_macro("SOC_GPIO_VALID_OUTPUT_GPIO_MASK", defines))
    if set(nums) != valid - MASK_EXTRA.get(chip, set()):
        raise GenError(f"{chip}: table GPIOs differ from SOC_GPIO_VALID_GPIO_MASK: {sorted(set(nums) ^ valid)}")
    gpi = {g["num"] for g in table if "GPI" in g["tags"]}
    if gpi != set(nums) - output:
        raise GenError(f"{chip}: GPI pins {sorted(gpi)} differ from soc_caps input-only {sorted(set(nums) - output)}")

    adc = parse_adc_channels(corpus[used[2]]["text"])
    table_adc = {(g["adc"]["unit"], g["adc"]["channel"]): g["num"] for g in table if g["adc"]}
    if adc != table_adc:
        diff = sorted(set(adc.items()) ^ set(table_adc.items()))
        raise GenError(f"{chip}: ADC channels differ between gpio table and adc_channel.h: {diff}")

    iomux = parse_iomux(corpus[used[3]]["text"])
    missing = [n for n in nums if not iomux.get(n)]
    if missing:
        raise GenError(f"{chip}: no IO MUX functions for {missing}")

    touch_sid = f"idf-v6.1-touch-{chip}"
    touch: dict[int, int] = {}
    has_touch = "SOC_TOUCH_SENSOR_SUPPORTED" in defines
    if has_touch != (touch_sid in corpus):
        raise GenError(f"{chip}: SOC_TOUCH_SENSOR_SUPPORTED={has_touch} but touch table present={touch_sid in corpus}")
    if has_touch:
        used.append(touch_sid)
        touch = parse_touch(corpus[touch_sid]["text"])
        if not set(touch) <= set(nums) or max(touch.values()) != eval_macro("SOC_TOUCH_MAX_CHAN_ID", defines):
            raise GenError(f"{chip}: touch table does not match the GPIO table / SOC_TOUCH_MAX_CHAN_ID")

    data_tokens = DATA_TOKENS.get(chip, set())
    gpios = []
    for g in table:
        n = g["num"]
        functions = list(iomux[n])
        if g["rtc_name"] is not None:
            functions.append(g["rtc_name"])
        if g["adc"]:
            functions.append(f"ADC{g['adc']['unit']}_CH{g['adc']['channel']}")
        if n in touch:
            functions.append(f"TOUCH{touch[n]}")
        gpios.append({
            "num": n, "name": f"GPIO{n}",
            "rtc": g["rtc_gpio"] is not None or "RTC" in g["tags"],
            "adc": g["adc"], "touch": touch.get(n), "input_only": n in gpi,
            # the .inc names the only pins without internal pulls (GPI); all others have them
            "internal_pulls": n not in gpi,
            "functions": list(dict.fromkeys(functions)),
            "tags": [t for t in g["tags"] if t not in data_tokens] or [],
        })

    # rules
    notes = parse_notes(gpio_text)
    keyed = {note_key(t): t for t in notes if note_key(t)}
    known = _known_sources()
    adc2 = sorted(g["num"] for g in table if g["adc"] and g["adc"]["unit"] == 2)
    rules = []
    token_pins: dict[str, set[int]] = {}
    for spec in RULES[chip]:
        pins = adc2 if spec["pins"] == "ADC2" else list(spec["pins"])
        if not pins or not set(pins) <= set(nums):
            raise GenError(f"{spec['id']}: pins {pins} not on {title}")
        if spec["severity"] not in RULE_SEVERITIES:
            raise GenError(f"{spec['id']}: bad severity")
        if spec["modes"] != ["*"] and not set(spec["modes"]) <= set(MODES):
            raise GenError(f"{spec['id']}: bad modes {spec['modes']}")
        if not set(spec.get("when", {})) <= {"psram", "wifi", "variant"}:
            raise GenError(f"{spec['id']}: bad when {spec.get('when')}")
        sid = spec["source_id"]
        if sid not in known or sid not in corpus:
            raise GenError(f"{spec['id']}: source {sid} unknown or not in the corpus")
        if spec["severity"] != "info" and spec.get("unverified"):
            raise GenError(f"{spec['id']}: unverified rules must be severity info")
        haystack = corpus[sid]["text"]
        if sid == used[0]:
            haystack = keyed[spec["_note"]] if spec.get("_note") else "\n".join(notes)
        if spec["evidence"] not in haystack:
            raise GenError(f"{spec['id']}: evidence not found in {sid}: {spec['evidence']!r}")
        for also_sid, quote in spec.get("_also", []):
            if also_sid not in corpus or quote not in corpus[also_sid]["text"]:
                raise GenError(f"{spec['id']}: quote not found in {also_sid}: {quote!r}")
        tokens = spec.get("_comment", [])
        for tok in tokens:
            token_pins.setdefault(tok, set()).update(tokens[tok] if isinstance(tokens, dict) else pins)
        if sid not in used:
            used.append(sid)
        rule = {k: v for k, v in spec.items() if not k.startswith("_")}
        rule["pins"] = pins
        rule.setdefault("when", {})
        order = ("id", "title", "severity", "pins", "when", "modes", "message", "source_id", "evidence", "unverified")
        rules.append({k: rule[k] for k in order if k in rule})
    table_tokens = {t for g in table for t in g["tags"]} - data_tokens
    if table_tokens != set(token_pins):
        raise GenError(f"{chip}: comment tokens {sorted(table_tokens)} vs rules {sorted(token_pins)}")
    for tok, pins in token_pins.items():
        have = {g["num"] for g in table if tok in g["tags"]}
        if have != pins:
            raise GenError(f"{chip}: comment {tok!r} on {sorted(have)}, rules cover {sorted(pins)}")

    # variants
    variants = []
    ids: set[str] = set()
    for v in VARIANTS.get(chip, []):
        sid = v["source_id"]
        if sid not in known or sid not in corpus:
            raise GenError(f"variant {v['id']}: source {sid} unknown or not in the corpus")
        if v["id"] in ids or not re.fullmatch(r"[a-z0-9-]{1,16}", v["id"]):
            raise GenError(f"variant {v['id']}: id duplicate or not [a-z0-9-]")
        ids.add(v["id"])
        if v["evidence"] not in corpus[sid]["text"]:
            raise GenError(f"variant {v['id']}: evidence not in {sid}")
        named = v["module"]  # the module the evidence must name
        if sid == DATASHEET_SOURCE:
            table = parse_variant_table(corpus[sid]["text"])
            got = table.get(v["module"])
            want: tuple = (v["flash_mb"], v["psram"], v["psram_mb"])
            if v["evidence"] not in corpus[sid]["text"].splitlines():
                raise GenError(f"variant {v['id']}: evidence is not a whole row of {sid}")
            if table.get(v["module"].replace("-WROOM-1-", "-WROOM-1U-")) != got:
                raise GenError(f"variant {v['id']}: no WROOM-1U row with the same flash/PSRAM")
        elif sid in MODULE_SOURCES:
            mod = parse_module_excerpt(corpus[sid]["text"])
            got = (mod["module"], mod["in_package_flash"], None, 0)
            want = (v["module"], v["_in_package_flash"], v["flash_mb"], v["psram_mb"])
            named = mod["chips"][0]
            if v["psram"] is not None or "SOC_SPIRAM_SUPPORTED" in defines:
                raise GenError(f"variant {v['id']}: PSRAM {v['psram']!r}, SOC_SPIRAM_SUPPORTED in soc_caps.h")
            if set(v["_not_led_out"]) & mod["ios"]:
                raise GenError(f"variant {v['id']}: {sorted(set(v['_not_led_out']) & mod['ios'])} are led out")
            others = {p for o in VARIANTS[chip] if o["id"] != v["id"] for p in o.get("_not_led_out", [])}
            if not others <= mod["ios"]:
                raise GenError(f"variant {v['id']}: {sorted(others - mod['ios'])} missing in Table 3-1 of {sid}")
            mine = sorted(p for r in rules if r["when"].get("variant") == v["id"] for p in r["pins"])
            if mine != sorted(v["_not_led_out"]):
                raise GenError(f"variant {v['id']}: rules with when.variant cover {mine}, not {v['_not_led_out']}")
        elif sid == ESP32_ORDERING_SOURCE:
            got = parse_ordering_table(corpus[sid]["text"]).get(v["module"])
            want = (v["flash_mb"], v["psram_mb"])
            if (v["psram"] is None) != (v["psram_mb"] == 0):
                raise GenError(f"variant {v['id']}: psram {v['psram']!r} but {v['psram_mb']} MB")
        else:
            raise GenError(f"variant {v['id']}: no table parser for {sid}")
        if got != want:
            raise GenError(f"variant {v['id']}: {sid} says {got}, expected {want}")
        if named not in v["evidence"]:
            raise GenError(f"variant {v['id']}: evidence does not name {named}")
        variants.append({k: x for k, x in v.items() if not k.startswith("_")})
        if sid not in used:
            used.append(sid)

    for rule in rules:  # a condition that no variant can meet would silently never apply
        want = rule["when"].get("psram")
        if want is not None and want not in {v["psram"] for v in variants}:
            raise GenError(f"{rule['id']}: when.psram {want!r} matches no {title} variant")
        wanted = rule["when"].get("variant")
        if wanted is not None and not set([wanted] if isinstance(wanted, str) else wanted) <= ids:
            raise GenError(f"{rule['id']}: when.variant {wanted!r} names an unknown {title} variant")

    capabilities = {
        "gpio": {"source_id": used[0]},
        "output": {"source_id": used[1]},
        "adc": {"source_id": used[2]},
        "functions": {"source_id": used[3]},
        "touch": {"supported": has_touch, "source_id": touch_sid if has_touch else used[1]},
    }
    return {
        "schema": 1,
        "chip": chip,
        "title": title,
        "generated_from": {"repo": IDF_REPO, "tag": IDF_TAG, "tag_object": IDF_TAG_OBJECT, "commit": IDF_COMMIT,
                           "generator": "scripts/gen_pins.py", "files": [_file_ref(corpus[s]) for s in used]},
        "gpio_count": len(gpios),
        "capabilities": capabilities,
        "gpios": gpios,
        "variants": variants,
        "rules": rules,
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def generate(corpus_dir: Path = DEFAULT_CORPUS) -> dict[str, str]:
    """chip -> JSON text."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    corpus = load_corpus(corpus_dir)
    return {chip: render(build(chip, corpus)) for chip in CHIPS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate circuit_bench/data/pins/<chip>.json from the pinned corpus.")
    ap.add_argument("--check", action="store_true", help="compare with the checked-in files, write nothing")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = ap.parse_args(argv)
    try:
        out = generate(args.corpus)
    except GenError as e:
        print(f"gen_pins: {e}", file=sys.stderr)
        return 2
    if args.check:
        bad = 0
        for chip, text in out.items():
            path = OUT_DIR / f"{chip}.json"
            same = path.is_file() and path.read_bytes() == text.encode("utf-8")
            print(f"{'ok  ' if same else 'DIFF'}  {path.relative_to(ROOT)}")
            bad += not same
        extra = sorted(p.name for p in OUT_DIR.glob("*.json") if p.stem not in out)
        for name in extra:
            print(f"EXTRA {name}")
        return 1 if bad or extra else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for chip, text in out.items():
        (OUT_DIR / f"{chip}.json").write_text(text, encoding="utf-8")
        print(f"wrote {(OUT_DIR / f'{chip}.json').relative_to(ROOT)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

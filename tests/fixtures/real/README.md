# Real captures (anonymised)

Serial output of a real ESP32-S3-DevKitC-1 (N16R8, chip revision v0.2) on its USB-Serial/JTAG port, recorded in the
hardware tests HW-1/HW-2 on 2026-11-06 with the example firmware `circuit_bench/data/examples/laser-trigger`.
Nothing to anonymise was in these lines (no MAC, no paths); the MAC of the board stays out of the repository.

- `esp32s3-panic.log`: one panic block as the serial broker stored it (StoreProhibited in `write_sensor_buffer`,
  firmware with `DEMO_CRASH 1`, ELF SHA256 prefix `cb8f614b016a44c5`)
- `esp32s3-reboot-loop.log`: two boots of the crash loop: the first after RESET was tapped (`rst:0x15`), the second
  the panic's own reboot (`rst:0xc (RTC_SW_CPU_RST)`), each with the panic
- `esp32s3-after-flash.log`: the boot after flashing the fixed firmware: `rst:0x15 (USB_UART_CHIP_RESET)`, `boot ok`

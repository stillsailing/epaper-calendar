# Project context

- Hardware is ESP32-L + DESPI-C73 + GDEP073E01, using classic ESP32 / WEMOS LOLIN32. Do not apply ESP32E6-E01 or ESP32-S3 assumptions.
- The intended product is an offline calendar. Generate images locally on the Mac; do not introduce a deployed backend without a change in requirements.
- Main sketch: `firmware/epaper_calendar/epaper_calendar.ino`. Preserve the Arduino folder/file naming relationship.
- Build with `scripts/compile.sh`. FQBN is `esp32:esp32:lolin32`; the initialization baseline uses ESP32 core 3.3.11.
- The build script must remain build-only. Programming connected hardware is a separate action, performed when requested as part of the task.
- Vendor driver files and the image header match the preserved ZIP. Keep changes narrow and document any driver changes against the source and hardware documentation.
- The baseline draws once per boot and calls the vendor power-off routine. Keep refresh frequency and display power management explicit.
- Build success is not hardware validation. Vendor BUSY waits currently have no timeout; do not claim runtime recovery or thermal protection exists.
- Do not assume the ESP32-L board has the SD slot or RTC of another development board. Confirm storage and clock hardware before implementing those paths.

# Project context

- Hardware is ESP32-L + DESPI-C73 + GDEP073E01, using classic ESP32 / WEMOS LOLIN32. Do not apply ESP32E6-E01 or ESP32-S3 assumptions.
- The intended product is a battery-powered offline calendar. Generate pages locally on the Mac (`scripts/generate_pages.py`, `scripts/pack_calendar.py`); do not introduce a deployed backend or Wi-Fi without a change in requirements.
- Main sketch: `firmware/epaper_calendar/epaper_calendar.ino`. Preserve the Arduino folder/file naming relationship, and keep `partitions.csv` in the sketch folder; the core picks it up automatically.
- Build with `scripts/compile.sh`. FQBN is `esp32:esp32:lolin32`; the initialization baseline uses ESP32 core 3.3.11.
- The build script must remain build-only. Uploading firmware, `scripts/flash_data.sh` and `scripts/set_rtc.py` program connected hardware; run them only when requested as part of the task.
- Vendor driver files and `image.h` match the preserved ZIP. `image.h` is kept but no longer included by the sketch. Keep changes narrow and document any driver changes against the source and hardware documentation.
- The firmware refreshes at most once per date (plus once after power-on or reset), always ends with the vendor power-off routine, then (DS3231 mode) puts the ESP32 into deep sleep until shortly after the next local midnight. Keep refresh frequency and display power management explicit. The panel deep-sleep command (0x07) remains disabled as in the vendor code.
- Pages live in the `calendar` flash partition (4 MB flash layout; `app0` size matches lolin32's `upload.maximum_size`). The blob format is defined jointly by `scripts/pack_calendar.py` and `calendar_store.cpp`; change both together and bump the format version.
- The clock is an external DS3231 on I2C, chosen by the user but not yet purchased. Without it the firmware falls back to an internal-clock mode: it stays awake (no deep sleep), counts time with `esp_timer`, accepts `SET` over serial at any time, and requires continuous USB power; any reset loses the time. GPIO21/22 and the 4 MB flash size are assumptions not yet confirmed on the ESP32-L. The board has no SD slot in this design; do not assume other storage or clock hardware.
- Build success is not hardware validation; nothing has run on the device yet. Vendor BUSY waits have no timeout; a 120 s task watchdog resets the chip and the next boot skips the panel until the next day. That limits battery drain only; do not claim runtime recovery or thermal protection exists.
- Tests: `python3 -m unittest discover -s scripts`.

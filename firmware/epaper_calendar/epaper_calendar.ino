#include <Arduino.h>
#include <SPI.h>
#include <esp_partition.h>
#include <esp_sleep.h>
#include <esp_task_wdt.h>
#include <esp_timer.h>

#include "Display_EPD_W21.h"
#include "Display_EPD_W21_spi.h"
#include "calendar_store.h"
#include "rtc_ds3231.h"

// ESP32-L + DESPI-C73 + GDEP073E01. Select WEMOS LOLIN32 in Arduino IDE.
// Pages come from the "calendar" flash partition (see partitions.csv and
// scripts/pack_calendar.py); the vendor image.h is kept but not compiled in.
#if !defined(CONFIG_IDF_TARGET_ESP32)
#error "This sketch targets the classic ESP32. Select WEMOS LOLIN32, not ESP32-S3."
#endif

// Keep the vendor driver's A14-A17 aliases tied to the verified GPIOs.
static_assert(A14 == 13 && A15 == 12 && A16 == 14 && A17 == 27,
              "Unexpected board pin mapping. Select WEMOS LOLIN32.");

constexpr uint8_t kBusyPin = A14;   // GPIO13
constexpr uint8_t kResetPin = A15;  // GPIO12
constexpr uint8_t kDcPin = A16;     // GPIO14
constexpr uint8_t kCsPin = A17;     // GPIO27
constexpr uint8_t kSckPin = 18;
constexpr uint8_t kMosiPin = 23;

// DS3231 on I2C. LOLIN32 defaults; not yet confirmed as free on the ESP32-L
// header. Change both here if the module is wired elsewhere.
constexpr uint8_t kRtcSdaPin = 21;
constexpr uint8_t kRtcSclPin = 22;

// Two clock modes, chosen at boot by whether the DS3231 answers:
//  - DS3231: refresh, then deep sleep until shortly after local midnight. The
//    ESP32 sleep timer runs from an internal RC oscillator that can drift by a
//    few percent, so long sleeps are cut short and the remainder is re-measured
//    against the DS3231. Suitable for battery power.
//  - Internal (no DS3231): stay awake and count time on the 40 MHz crystal via
//    esp_timer; serial stays open for "SET" at any time. Requires continuous
//    USB power; any reset or power loss forgets the time.
constexpr uint32_t kRefreshOffsetSeconds = 30;
constexpr uint32_t kShortSleepSeconds = 600;
constexpr uint32_t kRetrySeconds = 6 * 3600;  // Clock missing or unset.

// A refresh normally finishes well inside this; if a vendor BUSY wait hangs,
// the task watchdog resets the chip and the next boot skips the panel.
constexpr uint32_t kWatchdogMs = 120000;
constexpr uint32_t kTimeSetWindowMs = 5000;

// Survives deep sleep (not power loss): the page last sent to the panel.
constexpr uint32_t kNothingShown = UINT32_MAX;
constexpr uint32_t kShownFallback = 1;  // Not a valid YYYYMMDD.
RTC_DATA_ATTR uint32_t gShownKey = kNothingShown;

const esp_partition_t *gPartition = nullptr;

bool readPartition(uint32_t offset, void *dst, size_t len) {
  return esp_partition_read(gPartition, offset, dst, len) == ESP_OK;
}

void sendToPanel(const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; i++) EPD_W21_WriteDATA(data[i]);
}

// Finds the page for `date` (falling back to the fallback page), verifies it,
// then performs one full refresh and powers off the display driver.
bool showPage(uint32_t date) {
  gPartition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                        static_cast<esp_partition_subtype_t>(0x40), "calendar");
  if (!gPartition) {
    Serial.println("[calendar] No calendar partition; flash partitions.csv with the firmware");
    return false;
  }
  PageRef page;
  const char *error = storeFind(readPartition, gPartition->size, date, page);
  if (error && date != kFallbackDate) {
    Serial.printf("[calendar] Page %lu: %s; trying fallback page\n", (unsigned long)date, error);
    error = storeFind(readPartition, gPartition->size, kFallbackDate, page);
  }
  if (!error) error = storeDecode(readPartition, page, nullptr);  // Verify before touching the panel.
  if (error) {
    Serial.printf("[calendar] Nothing to show: %s\n", error);
    return false;
  }

  pinMode(kBusyPin, INPUT);
  pinMode(kResetPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kCsPin, OUTPUT);
  digitalWrite(kResetPin, HIGH);
  digitalWrite(kDcPin, HIGH);
  digitalWrite(kCsPin, HIGH);
  // Start the bus before opening a transaction. This display only needs MOSI.
  if (!SPI.begin(kSckPin, -1, kMosiPin, kCsPin)) {
    Serial.println("[calendar] SPI could not start; display update skipped");
    return false;
  }
  SPI.beginTransaction(SPISettings(10000000, MSBFIRST, SPI_MODE0));

  // Same sequence as the vendor PIC_display(), fed from flash instead of image.h.
  Serial.printf("[calendar] Showing page %lu (%lu bytes compressed)\n",
                (unsigned long)page.date, (unsigned long)page.length);
  EPD_init();
  EPD_W21_WriteCMD(0x10);
  error = storeDecode(readPartition, page, sendToPanel);
  if (error) {
    Serial.printf("[calendar] Page changed while drawing (%s); refresh skipped\n", error);
  } else {
    Serial.println("[calendar] Waiting for refresh");
    EPD_W21_WriteCMD(0x12);  // Display refresh.
    EPD_W21_WriteDATA(0x00);
    delay(1);  // Vendor: at least 200 us before polling BUSY.
    lcd_chkstatus();
  }
  Serial.println("[calendar] Powering off display driver");
  EPD_sleep();
  SPI.endTransaction();
  return !error;
}

enum class ClockSource { Ds3231, Internal };
ClockSource gClock = ClockSource::Ds3231;

// Internal clock: local time = base + crystal-timed microseconds since base.
bool gInternalSet = false;
int64_t gInternalBaseSeconds = 0;
int64_t gInternalBaseMicros = 0;
int64_t gLastSetSeconds = -1;  // Previous SET this power cycle, for drift rate.

bool readClock(LocalTime &now) {
  if (gClock == ClockSource::Ds3231) return rtcRead(now) == RtcStatus::Ok;
  if (!gInternalSet) return false;
  now = fromEpochSeconds(gInternalBaseSeconds +
                         (esp_timer_get_time() - gInternalBaseMicros) / 1000000);
  return true;
}

// Sets the active clock and reports how far it had drifted since the last SET.
void setClock(const LocalTime &time) {
  const int64_t target = toEpochSeconds(time);
  LocalTime before;
  const bool hadTime = readClock(before);
  if (gClock == ClockSource::Ds3231) {
    if (!rtcWrite(time)) {
      Serial.println("[calendar] Clock write failed");
      return;
    }
  } else {
    gInternalBaseSeconds = target;
    gInternalBaseMicros = esp_timer_get_time();
    gInternalSet = true;
  }
  Serial.printf("[calendar] Clock set to %04u-%02u-%02u %02u:%02u:%02u (%s)\n", time.year,
                time.month, time.day, time.hour, time.minute, time.second,
                gClock == ClockSource::Ds3231 ? "DS3231" : "internal");
  if (hadTime) {
    const long error = static_cast<long>(toEpochSeconds(before) - target);
    Serial.printf("[calendar] Clock was %+ld s off", error);
    if (gLastSetSeconds >= 0 && target - gLastSetSeconds >= 3600) {
      const double hours = (target - gLastSetSeconds) / 3600.0;
      Serial.printf(" after %.1f h (%+.1f s/day)", hours, error * 24 / hours);
    }
    Serial.println();
  }
  gLastSetSeconds = target;
}

void handleCommand(String line) {
  line.trim();
  if (!line.startsWith("SET ")) return;
  LocalTime time;
  if (parseLocalTime(line.c_str() + 4, time)) {
    setClock(time);
  } else {
    Serial.println("[calendar] Invalid time; expected SET YYYY-MM-DD HH:MM:SS");
  }
}

// On a cold start, wait briefly for "SET YYYY-MM-DD HH:MM:SS" from scripts/set_rtc.py.
void offerTimeSet() {
  Serial.printf("[calendar] Send 'SET YYYY-MM-DD HH:MM:SS' within %lu s to set the clock\n",
                (unsigned long)(kTimeSetWindowMs / 1000));
  Serial.setTimeout(kTimeSetWindowMs);
  handleCommand(Serial.readStringUntil('\n'));
}

// Internal mode: commands may arrive at any time.
void pollSerial() {
  static String line;
  while (Serial.available()) {
    const char c = Serial.read();
    if (c == '\n') {
      handleCommand(line);
      line = "";
    } else if (line.length() < 64) {
      line += c;
    }
  }
}

// Shows today's page, or the fallback page when the clock is unset, unless it
// is already on the panel.
void updateDisplay(bool clockOk, const LocalTime &now) {
  const uint32_t wanted = clockOk ? dateKey(now) : kShownFallback;
  if (wanted == gShownKey) return;
  showPage(clockOk ? wanted : kFallbackDate);
  gShownKey = wanted;  // Recorded even on failure so a bad page is not retried.
}

void logClock(bool clockOk, const LocalTime &now) {
  if (clockOk) {
    Serial.printf("[calendar] Now %04u-%02u-%02u %02u:%02u:%02u\n", now.year, now.month, now.day,
                  now.hour, now.minute, now.second);
  } else if (gClock == ClockSource::Internal) {
    Serial.println("[calendar] Internal clock not set; run scripts/set_rtc.py");
  } else {
    Serial.println("[calendar] RTC time lost; run scripts/set_rtc.py");
  }
}

// Does not return: deep sleep ends in a reset.
void sleepFor(uint32_t seconds) {
  Serial.printf("[calendar] Deep sleep for %lu s\n", (unsigned long)seconds);
  Serial.flush();
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(seconds) * 1000000ULL);
  esp_deep_sleep_start();
}

void setup() {
  Serial.begin(115200);
  const esp_reset_reason_t reason = esp_reset_reason();
  const bool coldStart = reason != ESP_RST_DEEPSLEEP;
  if (coldStart) delay(1000);  // Give a USB serial monitor time to attach.
  Serial.println();
  Serial.printf("[calendar] Boot, reset reason %d\n", static_cast<int>(reason));

  esp_task_wdt_config_t wdt = {
      .timeout_ms = kWatchdogMs, .idle_core_mask = 1 << 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wdt);
  esp_task_wdt_add(nullptr);

  // After a watchdog/panic/brownout reset, leave the panel alone until the
  // next scheduled day instead of retrying a refresh that just failed.
  const bool faulted = reason == ESP_RST_TASK_WDT || reason == ESP_RST_INT_WDT ||
                       reason == ESP_RST_WDT || reason == ESP_RST_PANIC ||
                       reason == ESP_RST_BROWNOUT;

  rtcBegin(kRtcSdaPin, kRtcSclPin);
  LocalTime now;
  if (rtcRead(now) == RtcStatus::NotFound) {
    gClock = ClockSource::Internal;
    Serial.println("[calendar] DS3231 not found; using the internal clock. "
                   "Keep USB power connected: no deep sleep in this mode");
  }
  if (coldStart && !faulted) offerTimeSet();

  bool clockOk = readClock(now);
  logClock(clockOk, now);
  if (faulted) {
    Serial.println("[calendar] Previous run faulted; display update skipped");
    gShownKey = clockOk ? dateKey(now) : kShownFallback;
  } else {
    if (gShownKey == (clockOk ? dateKey(now) : kShownFallback)) {
      Serial.println("[calendar] Page already current");
    }
    updateDisplay(clockOk, now);
  }

  if (gClock == ClockSource::Internal) return;  // loop() takes over.

  if (!clockOk) sleepFor(kRetrySeconds);
  // Re-read so time spent refreshing is accounted for.
  if (!readClock(now)) sleepFor(kRetrySeconds);
  const uint32_t remaining = secondsUntilNextDay(now, kRefreshOffsetSeconds);
  sleepFor(remaining > kShortSleepSeconds ? remaining / 10 * 9 : remaining);
}

// Only reached in internal-clock mode; DS3231 mode always ends setup() in deep sleep.
void loop() {
  esp_task_wdt_reset();
  pollSerial();
  LocalTime now;
  const bool clockOk = readClock(now);
  const uint32_t wanted = clockOk ? dateKey(now) : kShownFallback;
  if (wanted != gShownKey) {
    logClock(clockOk, now);
    updateDisplay(clockOk, now);
  }
  delay(200);
}

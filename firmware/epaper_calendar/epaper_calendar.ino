#include <Arduino.h>
#include <SPI.h>
#include <driver/rtc_io.h>
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

// Buttons, active low: a key connects its pin to GND (internal pull-ups are on;
// a module's own pull-ups also work). Power a button module from 3.3 V, never
// 5 V. All pins have internal pull-ups and none is a strapping pin. Only the
// wake key can wake the chip from deep sleep (ext0, so it must be an RTC GPIO);
// the others work while it is awake.
constexpr uint8_t kWakePin = 32;
constexpr uint8_t kPrevMonthPin = 33;
constexpr uint8_t kPrevDayPin = 25;
constexpr uint8_t kTodayPin = 26;
constexpr uint8_t kNextDayPin = 4;
constexpr uint8_t kNextMonthPin = 16;
constexpr uint8_t kMonthViewPin = 17;
// Declared up here, before the prototypes the Arduino preprocessor inserts.
enum class Action : uint8_t { Wake, PrevMonth, PrevDay, Today, NextDay, NextMonth, MonthView };
constexpr uint32_t kDebounceMs = 30;
constexpr uint32_t kSettleMs = 1500;        // Wait for further presses before drawing.
constexpr int64_t kBrowseSeconds = 120;     // Then return to today.
constexpr uint32_t kSessionIdleMs = 30000;  // DS3231 mode: stay awake after the wake key.

// Month view: pages are drawn on the Mac; the firmware turns today's cell into
// a red rounded block with white text while streaming the page out. The grid area mirrors MONTH_GRID_*
// in scripts/generate_pages.py (scripts/test_pack_calendar.py checks them).
constexpr int kPanelWidth = 800;
constexpr int kMonthGridLeft = 40;
constexpr int kMonthGridRight = 760;
constexpr int kMonthGridTop = 116;
constexpr int kMonthGridBottom = 436;
constexpr int kTodayRadius = 6;  // Corner radius of today's block, pixels.
// Panel codes, as in the vendor Color_get().
constexpr uint8_t kWhiteNibble = 0x1;
constexpr uint8_t kYellowNibble = 0x2;
constexpr uint8_t kRedNibble = 0x3;

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
// Browsing with the buttons: days from today, whether the month view (page
// key YYYYMM00) is shown, and when to return to today (local epoch seconds).
RTC_DATA_ATTR int32_t gViewOffset = 0;
RTC_DATA_ATTR bool gMonthView = false;
RTC_DATA_ATTR int64_t gBrowseUntil = 0;

const esp_partition_t *gPartition = nullptr;

bool readPartition(uint32_t offset, void *dst, size_t len) {
  return esp_partition_read(gPartition, offset, dst, len) == ESP_OK;
}

bool findPartition() {
  if (!gPartition) {
    gPartition = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, static_cast<esp_partition_subtype_t>(0x40), "calendar");
  }
  return gPartition != nullptr;
}

bool pageExists(uint32_t date) {
  PageRef page;
  return findPartition() && !storeFind(readPartition, gPartition->size, date, page);
}

// Today's cell on the month view; recolored while the page streams out.
struct Frame {
  bool on;
  int x0, y0, x1, y1;  // Inclusive; covers the generator's yellow festival box.
};
Frame gFrame = {false, 0, 0, 0, 0};
uint32_t gSent = 0;  // Bytes of the current page sent so far.

// Inside the rounded block: background (white or festival yellow) turns red and
// text turns white. In the cut-off corners, festival yellow turns white.
uint8_t framed(int x, int y, uint8_t nibble) {
  if (x < gFrame.x0 || x > gFrame.x1 || y < gFrame.y0 || y > gFrame.y1) return nibble;
  const int cx = x < gFrame.x0 + kTodayRadius ? gFrame.x0 + kTodayRadius
               : x > gFrame.x1 - kTodayRadius ? gFrame.x1 - kTodayRadius : x;
  const int cy = y < gFrame.y0 + kTodayRadius ? gFrame.y0 + kTodayRadius
               : y > gFrame.y1 - kTodayRadius ? gFrame.y1 - kTodayRadius : y;
  const bool background = nibble == kWhiteNibble || nibble == kYellowNibble;
  if ((x - cx) * (x - cx) + (y - cy) * (y - cy) > kTodayRadius * kTodayRadius) {
    return nibble == kYellowNibble ? kWhiteNibble : nibble;
  }
  return background ? kRedNibble : kWhiteNibble;
}

void sendToPanel(const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; i++, gSent++) {
    uint8_t b = data[i];
    if (gFrame.on) {  // Two pixels per byte, left one in the high nibble.
      const int y = gSent / (kPanelWidth / 2), x = gSent % (kPanelWidth / 2) * 2;
      b = framed(x, y, b >> 4) << 4 | framed(x + 1, y, b & 0x0F);
    }
    EPD_W21_WriteDATA(b);
  }
}

bool panelBegin() {
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
  return true;
}

// Refreshes from the data already sent, then powers off the display driver.
void panelRefreshAndOff(bool refresh) {
  if (refresh) {
    Serial.println("[calendar] Waiting for refresh");
    EPD_W21_WriteCMD(0x12);  // Display refresh.
    EPD_W21_WriteDATA(0x00);
    delay(1);  // Vendor: at least 200 us before polling BUSY.
    lcd_chkstatus();
  }
  Serial.println("[calendar] Powering off display driver");
  EPD_sleep();
  SPI.endTransaction();
}

// Finds the page for `date` (falling back to the fallback page), verifies it,
// then performs one full refresh and powers off the display driver.
bool showPage(uint32_t date) {
  if (!findPartition()) {
    Serial.println("[calendar] No calendar partition; flash partitions.csv with the firmware");
    return false;
  }
  PageRef page;
  const char *error = storeFind(readPartition, gPartition->size, date, page);
  if (error && date != kFallbackDate) {
    Serial.printf("[calendar] Page %lu: %s; trying fallback page\n", (unsigned long)date, error);
    error = storeFind(readPartition, gPartition->size, kFallbackDate, page);
    gFrame.on = false;
  }
  if (!error) error = storeDecode(readPartition, page, nullptr);  // Verify before touching the panel.
  if (error) {
    Serial.printf("[calendar] Nothing to show: %s\n", error);
    return false;
  }

  if (!panelBegin()) return false;

  // Same sequence as the vendor PIC_display(), fed from flash instead of image.h.
  Serial.printf("[calendar] Showing page %lu (%lu bytes compressed)%s\n",
                (unsigned long)page.date, (unsigned long)page.length,
                gFrame.on ? ", today marked" : "");
  EPD_init();
  EPD_W21_WriteCMD(0x10);
  gSent = 0;
  error = storeDecode(readPartition, page, sendToPanel);
  if (error) Serial.printf("[calendar] Page changed while drawing (%s); refresh skipped\n", error);
  panelRefreshAndOff(!error);
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

uint32_t daysFrom(const LocalTime &now, int32_t days) {
  return dateKey(fromEpochSeconds(toEpochSeconds(now) + days * 86400LL));
}

uint32_t monthKey(uint32_t date) { return date / 100 * 100; }

bool browsing() { return gViewOffset != 0 || gMonthView; }

// The page that belongs on the panel: today's (or the day or month being
// browsed), or the fallback page when the clock is unset.
uint32_t wantedKey(bool clockOk, const LocalTime &now) {
  if (!clockOk) return kShownFallback;
  if (browsing() && toEpochSeconds(now) >= gBrowseUntil) {
    Serial.println("[calendar] Browsing timed out; back to today");
    gViewOffset = 0;
    gMonthView = false;
  }
  const uint32_t date = daysFrom(now, gViewOffset);
  return gMonthView ? monthKey(date) : date;
}

// Marks today's cell when `key` is the month view of the current month, using
// the same grid as render_month() in scripts/generate_pages.py.
void markToday(uint32_t key, const LocalTime &now) {
  gFrame.on = false;
  if (key % 100 != 0 || key != monthKey(dateKey(now))) return;
  const LocalTime first = {now.year, now.month, 1, 0, 0, 0};
  const int64_t firstDay = toEpochSeconds(first) / 86400;
  const int days = static_cast<int>(toEpochSeconds(addMonths(first, 1)) / 86400 - firstDay);
  const int firstCol = static_cast<int>((firstDay + 3) % 7);  // 1970-01-01 was a Thursday.
  const int index = firstCol + now.day - 1;
  const int rows = (firstCol + days + 6) / 7;
  const float cellW = (kMonthGridRight - kMonthGridLeft) / 7.0f;
  const float rowH = static_cast<float>(kMonthGridBottom - kMonthGridTop) / rows;
  const int col = index % 7, row = index / 7;
  gFrame = {true, static_cast<int>(kMonthGridLeft + col * cellW) + 3,
            static_cast<int>(kMonthGridTop + row * rowH) + 2,
            static_cast<int>(kMonthGridLeft + (col + 1) * cellW) - 3,
            static_cast<int>(kMonthGridTop + (row + 1) * rowH) - 2};
}

// Shows the wanted page unless it is already on the panel (or `force`).
void updateDisplay(bool clockOk, const LocalTime &now, bool force = false) {
  const uint32_t wanted = wantedKey(clockOk, now);
  if (wanted == gShownKey && !force) return;
  if (clockOk) markToday(wanted, now);
  else gFrame.on = false;
  showPage(clockOk ? wanted : kFallbackDate);
  gShownKey = wanted;  // Recorded even on failure so a bad page is not retried.
}

// A member function, so the Arduino preprocessor does not hoist a prototype
// above the struct.
struct Button {
  uint8_t pin;
  Action action;
  bool down;  // Debounced state.
  bool raw;
  uint32_t changedAt;

  // True once per debounced press.
  bool pressed() {
    const bool now = digitalRead(pin) == LOW;
    if (now != raw) {
      raw = now;
      changedAt = millis();
      return false;
    }
    if (now == down || millis() - changedAt < kDebounceMs) return false;
    down = now;
    return now;
  }
};
// Left to right on the enclosure, seen from the front.
Button gButtons[] = {
    {kWakePin, Action::Wake},       {kPrevMonthPin, Action::PrevMonth},
    {kPrevDayPin, Action::PrevDay}, {kTodayPin, Action::Today},
    {kNextDayPin, Action::NextDay}, {kNextMonthPin, Action::NextMonth},
    {kMonthViewPin, Action::MonthView}};

bool gForceRefresh = false;
uint32_t gQuietUntil = 0;  // millis(); drawing waits while presses keep coming.

void beginButtons() {
  rtc_gpio_deinit(static_cast<gpio_num_t>(kWakePin));  // Back from deep-sleep wake config.
  for (Button &b : gButtons) {
    pinMode(b.pin, INPUT_PULLUP);
    b.down = b.raw = digitalRead(b.pin) == LOW;  // A key already held is not a new press.
    b.changedAt = millis();
  }
}

// Days from today to the same day `months` away from the viewed date, with the
// day clamped to the month's length (31 March - 1 month = 28/29 February).
int32_t monthStep(const LocalTime &now, int months) {
  const int64_t today = toEpochSeconds(now);
  const LocalTime target = addMonths(fromEpochSeconds(today + gViewOffset * 86400LL), months);
  return static_cast<int32_t>((toEpochSeconds(target) - today) / 86400);
}

void onButton(Action action, bool clockOk, const LocalTime &now) {
  switch (action) {
    case Action::Wake:
      Serial.println("[calendar] Wake key: buttons active");
      return;
    case Action::Today:
      Serial.println("[calendar] Today key: redrawing today");
      gViewOffset = 0;
      gMonthView = false;
      gForceRefresh = true;
      return;
    default:
      break;
  }
  if (!clockOk) {
    Serial.println("[calendar] Clock not set; browsing disabled");
    return;
  }
  // Month keys keep the current view; day keys leave the month view; the month
  // view key toggles it.
  int32_t offset = gViewOffset;
  bool monthView = gMonthView;
  if (action == Action::PrevDay || action == Action::NextDay) {
    offset += monthView ? 0 : (action == Action::PrevDay ? -1 : 1);
    monthView = false;
  }
  if (action == Action::PrevMonth) offset = monthStep(now, -1);
  if (action == Action::NextMonth) offset = monthStep(now, 1);
  if (action == Action::MonthView) monthView = !monthView;
  const uint32_t date = daysFrom(now, offset);
  const uint32_t key = monthView ? monthKey(date) : date;
  if (!pageExists(key)) {
    Serial.printf("[calendar] No page for %lu\n", (unsigned long)key);
    return;
  }
  gViewOffset = offset;
  gMonthView = monthView;
  gBrowseUntil = toEpochSeconds(now) + kBrowseSeconds;
  gQuietUntil = millis() + kSettleMs;
  Serial.printf("[calendar] Viewing %lu (%+ld days)\n", (unsigned long)key, (long)offset);
}

// One pass of the awake loop: serial, buttons, and any refresh that is due.
// Returns true if a button was pressed or the panel was redrawn.
bool service() {
  esp_task_wdt_reset();
  pollSerial();
  LocalTime now;
  const bool clockOk = readClock(now);
  bool active = false;
  for (Button &b : gButtons) {
    if (b.pressed()) {
      onButton(b.action, clockOk, now);
      active = true;
    }
  }
  if (static_cast<int32_t>(millis() - gQuietUntil) < 0) return active;
  if (gForceRefresh || wantedKey(clockOk, now) != gShownKey) {
    logClock(clockOk, now);
    updateDisplay(clockOk, now, gForceRefresh);
    gForceRefresh = false;
    active = true;
  }
  return active;
}

// Lets the wake key wake the chip. A key held down (or stuck) would wake it
// again immediately, so it is left out until the next sleep.
void enableButtonWake() {
  const gpio_num_t pin = static_cast<gpio_num_t>(kWakePin);
  if (digitalRead(kWakePin) == LOW) {
    Serial.println("[calendar] Wake key held; not a wake source this time");
    return;
  }
  esp_sleep_enable_ext0_wakeup(pin, 0);
  rtc_gpio_pullup_en(pin);
  rtc_gpio_pulldown_dis(pin);
  esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_ON);  // Keeps the pull-up on.
}

// Does not return: deep sleep ends in a reset.
void sleepFor(uint32_t seconds) {
  Serial.printf("[calendar] Deep sleep for %lu s\n", (unsigned long)seconds);
  Serial.flush();
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(seconds) * 1000000ULL);
  enableButtonWake();
  esp_deep_sleep_start();
}

// Until shortly after midnight (cut short against RC drift), or until browsing
// times out.
uint32_t sleepSeconds(const LocalTime &now) {
  const uint32_t remaining = secondsUntilNextDay(now, kRefreshOffsetSeconds);
  uint32_t seconds = remaining > kShortSleepSeconds ? remaining / 10 * 9 : remaining;
  if (browsing()) {
    const int64_t browse = gBrowseUntil - toEpochSeconds(now);
    seconds = browse < 1 ? 1 : (browse < seconds ? static_cast<uint32_t>(browse) : seconds);
  }
  return seconds;
}

void setup() {
  Serial.begin(115200);
  const esp_reset_reason_t reason = esp_reset_reason();
  const bool coldStart = reason != ESP_RST_DEEPSLEEP;
  const esp_sleep_wakeup_cause_t wake = esp_sleep_get_wakeup_cause();
  const bool buttonWake = wake == ESP_SLEEP_WAKEUP_EXT0;
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

  beginButtons();
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
    gShownKey = wantedKey(clockOk, now);
  } else {
    if (gShownKey == wantedKey(clockOk, now)) Serial.println("[calendar] Page already current");
    updateDisplay(clockOk, now);
  }
  if (buttonWake) onButton(Action::Wake, clockOk, now);

  if (gClock == ClockSource::Internal) return;  // loop() takes over.

  // Stay awake while the buttons are in use after the wake key or power-on.
  if (!faulted && (coldStart || buttonWake)) {
    uint32_t lastActive = millis();
    while (millis() - lastActive < kSessionIdleMs) {
      if (service()) lastActive = millis();
      delay(20);
    }
  }
  // Re-read so time spent refreshing is accounted for.
  if (!readClock(now)) sleepFor(kRetrySeconds);
  sleepFor(sleepSeconds(now));
}

// Only reached in internal-clock mode; DS3231 mode always ends setup() in deep sleep.
void loop() {
  service();
  delay(20);
}

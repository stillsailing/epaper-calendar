#ifndef RTC_DS3231_H
#define RTC_DS3231_H

#include <stdint.h>

// Minimal DS3231 access over Wire, plus local-time arithmetic shared with the
// internal-clock fallback. Times are local (no time zone or DST handling);
// scripts/set_rtc.py sends the Mac's local time.

struct LocalTime {
  uint16_t year;  // 2000..2099
  uint8_t month, day, hour, minute, second;
};

enum class RtcStatus { Ok, NotFound, TimeLost };

void rtcBegin(int sdaPin, int sclPin);
// TimeLost: the oscillator stopped (first power-up or dead coin cell) since the
// time was last set, so `now` is not trustworthy.
RtcStatus rtcRead(LocalTime &now);
bool rtcWrite(const LocalTime &time);  // Also clears the oscillator-stop flag.

bool parseLocalTime(const char *text, LocalTime &time);  // "YYYY-MM-DD HH:MM:SS"
uint32_t dateKey(const LocalTime &time);                  // YYYYMMDD
uint32_t secondsUntilNextDay(const LocalTime &time, uint32_t offsetSeconds);
int64_t toEpochSeconds(const LocalTime &time);  // Seconds since 1970-01-01 00:00 local.
LocalTime fromEpochSeconds(int64_t seconds);
// Same day and time `months` later (or earlier), the day clamped to the month's length.
LocalTime addMonths(const LocalTime &time, int months);

#endif

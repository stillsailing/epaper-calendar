#include "rtc_ds3231.h"

#include <Arduino.h>
#include <Wire.h>

namespace {

constexpr uint8_t kAddress = 0x68;
constexpr uint8_t kRegSeconds = 0x00;
constexpr uint8_t kRegStatus = 0x0F;
constexpr uint8_t kStatusOsf = 0x80;  // Oscillator stop flag.

uint8_t fromBcd(uint8_t v) { return (v >> 4) * 10 + (v & 0x0F); }
uint8_t toBcd(uint8_t v) { return ((v / 10) << 4) | (v % 10); }

bool readRegisters(uint8_t reg, uint8_t *dst, uint8_t len) {
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(kAddress, len) != len) return false;
  for (uint8_t i = 0; i < len; i++) dst[i] = Wire.read();
  return true;
}

bool writeRegisters(uint8_t reg, const uint8_t *src, uint8_t len) {
  Wire.beginTransmission(kAddress);
  Wire.write(reg);
  Wire.write(src, len);
  return Wire.endTransmission() == 0;
}

bool isLeap(int year) { return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0; }

uint8_t daysInMonth(int year, int month) {
  static const uint8_t kDays[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  return month == 2 && isLeap(year) ? 29 : kDays[month - 1];
}

bool isValid(const LocalTime &t) {
  return t.year >= 2000 && t.year <= 2099 && t.month >= 1 && t.month <= 12 && t.day >= 1 &&
         t.day <= daysInMonth(t.year, t.month) && t.hour < 24 && t.minute < 60 && t.second < 60;
}

// Days since 1970-01-01 (H. Hinnant's days_from_civil).
int32_t daysFromCivil(int y, unsigned m, unsigned d) {
  y -= m <= 2;
  const int era = y / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int32_t>(doe) - 719468;
}

}  // namespace

void rtcBegin(int sdaPin, int sclPin) { Wire.begin(sdaPin, sclPin, 100000); }

RtcStatus rtcRead(LocalTime &now) {
  uint8_t r[7], status;
  if (!readRegisters(kRegSeconds, r, sizeof(r)) || !readRegisters(kRegStatus, &status, 1)) {
    return RtcStatus::NotFound;
  }
  uint8_t hour = r[2] & 0x40 ? fromBcd(r[2] & 0x1F) % 12 + (r[2] & 0x20 ? 12 : 0)  // 12 h mode
                             : fromBcd(r[2] & 0x3F);
  now = {static_cast<uint16_t>(2000 + fromBcd(r[6])), fromBcd(r[5] & 0x1F), fromBcd(r[4] & 0x3F),
         hour, fromBcd(r[1] & 0x7F), fromBcd(r[0] & 0x7F)};
  if ((status & kStatusOsf) || !isValid(now)) return RtcStatus::TimeLost;
  return RtcStatus::Ok;
}

bool rtcWrite(const LocalTime &t) {
  if (!isValid(t)) return false;
  // DS3231 weekday register is 1..7; 1970-01-01 was a Thursday.
  uint8_t weekday = (daysFromCivil(t.year, t.month, t.day) % 7 + 3) % 7 + 1;  // Monday = 1
  const uint8_t r[7] = {toBcd(t.second), toBcd(t.minute), toBcd(t.hour), weekday,
                        toBcd(t.day),    toBcd(t.month),  toBcd(t.year - 2000)};
  uint8_t status;
  if (!writeRegisters(kRegSeconds, r, sizeof(r)) || !readRegisters(kRegStatus, &status, 1)) {
    return false;
  }
  status &= ~kStatusOsf;
  return writeRegisters(kRegStatus, &status, 1);
}

bool parseLocalTime(const char *text, LocalTime &t) {
  unsigned y, mo, d, h, mi, s;
  char extra;
  if (sscanf(text, "%4u-%2u-%2u %2u:%2u:%2u%c", &y, &mo, &d, &h, &mi, &s, &extra) != 6) {
    return false;
  }
  t = {static_cast<uint16_t>(y), static_cast<uint8_t>(mo), static_cast<uint8_t>(d),
       static_cast<uint8_t>(h), static_cast<uint8_t>(mi), static_cast<uint8_t>(s)};
  return isValid(t);
}

uint32_t dateKey(const LocalTime &t) { return t.year * 10000UL + t.month * 100UL + t.day; }

uint32_t secondsUntilNextDay(const LocalTime &t, uint32_t offsetSeconds) {
  return 86400UL - (t.hour * 3600UL + t.minute * 60UL + t.second) + offsetSeconds;
}

int64_t toEpochSeconds(const LocalTime &t) {
  return static_cast<int64_t>(daysFromCivil(t.year, t.month, t.day)) * 86400 + t.hour * 3600L +
         t.minute * 60L + t.second;
}

// Inverse of toEpochSeconds (H. Hinnant's civil_from_days).
LocalTime fromEpochSeconds(int64_t seconds) {
  int64_t days = seconds / 86400, rem = seconds % 86400;
  if (rem < 0) rem += 86400, days--;
  const int64_t z = days + 719468;
  const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = static_cast<unsigned>(z - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  const unsigned day = doy - (153 * mp + 2) / 5 + 1;
  const unsigned month = mp < 10 ? mp + 3 : mp - 9;
  const int64_t year = yoe + era * 400 + (month <= 2);
  return {static_cast<uint16_t>(year), static_cast<uint8_t>(month), static_cast<uint8_t>(day),
          static_cast<uint8_t>(rem / 3600), static_cast<uint8_t>(rem / 60 % 60),
          static_cast<uint8_t>(rem % 60)};
}

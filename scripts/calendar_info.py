"""Chinese calendar details for page generation: lunar dates, solar terms, festivals.

Lunar dates come from macOS Foundation's Chinese calendar (via JavaScript for
Automation), so no third-party data or packages are needed. Solar terms are
computed from the Sun's apparent longitude (Meeus, low-precision; about 15
minutes of error, so a term within minutes of midnight could land a day off).
Statutory holidays and make-up workdays are announced yearly and not included.
"""

import json
import math
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
LUNAR_MONTHS = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
DIGITS = "一二三四五六七八九十"
WEEKDAYS = "一二三四五六日"

# Sun's apparent longitude in multiples of 15°, starting at 0° (春分).
SOLAR_TERMS = ["春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
               "立秋", "处暑", "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
               "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰"]

SOLAR_FESTIVALS = {
    (1, 1): "元旦", (3, 8): "妇女节", (5, 1): "劳动节", (5, 4): "青年节",
    (6, 1): "儿童节", (9, 10): "教师节", (10, 1): "国庆节", (12, 25): "圣诞节",
}
LUNAR_FESTIVALS = {
    (1, 1): "春节", (1, 15): "元宵节", (2, 2): "龙抬头", (5, 5): "端午节",
    (7, 7): "七夕", (7, 15): "中元节", (8, 15): "中秋节", (9, 9): "重阳节",
    (12, 8): "腊八节", (12, 23): "小年",
}
# Festivals that get the "major" treatment (accent color) on pages.
MAJOR = {"元旦", "春节", "除夕", "元宵节", "清明", "劳动节", "端午节", "中秋节", "国庆节"}

CHINA_TZ = timezone(timedelta(hours=8))

_JXA = r"""
function run(argv) {
  ObjC.import("Foundation");
  const chinese = $.NSCalendar.calendarWithIdentifier("chinese");
  const greg = $.NSCalendar.calendarWithIdentifier("gregorian");
  const [y, m, d] = argv[0].split("-").map(Number);
  const out = [];
  for (let i = 0; i < Number(argv[1]); i++) {
    const c = $.NSDateComponents.alloc.init;
    c.year = y; c.month = m; c.day = d + i; c.hour = 12;
    const lc = chinese.componentsFromDate(
      $.NSCalendarUnitYear | $.NSCalendarUnitMonth | $.NSCalendarUnitDay,
      greg.dateFromComponents(c));
    out.push([lc.year, lc.month, lc.day, lc.isLeapMonth ? 1 : 0]);
  }
  return JSON.stringify(out);
}
"""


@dataclass
class Lunar:
    cycle_year: int  # 1..60, 1 = 甲子
    month: int
    day: int
    leap: bool

    @property
    def year_name(self):
        i = self.cycle_year - 1
        return f"{STEMS[i % 10]}{BRANCHES[i % 12]}"

    @property
    def zodiac(self):
        return ZODIAC[(self.cycle_year - 1) % 12]

    @property
    def month_name(self):
        return ("闰" if self.leap else "") + LUNAR_MONTHS[self.month - 1] + "月"

    @property
    def day_name(self):
        if self.day <= 10:
            return "初" + DIGITS[self.day - 1]
        if self.day < 20:
            return "十" + DIGITS[self.day - 11]
        if self.day == 20:
            return "二十"
        if self.day < 30:
            return "廿" + DIGITS[self.day - 21]
        return "三十"


@dataclass
class DayInfo:
    day: date
    lunar: Lunar
    term: str = None
    festivals: list = field(default_factory=list)

    @property
    def weekday_name(self):
        return "星期" + WEEKDAYS[self.day.weekday()]

    @property
    def weekend(self):
        return self.day.weekday() >= 5

    @property
    def highlight(self):
        """Most notable label for the day: festival first, then solar term."""
        return self.festivals[0] if self.festivals else self.term

    @property
    def major(self):
        return any(name in MAJOR for name in self.festivals + [self.term])

    @property
    def short_label(self):
        """Text under a date in a month grid: festival, term, month start, or lunar day."""
        if self.highlight:
            return self.highlight
        if self.lunar.day == 1:
            return self.lunar.month_name
        return self.lunar.day_name


def lunar_dates(start, count):
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", _JXA, start.isoformat(), str(count)],
        capture_output=True, text=True, check=True)
    # NSInteger values arrive as strings through the ObjC bridge.
    return [Lunar(int(y), int(m), int(d), bool(leap)) for y, m, d, leap in json.loads(result.stdout)]


def _sun_longitude(moment):
    """Apparent ecliptic longitude of the Sun in degrees (Meeus ch. 25)."""
    jd = moment.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545.0) / 36525
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m) + 0.000289 * math.sin(3 * m))
    omega = math.radians(125.04 - 1934.136 * t)
    return (l0 + c - 0.00569 - 0.00478 * math.sin(omega)) % 360


def solar_term(day):
    """Name of the solar term starting on this China-time day, if any."""
    start = datetime(day.year, day.month, day.day, tzinfo=CHINA_TZ)
    a = _sun_longitude(start)
    b = _sun_longitude(start + timedelta(days=1))
    if b < a:
        b += 360
    boundary = math.floor(b / 15) * 15
    if boundary > a:
        return SOLAR_TERMS[int(boundary % 360) // 15]
    return None


def _nth_weekday(year, month, weekday, n):
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def build(start, count):
    """DayInfo for `count` consecutive days starting at `start`."""
    # One extra day so 除夕 (the day before 春节) can be found at the end.
    lunars = lunar_dates(start, count + 1)
    days = []
    for i in range(count + 1):
        day = start + timedelta(days=i)
        lunar = lunars[i]
        info = DayInfo(day, lunar, solar_term(day))
        if (day.month, day.day) in SOLAR_FESTIVALS:
            info.festivals.append(SOLAR_FESTIVALS[(day.month, day.day)])
        if day == _nth_weekday(day.year, 5, 6, 2):
            info.festivals.append("母亲节")
        if day == _nth_weekday(day.year, 6, 6, 3):
            info.festivals.append("父亲节")
        if not lunar.leap and (lunar.month, lunar.day) in LUNAR_FESTIVALS:
            info.festivals.insert(0, LUNAR_FESTIVALS[(lunar.month, lunar.day)])
        days.append(info)
    for today, tomorrow in zip(days, days[1:]):
        if "春节" in tomorrow.festivals:
            today.festivals.insert(0, "除夕")
    return days[:count]


def month_days(year, month):
    """DayInfo for every day of a month."""
    first = date(year, month, 1)
    following = date(year + month // 12, month % 12 + 1, 1)
    return build(first, (following - first).days)

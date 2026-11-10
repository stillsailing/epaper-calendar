"""Tests for calendar_info.py. Run: python3 -m unittest discover -s scripts"""

import unittest
from datetime import date

import calendar_info as info


class Lunar(unittest.TestCase):
    def test_names(self):
        day = info.build(date(2026, 11, 9), 1)[0]
        self.assertEqual((day.lunar.year_name, day.lunar.zodiac), ("丙午", "马"))
        self.assertEqual((day.lunar.month_name, day.lunar.day_name), ("十月", "初一"))
        self.assertEqual(day.weekday_name, "星期一")

    def test_leap_month(self):
        day = info.build(date(2025, 7, 25), 1)[0]
        self.assertEqual(day.lunar.month_name, "闰六月")

    def test_day_names(self):
        names = [info.Lunar(1, 1, d, False).day_name for d in (1, 10, 11, 20, 21, 30)]
        self.assertEqual(names, ["初一", "初十", "十一", "二十", "廿一", "三十"])


class Festivals(unittest.TestCase):
    def test_lunar_festivals(self):
        days = {d.day: d.festivals for d in info.build(date(2026, 1, 1), 450) if d.festivals}
        self.assertIn("春节", days[date(2026, 2, 17)])
        self.assertIn("除夕", days[date(2026, 2, 16)])
        self.assertIn("端午节", days[date(2026, 6, 19)])
        self.assertIn("中秋节", days[date(2026, 9, 25)])
        self.assertIn("除夕", days[date(2027, 2, 5)])  # 腊月廿九: no 三十 that year.
        self.assertIn("春节", days[date(2027, 2, 6)])
        self.assertIn("母亲节", days[date(2026, 5, 10)])

    def test_solar_terms_2026(self):
        terms = {d.term: d.day for d in info.build(date(2026, 1, 1), 365) if d.term}
        self.assertEqual(len(terms), 24)
        expected = {"小寒": (1, 5), "立春": (2, 4), "春分": (3, 20), "清明": (4, 5),
                    "立夏": (5, 5), "夏至": (6, 21), "立秋": (8, 7), "秋分": (9, 23),
                    "立冬": (11, 7), "冬至": (12, 22)}
        for name, (month, day) in expected.items():
            self.assertEqual(terms[name], date(2026, month, day), name)


if __name__ == "__main__":
    unittest.main()

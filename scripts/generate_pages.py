#!/usr/bin/env python3
"""Render one 800 x 480 calendar page per day, plus fallback.png.

Output feeds pack_calendar.py. Colors are the panel's six pure colors so
quantization keeps them exact; only anti-aliased text edges are approximated.
"""

import argparse
import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required: python3 -m pip install --user -r scripts/requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / ".build/pages"
DEFAULT_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

WIDTH, HEIGHT = 800, 480
BLACK, WHITE, YELLOW = (0, 0, 0), (255, 255, 255), (255, 255, 0)
RED, BLUE = (255, 0, 0), (0, 0, 255)
WEEKDAYS = "一二三四五六日"


class Fonts:
    def __init__(self, path):
        self.path = path
        self.cache = {}

    def __call__(self, size):
        if size not in self.cache:
            self.cache[size] = ImageFont.truetype(self.path, size)
        return self.cache[size]


def centered(draw, box, text, font, fill):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = box[0] + (box[2] - box[0] - (right - left)) / 2 - left
    y = box[1] + (box[3] - box[1] - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)


def render_day(day, font):
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    # Left panel: month, day number, weekday.
    draw.rectangle((0, 0, 299, HEIGHT), fill=RED)
    centered(draw, (0, 20, 300, 80), f"{day.year}年{day.month}月", font(36), WHITE)
    centered(draw, (0, 90, 300, 330), str(day.day), font(190), WHITE)
    centered(draw, (0, 340, 300, 390), f"星期{WEEKDAYS[day.weekday()]}", font(34), WHITE)
    day_of_year = day.timetuple().tm_yday
    centered(draw, (0, 400, 300, 440), f"第 {day_of_year} 天", font(24), YELLOW)

    # Right panel: month grid with today highlighted, weekends in red.
    cell_w, cell_h, left, top = 66, 62, 320, 20
    for col, name in enumerate(WEEKDAYS):
        centered(draw, (left + col * cell_w, top, left + (col + 1) * cell_w, top + 44),
                 name, font(24), RED if col >= 5 else BLACK)
    draw.line((left + 8, top + 50, left + 7 * cell_w - 8, top + 50), fill=BLACK, width=2)
    weeks = calendar.monthcalendar(day.year, day.month)
    row_h = min(cell_h, (HEIGHT - top - 64) // len(weeks))
    for row, week in enumerate(weeks):
        for col, number in enumerate(week):
            if not number:
                continue
            box = (left + col * cell_w, top + 60 + row * row_h,
                   left + (col + 1) * cell_w, top + 60 + (row + 1) * row_h)
            color = RED if col >= 5 else BLACK
            if number == day.day:
                cx, cy, r = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, min(row_h, cell_w) / 2 - 3
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLUE)
                color = WHITE
            centered(draw, box, str(number), font(28), color)
    return image


def render_fallback(font):
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 120), fill=BLUE)
    centered(draw, (0, 0, WIDTH, 120), "电子日历", font(56), WHITE)
    centered(draw, (0, 170, WIDTH, 250), "暂时无法显示今天的页面", font(44), BLACK)
    centered(draw, (0, 280, WIDTH, 330), "时钟未设置，或没有这一天的图片", font(30), RED)
    centered(draw, (0, 350, WIDTH, 400), "请连接电脑运行 scripts/set_rtc.py 校时", font(26), BLACK)
    return image


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=date.fromisoformat, default=date.today(),
                        help="first day, YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, default=365, help="number of days (default: 365)")
    parser.add_argument("--font", default=DEFAULT_FONT, help="TrueType/OpenType font with CJK glyphs")
    args = parser.parse_args(argv)

    try:
        font = Fonts(args.font)
        font(12)
    except OSError as error:
        parser.exit(1, f"error: cannot load font {args.font}: {error}\n")

    args.output.mkdir(parents=True, exist_ok=True)
    render_fallback(font).save(args.output / "fallback.png")
    for offset in range(args.days):
        day = args.start + timedelta(days=offset)
        render_day(day, font).save(args.output / f"{day.isoformat()}.png")
    last = args.start + timedelta(days=args.days - 1)
    print(f"wrote {args.days} pages ({args.start} .. {last}) and fallback.png to {args.output}")


if __name__ == "__main__":
    main()

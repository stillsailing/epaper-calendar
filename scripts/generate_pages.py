#!/usr/bin/env python3
"""Render one 800 x 480 calendar page per day, a month view per month, and fallback.png.

Output feeds pack_calendar.py. Pages use only the panel's six pure colors and
text is drawn without anti-aliasing, so quantization keeps every pixel exact.
Lunar dates, solar terms and festivals come from calendar_info.py.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is required: python3 -m pip install --user -r scripts/requirements.txt")

import calendar_info as info

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / ".build/pages"

WIDTH, HEIGHT = 800, 480
BLACK, WHITE, YELLOW = (0, 0, 0), (255, 255, 255), (255, 255, 0)
RED, BLUE, GREEN = (255, 0, 0), (0, 0, 255), (0, 255, 0)

_SYS = "/System/Library/Fonts/"
_SUP = _SYS + "Supplemental/"
FACES = {
    "song_black": (_SUP + "Songti.ttc", 0),
    "song_bold": (_SUP + "Songti.ttc", 1),
    "hei": (_SYS + "Hiragino Sans GB.ttc", 0),
    "hei_bold": (_SYS + "Hiragino Sans GB.ttc", 2),
    "din": (_SUP + "DIN Condensed Bold.ttf", 0),
    "bodoni": (_SUP + "Bodoni 72.ttc", 2),
    "futura_xb": (_SUP + "Futura.ttc", 4),
    "avenir_demi": (_SYS + "Avenir Next Condensed.ttc", 2),
}
MONTHS_EN = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
             "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
WEEKDAYS_EN = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
MONTHS_CN = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
# Month-view grid area. The firmware frames today's cell from the same numbers
# (kMonthGrid* in epaper_calendar.ino; test_pack_calendar.py checks they match).
MONTH_GRID_LEFT, MONTH_GRID_RIGHT, MONTH_GRID_TOP, MONTH_GRID_BOTTOM = 40, 760, 116, 436

_font_cache = {}


def font(face, size):
    key = (face, size)
    if key not in _font_cache:
        path, index = FACES[face]
        _font_cache[key] = ImageFont.truetype(path, size, index=index)
    return _font_cache[key]


def canvas(color=WHITE):
    image = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # No anti-aliasing: every pixel stays one of the six colors.
    return image, draw


def vertical(draw, x, y, text, face, size, fill, spacing=1.08):
    """Top-to-bottom CJK text centered on column x, starting at y."""
    for i, ch in enumerate(text):
        draw.text((x, y + i * size * spacing + size / 2), ch, font=font(face, size), fill=fill,
                  anchor="mm")


def pill(draw, center, text, face, size, fill, background, pad=(14, 6)):
    left, top, right, bottom = draw.textbbox(center, text, font=font(face, size), anchor="mm")
    draw.rounded_rectangle((left - pad[0], top - pad[1], right + pad[0], bottom + pad[1]),
                           radius=(bottom - top) // 2 + pad[1], fill=background)
    draw.text(center, text, font=font(face, size), fill=fill, anchor="mm")


def next_major(today, lookahead):
    for later in lookahead:
        if later.day > today.day and later.major:
            return later
    return None


# --- Style: almanac (黄历) -------------------------------------------------

def almanac(today, lookahead, month):
    image, draw = canvas()
    accent = RED if today.weekend or today.major else BLACK
    d = today.day

    # Header.
    draw.text((40, 44), str(d.year), font=font("bodoni", 34), fill=BLACK, anchor="ls")
    draw.text((400, 44), f"{MONTHS_CN[d.month - 1]}月  {MONTHS_EN[d.month - 1]}",
              font=font("song_bold", 26), fill=BLACK, anchor="ms")
    draw.text((760, 44), f"{today.lunar.year_name}{today.lunar.zodiac}年",
              font=font("song_bold", 26), fill=BLACK, anchor="rs")
    draw.rectangle((40, 60, 760, 63), fill=BLACK)
    draw.rectangle((40, 67, 760, 67), fill=BLACK)

    # Giant day number and weekday.
    draw.text((300, 268), str(d.day), font=font("bodoni", 300), fill=accent, anchor="mm")
    draw.text((300, 420), f"{today.weekday_name}", font=font("song_black", 34), fill=accent,
              anchor="rs")
    draw.text((312, 420), WEEKDAYS_EN[d.weekday()], font=font("bodoni", 26), fill=accent,
              anchor="ls")

    # Lunar seal: red block with vertical white text.
    seal_text = today.lunar.month_name + today.lunar.day_name
    seal_h = 34 + len(seal_text) * 50
    draw.rectangle((590, 96, 680, 96 + seal_h), fill=RED)
    vertical(draw, 635, 113, seal_text, "song_black", 46, WHITE)
    draw.text((635, 96 + seal_h + 30), "农历", font=font("song_bold", 22), fill=BLACK,
              anchor="mm")
    if today.highlight:
        pill(draw, (635, 96 + seal_h + 74), today.highlight, "song_black", 28, BLACK, YELLOW)

    # Footer: day of year and countdown to the next major day.
    draw.rectangle((40, 444, 760, 445), fill=BLACK)
    draw.text((40, 468), f"{d.year} 年第 {d.timetuple().tm_yday} 天", font=font("hei", 18),
              fill=BLACK, anchor="ls")
    upcoming = next_major(today, lookahead)
    if upcoming:
        days = (upcoming.day - d).days
        draw.text((760, 468), f"距{upcoming.highlight}还有 {days} 天", font=font("hei_bold", 18),
                  fill=RED, anchor="rs")
    return image


# --- Style: month grid (月历) ---------------------------------------------

def grid(today, lookahead, month):
    image, draw = canvas()
    d = today.day

    # Left panel: yellow block with the day.
    draw.rectangle((0, 0, 270, HEIGHT), fill=YELLOW)
    draw.text((32, 56), f"{d.month:02d}", font=font("din", 44), fill=BLACK, anchor="ls")
    draw.text((84, 56), f"/ {MONTHS_EN[d.month - 1][:3]}", font=font("din", 30), fill=BLACK,
              anchor="ls")
    draw.text((135, 236), f"{d.day:02d}", font=font("din", 250), fill=BLACK, anchor="mm")
    draw.rectangle((32, 330, 238, 333), fill=BLACK)
    draw.text((32, 378), today.weekday_name, font=font("song_black", 36), fill=BLACK, anchor="ls")
    draw.text((32, 418), f"农历{today.lunar.month_name}{today.lunar.day_name}",
              font=font("hei_bold", 22), fill=BLACK, anchor="ls")
    if today.highlight:
        draw.rectangle((32, 432, 32 + 30 * len(today.highlight) + 20, 466), fill=RED)
        draw.text((42, 459), today.highlight, font=font("hei_bold", 24), fill=WHITE, anchor="ls")

    # Right: month header and grid with lunar labels.
    left, cell_w = 300, 68
    draw.text((left, 56), f"{d.year}", font=font("din", 44), fill=BLACK, anchor="ls")
    draw.text((left + 90, 56), f"{MONTHS_CN[d.month - 1]}月", font=font("song_black", 30),
              fill=BLACK, anchor="ls")
    draw.text((left + 7 * cell_w - 12, 56), f"{today.lunar.year_name}{today.lunar.zodiac}年",
              font=font("hei", 20), fill=BLACK, anchor="rs")
    for col, name in enumerate(info.WEEKDAYS):
        draw.text((left + col * cell_w + cell_w / 2, 96), name, font=font("hei_bold", 20),
                  fill=RED if col >= 5 else BLACK, anchor="ms")
    draw.rectangle((left + 6, 106, left + 7 * cell_w - 6, 107), fill=BLACK)

    first_col = month[0].day.weekday()
    rows = (first_col + len(month) + 6) // 7
    row_h = min(62, (HEIGHT - 120 - 10) // rows)
    for item in month:
        index = first_col + item.day.day - 1
        col, row = index % 7, index // 7
        cx = left + col * cell_w + cell_w / 2
        top = 116 + row * row_h
        is_today = item.day == d
        number_color = RED if col >= 5 or item.major else BLACK
        label_color = RED if item.highlight else BLACK
        if is_today:
            draw.rectangle((cx - cell_w / 2 + 3, top, cx + cell_w / 2 - 3, top + row_h - 6),
                           fill=BLACK)
            number_color = label_color = YELLOW
        draw.text((cx, top + 32), str(item.day.day), font=font("din", 32), fill=number_color,
                  anchor="ms")
        label = item.short_label
        draw.text((cx, top + 51), label if len(label) <= 3 else label[:3],
                  font=font("hei", 14), fill=label_color, anchor="ms")
    return image


# --- Style: poster (海报) -------------------------------------------------

def poster(today, lookahead, month):
    d = today.day
    background = RED if today.weekend or today.major else BLUE
    image, draw = canvas(background)

    draw.text((40, 62), f"{d.year}.{d.month:02d}", font=font("din", 46), fill=WHITE, anchor="ls")
    draw.text((760, 58), f"{today.lunar.year_name}{today.lunar.zodiac}年",
              font=font("song_black", 30), fill=WHITE, anchor="rs")

    # Giant number on the left, text block on the right.
    draw.text((210, 236), str(d.day), font=font("futura_xb", 290), fill=WHITE, anchor="mm")
    draw.text((430, 190), today.weekday_name, font=font("song_black", 64), fill=WHITE,
              anchor="ls")
    draw.text((432, 244), f"农历{today.lunar.month_name}{today.lunar.day_name}",
              font=font("song_bold", 34), fill=YELLOW, anchor="ls")
    if today.highlight:
        left, top, right, bottom = draw.textbbox((432, 304), today.highlight,
                                                 font=font("song_black", 40), anchor="ls")
        draw.rectangle((left - 12, top - 10, right + 12, bottom + 10), fill=YELLOW)
        draw.text((432, 304), today.highlight, font=font("song_black", 40), fill=BLACK,
                  anchor="ls")

    # Week strip.
    monday = d - timedelta(days=d.weekday())
    by_day = {m.day: m for m in month + lookahead}
    cell_w, top, bottom = 96, 372, 452
    left = (WIDTH - 7 * cell_w) // 2 + 4
    for i in range(7):
        day = monday + timedelta(days=i)
        x0 = left + i * cell_w
        box = (x0 + 4, top, x0 + cell_w - 4, bottom)
        if day == d:
            draw.rectangle(box, fill=YELLOW)
            fg = BLACK
        else:
            draw.rectangle(box, outline=WHITE, width=2)
            fg = WHITE
        cx = (box[0] + box[2]) / 2
        draw.text((cx, top + 26), info.WEEKDAYS[i], font=font("hei_bold", 18), fill=fg,
                  anchor="ms")
        draw.text((cx, top + 66), str(day.day), font=font("din", 38), fill=fg, anchor="ms")
        item = by_day.get(day)
        if item and item.highlight and day != d:
            draw.rectangle((box[2] - 12, top + 6, box[2] - 6, top + 12), fill=YELLOW)
    return image


STYLES = {"almanac": almanac, "grid": grid, "poster": poster}


def render_month(year, month):
    """Whole-month view (YYYY-MM.png), in the almanac style; the firmware's month key shows it
    and draws a frame around today's cell."""
    days = info.month_days(year, month)
    first, last = days[0], days[-1]
    image, draw = canvas()

    draw.text((40, 44), str(year), font=font("bodoni", 34), fill=BLACK, anchor="ls")
    draw.text((400, 44), f"{MONTHS_CN[month - 1]}月  {MONTHS_EN[month - 1]}",
              font=font("song_bold", 26), fill=BLACK, anchor="ms")
    draw.text((760, 44), f"{first.lunar.year_name}{first.lunar.zodiac}年",
              font=font("song_bold", 26), fill=BLACK, anchor="rs")
    draw.rectangle((40, 60, 760, 63), fill=BLACK)
    draw.rectangle((40, 67, 760, 67), fill=BLACK)

    left, cell_w = MONTH_GRID_LEFT, (MONTH_GRID_RIGHT - MONTH_GRID_LEFT) / 7
    for col, name in enumerate(info.WEEKDAYS):
        draw.text((left + (col + 0.5) * cell_w, 100), name, font=font("song_bold", 22),
                  fill=RED if col >= 5 else BLACK, anchor="ms")
    draw.rectangle((40, 110, 760, 110), fill=BLACK)

    first_col = first.day.weekday()
    rows = (first_col + len(days) + 6) // 7
    top0, row_h = MONTH_GRID_TOP, (MONTH_GRID_BOTTOM - MONTH_GRID_TOP) / rows
    for item in days:
        index = first_col + item.day.day - 1
        col, row = index % 7, index // 7
        cx, top = left + (col + 0.5) * cell_w, top0 + row * row_h
        if item.major:
            draw.rectangle((cx - cell_w / 2 + 4, top + 3, cx + cell_w / 2 - 4, top + row_h - 3),
                           fill=YELLOW)
        number_color = RED if col >= 5 or item.major else BLACK
        draw.text((cx, top + row_h * 0.56), str(item.day.day),
                  font=font("bodoni", 34 if rows == 5 else 30), fill=number_color, anchor="ms")
        label = item.short_label
        draw.text((cx, top + row_h * 0.88), label if len(label) <= 4 else label[:4],
                  font=font("hei", 15), fill=RED if item.highlight else BLACK, anchor="ms")

    draw.rectangle((40, 444, 760, 445), fill=BLACK)
    draw.text((40, 468), f"农历 {first.lunar.month_name}{first.lunar.day_name} 至 "
              f"{last.lunar.month_name}{last.lunar.day_name}", font=font("hei", 18), fill=BLACK,
              anchor="ls")
    terms = " · ".join(f"{d.term} {d.day.day} 日" for d in days if d.term)
    draw.text((760, 468), terms, font=font("hei_bold", 18), fill=RED, anchor="rs")
    return image


def render_fallback():
    """Shown when the clock is unset or a date has no page; matches the almanac style."""
    image, draw = canvas()
    draw.text((40, 44), "电子日历", font=font("song_black", 30), fill=BLACK, anchor="ls")
    draw.rectangle((40, 60, 760, 63), fill=BLACK)
    draw.rectangle((40, 67, 760, 67), fill=BLACK)

    draw.rectangle((70, 120, 160, 120 + 34 + 4 * 50), fill=RED)
    vertical(draw, 115, 137, "等待校时", "song_black", 46, WHITE)

    draw.text((210, 190), "暂时无法显示今天的页面", font=font("song_black", 44), fill=BLACK,
              anchor="ls")
    draw.text((210, 240), "时钟未设置，或没有这一天的图片", font=font("hei_bold", 26), fill=RED,
              anchor="ls")
    draw.text((210, 312), "连接电脑后运行：", font=font("hei", 22), fill=BLACK, anchor="ls")
    pill(draw, (420, 360), "python3 scripts/set_rtc.py", "din", 32, BLACK, YELLOW, pad=(18, 8))

    draw.rectangle((40, 444, 760, 445), fill=BLACK)
    draw.text((760, 468), "其余命令见 README", font=font("hei", 18), fill=BLACK, anchor="rs")
    return image


def render_range(start, days, style):
    """Yield (date, image) for each day, sharing calendar lookups."""
    lookahead = info.build(start, days + 400)
    months = {}
    for offset in range(days):
        today = lookahead[offset]
        key = (today.day.year, today.day.month)
        if key not in months:
            months[key] = info.month_days(*key)
        yield today.day, STYLES[style](today, lookahead[offset + 1:offset + 400], months[key])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start", type=date.fromisoformat, default=date.today(),
                        help="first day, YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, default=365, help="number of days (default: 365)")
    parser.add_argument("--style", choices=sorted(STYLES), default="almanac")
    args = parser.parse_args(argv)

    try:
        for face in FACES:
            font(face, 12)
    except OSError as error:
        parser.exit(1, f"error: missing macOS font: {error}\n")

    args.output.mkdir(parents=True, exist_ok=True)
    render_fallback().save(args.output / "fallback.png")
    months = set()
    for day, image in render_range(args.start, args.days, args.style):
        image.save(args.output / f"{day.isoformat()}.png")
        months.add((day.year, day.month))
    for year, month in sorted(months):
        render_month(year, month).save(args.output / f"{year}-{month:02d}.png")
    last = args.start + timedelta(days=args.days - 1)
    print(f"wrote {args.days} {args.style} pages ({args.start} .. {last}), {len(months)} month "
          f"views and fallback.png to {args.output}")


if __name__ == "__main__":
    main()

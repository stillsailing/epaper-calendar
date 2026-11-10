#!/usr/bin/env python3
"""Convert images to and from the GDEP073E01 six-color C array.

The firmware's vendor PIC_display() reads one byte per pixel (800 x 480 =
384,000 bytes) and maps each byte through Color_get(). This tool writes that
exact format, so the output header is a drop-in replacement for image.h.

  encode  PNG/JPG/BMP -> C header (+ optional preview PNG)
  preview C header    -> PNG, using pure RGB stand-ins for the panel colors
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("Pillow is required: python3 -m pip install --user -r scripts/requirements.txt")

WIDTH = 800
HEIGHT = 480

# (name, byte in the C array, preview RGB). Byte values match Color_get() in
# Display_EPD_W21.cpp. The RGB values are idealized; the panel looks different.
PALETTE = (
    ("black", 0x00, (0, 0, 0)),
    ("white", 0xFF, (255, 255, 255)),
    ("yellow", 0xFC, (255, 255, 0)),
    ("red", 0xE0, (255, 0, 0)),
    ("blue", 0x03, (0, 0, 255)),
    ("green", 0x1C, (0, 255, 0)),
)
CODE_BY_NAME = {name: code for name, code, _ in PALETTE}
RGB_BY_CODE = {code: rgb for _, code, rgb in PALETTE}
NAME_BY_CODE = {code: name for name, code, _ in PALETTE}

FITS = ("exact", "contain", "cover")
ROTATIONS = {
    0: None,
    90: Image.Transpose.ROTATE_270,  # Pillow rotates counter-clockwise.
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def prepare(image, fit="exact", rotate=0, background="white"):
    """Return an 800 x 480 RGB image ready for quantization."""
    image = ImageOps.exif_transpose(image)
    if ROTATIONS[rotate] is not None:
        image = image.transpose(ROTATIONS[rotate])

    background_rgb = RGB_BY_CODE[CODE_BY_NAME[background]]
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        image = Image.new("RGBA", rgba.size, background_rgb + (255,))
        image.alpha_composite(rgba)
    image = image.convert("RGB")

    size = (WIDTH, HEIGHT)
    if image.size == size:
        return image
    if fit == "exact":
        raise ValueError(
            f"image is {image.size[0]} x {image.size[1]}, expected {WIDTH} x {HEIGHT}; "
            "use --fit contain/cover or --rotate"
        )
    if fit == "contain":
        return ImageOps.pad(image, size, Image.Resampling.LANCZOS, color=background_rgb)
    return ImageOps.fit(image, size, Image.Resampling.LANCZOS)


def _lab(rgb):
    """sRGB (0-255) to CIELAB, D65."""
    def linear(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in rgb)
    xyz = (
        (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047,
        0.2126 * r + 0.7152 * g + 0.0722 * b,
        (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883,
    )
    fx, fy, fz = (t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116 for t in xyz)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _nearest_table():
    """Palette index for every 5-bit-per-channel RGB cell, by CIELAB distance.

    Plain RGB distance sends slightly warm mid-grays, such as anti-aliased
    text edges, to yellow; Lab keeps them black or white.
    """
    targets = [_lab(rgb) for _, _, rgb in PALETTE]
    levels = [(i << 3) | (i >> 2) for i in range(32)]  # 0..255 inclusive
    table = bytearray(32 * 32 * 32)
    for r in range(32):
        for g in range(32):
            for b in range(32):
                lab = _lab((levels[r], levels[g], levels[b]))
                table[(r << 10) | (g << 5) | b] = min(
                    range(len(targets)),
                    key=lambda i: sum((p - q) ** 2 for p, q in zip(lab, targets[i])),
                )
    return bytes(table)


_NEAREST = None


def quantize(image, dither=False):
    """Map an 800 x 480 RGB image to one palette byte per pixel."""
    global _NEAREST
    if _NEAREST is None:
        _NEAREST = _nearest_table()
    nearest = _NEAREST
    codes = [code for _, code, _ in PALETTE]
    pixels = image.tobytes()

    if not dither:
        return bytes(
            codes[nearest[((pixels[i] >> 3) << 10) | ((pixels[i + 1] >> 3) << 5) | (pixels[i + 2] >> 3)]]
            for i in range(0, len(pixels), 3)
        )

    # Floyd-Steinberg in RGB, choosing colors with the same Lab table.
    colors = [rgb for _, _, rgb in PALETTE]
    width, height = image.size
    out = bytearray(width * height)
    cur = [float(v) for v in pixels[:width * 3]]
    for y in range(height):
        nxt = ([float(v) for v in pixels[(y + 1) * width * 3:(y + 2) * width * 3]]
               if y + 1 < height else [0.0] * (width * 3))
        for x in range(width):
            i = x * 3
            r = min(255, max(0, int(cur[i] + 0.5)))
            g = min(255, max(0, int(cur[i + 1] + 0.5)))
            b = min(255, max(0, int(cur[i + 2] + 0.5)))
            index = nearest[((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)]
            out[y * width + x] = codes[index]
            pr, pg, pb = colors[index]
            for c, err in ((0, cur[i] - pr), (1, cur[i + 1] - pg), (2, cur[i + 2] - pb)):
                if x + 1 < width:
                    cur[i + 3 + c] += err * 7 / 16
                    nxt[i + 3 + c] += err * 1 / 16
                if x > 0:
                    nxt[i - 3 + c] += err * 3 / 16
                nxt[i + c] += err * 5 / 16
        cur = nxt
    return bytes(out)


def to_header(data, name, source):
    lines = [
        f"// Generated by scripts/convert_image.py from {source}.",
        f"// {WIDTH} x {HEIGHT}, one byte per pixel, decoded by Color_get().",
        f"const unsigned char {name}[{len(data)}] = {{",
    ]
    for offset in range(0, len(data), 16):
        lines.append(",".join(f"0X{b:02X}" for b in data[offset:offset + 16]) + ",")
    lines.append("};")
    return "\n".join(lines) + "\n"


def parse_header(text):
    """Return the bytes of the first array initializer in a C header."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    match = re.search(r"\{(.*?)\}", text, flags=re.S)
    if not match:
        raise ValueError("no array initializer found")
    values = [int(token, 16) for token in re.findall(r"0[xX][0-9a-fA-F]+", match.group(1))]
    if len(values) != WIDTH * HEIGHT:
        raise ValueError(f"array has {len(values)} bytes, expected {WIDTH * HEIGHT}")
    return bytes(values)


def render(data):
    """Render palette bytes as RGB. Unknown bytes become black, like Color_get()."""
    lut = {code: bytes(rgb) for code, rgb in RGB_BY_CODE.items()}
    black = lut[CODE_BY_NAME["black"]]
    rgb = b"".join(lut.get(b, black) for b in data)
    return Image.frombytes("RGB", (WIDTH, HEIGHT), rgb)


def summary(data):
    counts = Counter(data)
    total = len(data)
    parts = [
        f"{NAME_BY_CODE[code]} {counts[code] * 100 / total:.1f}%"
        for _, code, _ in PALETTE
        if counts[code]
    ]
    unknown = sum(n for code, n in counts.items() if code not in NAME_BY_CODE)
    if unknown:
        parts.append(f"unknown(shown as black) {unknown}")
    return ", ".join(parts)


def cmd_encode(args):
    with Image.open(args.input) as source:
        image = prepare(source, args.fit, args.rotate, args.background)
    data = quantize(image, args.dither)
    args.output.write_text(to_header(data, args.name, args.input.name), encoding="ascii")
    print(f"wrote {args.output} ({len(data)} bytes): {summary(data)}")
    if args.preview:
        render(data).save(args.preview)
        print(f"wrote {args.preview}")


def cmd_preview(args):
    data = parse_header(args.header.read_text(encoding="ascii", errors="replace"))
    render(data).save(args.output)
    print(f"wrote {args.output}: {summary(data)}")


def c_identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise argparse.ArgumentTypeError(f"not a C identifier: {value}")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    enc = sub.add_parser("encode", help="convert an image to a C header")
    enc.add_argument("input", type=Path)
    enc.add_argument("-o", "--output", type=Path, required=True, help="header to write")
    enc.add_argument("--preview", type=Path, help="also write a PNG preview of the result")
    enc.add_argument("--name", type=c_identifier, default="gImage_1",
                     help="array name (default: gImage_1, used by the sketch)")
    enc.add_argument("--fit", choices=FITS, default="exact",
                     help="exact: require 800x480 (default); contain: letterbox; cover: crop")
    enc.add_argument("--rotate", type=int, choices=sorted(ROTATIONS), default=0,
                     help="rotate clockwise before fitting, e.g. 90 for a 480x800 design")
    enc.add_argument("--background", choices=list(CODE_BY_NAME), default="white",
                     help="color for transparency and --fit contain borders")
    enc.add_argument("--dither", action="store_true",
                     help="Floyd-Steinberg dithering, for photos; leave off for text and flat colors")
    enc.set_defaults(func=cmd_encode)

    prev = sub.add_parser("preview", help="render a C header to PNG")
    prev.add_argument("header", type=Path)
    prev.add_argument("-o", "--output", type=Path, required=True)
    prev.set_defaults(func=cmd_preview)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()

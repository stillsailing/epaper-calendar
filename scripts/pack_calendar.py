#!/usr/bin/env python3
"""Pack dated calendar pages into the firmware's "calendar" flash partition.

Input is a directory of images named YYYY-MM-DD.png (or .jpg/.bmp), plus an
optional fallback.png shown when the clock is unset or a date has no page.
Each page is quantized with convert_image.py, packed two pixels per byte in
the panel's own 4-bit codes, and zlib-compressed.

Blob layout (little-endian), read by calendar_store.cpp:
  header  16 B: "ECAL", u16 version=1, u16 count, u16 width, u16 height, u32 total size
  entries 16 B each, sorted by date: u32 YYYYMMDD (0 = fallback), u32 offset,
          u32 compressed length, u32 CRC-32 of the compressed bytes
  pages   zlib streams, each inflating to 192,000 bytes
"""

import argparse
import re
import struct
import sys
import zlib
from datetime import date, timedelta
from pathlib import Path

import convert_image as ci

ROOT = Path(__file__).resolve().parent.parent
PARTITIONS = ROOT / "firmware/epaper_calendar/partitions.csv"
DEFAULT_OUTPUT = ROOT / ".build/calendar-data.bin"

MAGIC = b"ECAL"
VERSION = 1
HEADER = struct.Struct("<4sHHHHI")
ENTRY = struct.Struct("<IIII")
FALLBACK_DATE = 0
PAGE_BYTES = ci.WIDTH * ci.HEIGHT // 2

# Array byte -> nibble sent to the panel, as in the vendor Color_get().
PANEL_NIBBLE = {0x00: 0x0, 0xFF: 0x1, 0xFC: 0x2, 0xE0: 0x3, 0x03: 0x5, 0x1C: 0x6}
CODE_BY_NIBBLE = {nibble: code for code, nibble in PANEL_NIBBLE.items()}
NAME_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}


def pack_nibbles(data):
    return bytes((PANEL_NIBBLE[data[i]] << 4) | PANEL_NIBBLE[data[i + 1]]
                 for i in range(0, len(data), 2))


def unpack_nibbles(packed):
    out = bytearray()
    for b in packed:
        out.append(CODE_BY_NIBBLE[b >> 4])
        out.append(CODE_BY_NIBBLE[b & 0xF])
    return bytes(out)


def date_key(day):
    return day.year * 10000 + day.month * 100 + day.day


def build_blob(pages):
    """pages: {date_key: palette bytes (one per pixel)} -> blob bytes."""
    keys = sorted(pages)
    offset = HEADER.size + ENTRY.size * len(keys)
    entries, payloads = [], []
    for key in keys:
        compressed = zlib.compress(pack_nibbles(pages[key]), 9)
        entries.append(ENTRY.pack(key, offset, len(compressed), zlib.crc32(compressed)))
        payloads.append(compressed)
        offset += len(compressed)
    header = HEADER.pack(MAGIC, VERSION, len(keys), ci.WIDTH, ci.HEIGHT, offset)
    return header + b"".join(entries) + b"".join(payloads)


def read_blob(blob):
    """Inverse of build_blob, with the same checks the firmware makes."""
    magic, version, count, width, height, total = HEADER.unpack_from(blob)
    if (magic, version, width, height) != (MAGIC, VERSION, ci.WIDTH, ci.HEIGHT):
        raise ValueError("bad header")
    if total != len(blob):
        raise ValueError("size mismatch")
    pages = {}
    for i in range(count):
        key, offset, length, crc = ENTRY.unpack_from(blob, HEADER.size + i * ENTRY.size)
        compressed = blob[offset:offset + length]
        if zlib.crc32(compressed) != crc:
            raise ValueError(f"CRC mismatch for {key}")
        packed = zlib.decompress(compressed)
        if len(packed) != PAGE_BYTES:
            raise ValueError(f"page {key} inflates to {len(packed)} bytes")
        pages[key] = unpack_nibbles(packed)
    return pages


def partition_size(name="calendar", path=PARTITIONS):
    for line in path.read_text().splitlines():
        fields = [f.strip() for f in line.split("#", 1)[0].split(",")]
        if len(fields) >= 5 and fields[0] == name:
            return int(fields[4], 0)
    raise ValueError(f"partition {name!r} not found in {path}")


def collect(directory):
    """Return {date_key or FALLBACK_DATE: path}."""
    found = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.stem == "fallback":
            key = FALLBACK_DATE
        else:
            match = NAME_PATTERN.fullmatch(path.stem)
            if not match:
                print(f"skipping {path.name}: name is not YYYY-MM-DD or fallback", file=sys.stderr)
                continue
            key = date_key(date(*map(int, match.groups())))
        if key in found:
            raise ValueError(f"two images for the same date: {found[key].name}, {path.name}")
        found[key] = path
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pages", type=Path, help="directory of YYYY-MM-DD.png and optional fallback.png")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fit", choices=ci.FITS, default="exact")
    parser.add_argument("--rotate", type=int, choices=sorted(ci.ROTATIONS), default=0)
    parser.add_argument("--background", choices=list(ci.CODE_BY_NAME), default="white")
    parser.add_argument("--dither", action="store_true")
    args = parser.parse_args(argv)

    try:
        sources = collect(args.pages)
        if not sources:
            raise ValueError(f"no pages found in {args.pages}")
        pages = {}
        for key, path in sources.items():
            with ci.Image.open(path) as image:
                pages[key] = ci.quantize(
                    ci.prepare(image, args.fit, args.rotate, args.background), args.dither)
        blob = build_blob(pages)
        capacity = partition_size()
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")

    dated = sorted(k for k in pages if k != FALLBACK_DATE)
    sizes = [ENTRY.unpack_from(blob, HEADER.size + i * ENTRY.size)[2] for i in range(len(pages))]
    print(f"{len(dated)} dated pages" + (" + fallback" if FALLBACK_DATE in pages else " (no fallback)"))
    if dated:
        first, last = (date(k // 10000, k // 100 % 100, k % 100) for k in (dated[0], dated[-1]))
        missing = (last - first).days + 1 - len(dated)
        print(f"range {first} .. {last}" + (f", {missing} days without a page" if missing else ""))
    print(f"pages: average {sum(sizes) // len(sizes):,} B, largest {max(sizes):,} B")
    print(f"total {len(blob):,} B of {capacity:,} B partition ({len(blob) * 100 / capacity:.1f}%)")
    if len(blob) > capacity:
        parser.exit(1, "error: data does not fit the calendar partition\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()

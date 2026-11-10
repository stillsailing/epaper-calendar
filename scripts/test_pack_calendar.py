"""Tests for pack_calendar.py and generate_pages.py. Run: python3 -m unittest discover -s scripts"""

import struct
import tempfile
import unittest
import zlib
from datetime import date
from pathlib import Path

from PIL import Image

import convert_image as ci
import generate_pages as gp
import pack_calendar as pc


def solid(code):
    return bytes([code]) * (ci.WIDTH * ci.HEIGHT)


class Blob(unittest.TestCase):
    def test_nibbles_match_vendor_color_get(self):
        # Color_get(): black 0, white 1, yellow 2, red 3, blue 5, green 6; first pixel high.
        self.assertEqual(pc.pack_nibbles(bytes([0x00, 0xFF, 0xFC, 0xE0, 0x03, 0x1C])),
                         bytes([0x01, 0x23, 0x56]))

    def test_round_trip_and_layout(self):
        pages = {20261109: solid(0xE0), pc.FALLBACK_DATE: solid(0xFF), 20261110: solid(0x03)}
        blob = pc.build_blob(pages)
        self.assertEqual(pc.read_blob(blob), pages)
        magic, version, count, width, height, total = pc.HEADER.unpack_from(blob)
        self.assertEqual((magic, version, count, width, height, total),
                         (b"ECAL", 1, 3, 800, 480, len(blob)))
        dates = [pc.ENTRY.unpack_from(blob, 16 + 16 * i)[0] for i in range(count)]
        self.assertEqual(dates, [0, 20261109, 20261110])

    def test_corruption_is_detected(self):
        blob = bytearray(pc.build_blob({20261109: solid(0x00)}))
        blob[-5] ^= 0xFF
        with self.assertRaises(ValueError):
            pc.read_blob(bytes(blob))

    def test_partition_size_matches_csv(self):
        self.assertEqual(pc.partition_size(), 0x2B0000)


class EndToEnd(unittest.TestCase):
    def test_generated_pages_pack_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            pages_dir, out = Path(tmp) / "pages", Path(tmp) / "data.bin"
            # Includes a six-week month (2027-05) and a leap day.
            gp.main(["-o", str(pages_dir), "--start", "2027-05-30", "--days", "3"])
            gp.main(["-o", str(pages_dir), "--start", "2028-02-29", "--days", "1"])
            pc.main([str(pages_dir), "-o", str(out)])
            pages = pc.read_blob(out.read_bytes())
            self.assertEqual(sorted(pages), [0, 20270530, 20270531, 20270601, 20280229])
            sizes = [pc.ENTRY.unpack_from(out.read_bytes(), 16 + 16 * i)[2] for i in range(len(pages))]
            # 365 pages must fit the partition; keep generated pages well under the average budget.
            self.assertLess(max(sizes), pc.partition_size() // 366)

    def test_rejects_duplicate_and_ignores_unrelated_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            Image.new("RGB", (800, 480), "white").save(d / "2026-11-09.png")
            Image.new("RGB", (800, 480), "white").save(d / "notes.png")
            self.assertEqual(list(pc.collect(d)), [20261109])
            Image.new("RGB", (800, 480), "white").save(d / "2026-11-09.jpg")
            with self.assertRaises(ValueError):
                pc.collect(d)


if __name__ == "__main__":
    unittest.main()

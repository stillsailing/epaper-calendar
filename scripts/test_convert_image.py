"""Tests for convert_image.py. Run: python3 -m unittest discover -s scripts"""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

import convert_image as ci

ROOT = Path(__file__).resolve().parent.parent
VENDOR_HEADER = ROOT / "firmware/epaper_calendar/image.h"
VENDOR_PREVIEW = ROOT / "docs/vendor-sample.png"


class VendorRoundTrip(unittest.TestCase):
    def test_header_renders_to_committed_preview(self):
        data = ci.parse_header(VENDOR_HEADER.read_text(encoding="ascii"))
        with Image.open(VENDOR_PREVIEW) as expected:
            self.assertEqual(ci.render(data).tobytes(), expected.convert("RGB").tobytes())

    def test_preview_encodes_back_to_vendor_bytes(self):
        expected = ci.parse_header(VENDOR_HEADER.read_text(encoding="ascii"))
        with Image.open(VENDOR_PREVIEW) as source:
            data = ci.quantize(ci.prepare(source))
        self.assertEqual(data, expected)

    def test_written_header_parses_back(self):
        data = ci.parse_header(VENDOR_HEADER.read_text(encoding="ascii"))
        self.assertEqual(ci.parse_header(ci.to_header(data, "gImage_1", "x.png")), data)


class Quantize(unittest.TestCase):
    def solid(self, rgb):
        return Image.new("RGB", (ci.WIDTH, ci.HEIGHT), rgb)

    def test_palette_colors_map_exactly(self):
        for name, code, rgb in ci.PALETTE:
            for dither in (False, True):
                with self.subTest(name=name, dither=dither):
                    self.assertEqual(set(ci.quantize(self.solid(rgb), dither)), {code})

    def test_off_palette_colors_use_nearest(self):
        self.assertEqual(set(ci.quantize(self.solid((30, 30, 30)))), {0x00})
        self.assertEqual(set(ci.quantize(self.solid((230, 20, 10)))), {0xE0})

    def test_tinted_grays_stay_black_or_white(self):
        # Anti-aliased dark text on off-white paper; RGB distance picked yellow here.
        for rgb in ((128, 128, 126), (140, 138, 130), (110, 112, 120), (90, 90, 85)):
            with self.subTest(rgb=rgb):
                self.assertLessEqual(set(ci.quantize(self.solid(rgb))), {0x00, 0xFF})

    def test_output_only_contains_palette_codes(self):
        gradient = Image.linear_gradient("L").resize((ci.WIDTH, ci.HEIGHT)).convert("RGB")
        codes = set(ci.RGB_BY_CODE)
        self.assertLessEqual(set(ci.quantize(gradient, dither=True)), codes)
        self.assertLessEqual(set(ci.quantize(gradient, dither=False)), codes)


class Prepare(unittest.TestCase):
    def test_exact_rejects_wrong_size(self):
        with self.assertRaises(ValueError):
            ci.prepare(Image.new("RGB", (640, 480)))

    def test_fit_modes_produce_panel_size(self):
        for fit in ("contain", "cover"):
            with self.subTest(fit=fit):
                self.assertEqual(ci.prepare(Image.new("RGB", (1000, 1000)), fit).size, (800, 480))

    def test_contain_pads_with_background(self):
        image = ci.prepare(Image.new("RGB", (480, 480), (0, 0, 0)), "contain", background="red")
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(image.getpixel((400, 240)), (0, 0, 0))

    def test_rotate_portrait_design(self):
        portrait = Image.new("RGB", (480, 800), (255, 255, 255))
        portrait.putpixel((0, 0), (255, 0, 0))
        image = ci.prepare(portrait, rotate=90)
        self.assertEqual(image.size, (800, 480))
        # Clockwise: the top-left corner moves to the top-right.
        self.assertEqual(image.getpixel((799, 0)), (255, 0, 0))

    def test_transparency_uses_background(self):
        image = ci.prepare(Image.new("RGBA", (800, 480), (0, 0, 0, 0)), background="yellow")
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 0))


class Cli(unittest.TestCase):
    def test_encode_and_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "in.png"
            Image.new("RGB", (800, 480), (0, 0, 255)).save(src)
            ci.main(["encode", str(src), "-o", str(tmp / "out.h"),
                     "--preview", str(tmp / "p1.png"), "--name", "gToday"])
            text = (tmp / "out.h").read_text()
            self.assertIn("const unsigned char gToday[384000] = {", text)
            ci.main(["preview", str(tmp / "out.h"), "-o", str(tmp / "p2.png")])
            with Image.open(tmp / "p1.png") as a, Image.open(tmp / "p2.png") as b:
                self.assertEqual(a.tobytes(), b.tobytes())


if __name__ == "__main__":
    unittest.main()

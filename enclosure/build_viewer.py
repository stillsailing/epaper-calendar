#!/usr/bin/env python3
"""Build the 3D viewer for the enclosure model.

Exports every part of enclosure/calendar_frame.scad at its assembly position
as binary STL, embeds them (and a calendar page as the screen image) into
enclosure/viewer_template.html, and writes:

  enclosure/viewer.html                 self-contained page, open it in a browser
                                        (kept in the repo; rebuild after editing
                                        the model)
  .build/enclosure/viewer-fragment.html same page without the document
                                        skeleton, for hosts that add their own
  .build/enclosure/<part>.stl           printable parts (frame, plate, lid, foot)

Needs OpenSCAD on PATH (brew install --cask openscad@snapshot).
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAD = ROOT / "enclosure" / "calendar_frame.scad"
TEMPLATE = ROOT / "enclosure" / "viewer_template.html"
VIEWER = ROOT / "enclosure" / "viewer.html"
OUT = ROOT / ".build" / "enclosure"
VIEWER_PARTS = ["frame", "keypad", "panel", "plate", "boards", "lid", "foot"]
PRINTED_PARTS = ["frame", "plate", "lid", "foot"]
PLACEHOLDER = "/*@MODEL@*/null"


def find_openscad():
    for candidate in (shutil.which("openscad"), "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("OpenSCAD not found: brew install --cask openscad@snapshot")


def openscad(binary, out, defines, fmt=None):
    cmd = [binary]
    for name, value in defines.items():
        cmd += ["-D", f"{name}={value}"]
    if fmt:
        cmd += ["--export-format", fmt]
    cmd += ["-o", str(out), str(SCAD)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode or "WARNING" in result.stderr or "ERROR" in result.stderr:
        sys.exit(f"openscad failed for {defines}:\n{result.stderr}")


def read_params(binary, tmp):
    echo = tmp / "params.echo"
    openscad(binary, echo, {"part": '"foot"'})
    for line in echo.read_text().splitlines():
        if line.startswith("ECHO: viewer = "):
            return dict(json.loads(line.removeprefix("ECHO: viewer = ")))
    sys.exit("calendar_frame.scad did not echo the viewer parameters")


def default_page():
    pages = ROOT / ".build" / "pages"
    for name in (f"{date.today().isoformat()}.png", "fallback.png"):
        if (pages / name).exists():
            return pages / name
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--page", type=Path, help="PNG shown on the screen (default: today's page)")
    args = parser.parse_args(argv)

    binary = find_openscad()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        params = read_params(binary, tmp)
        parts = {}
        for part in VIEWER_PARTS:
            stl = tmp / f"{part}.stl"
            openscad(binary, stl, {"part": f'"{part}"', "placed": "true"}, fmt="binstl")
            parts[part] = base64.b64encode(stl.read_bytes()).decode()
        for part in PRINTED_PARTS:
            openscad(binary, OUT / f"{part}.stl", {"part": f'"{part}"'}, fmt="binstl")

    page = args.page or default_page()
    model = {
        "params": params,
        "parts": parts,
        "page": f"data:image/png;base64,{base64.b64encode(page.read_bytes()).decode()}" if page else None,
        "pageDate": page.stem if page and page.stem != "fallback" else None,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    template = TEMPLATE.read_text()
    if PLACEHOLDER not in template:
        sys.exit(f"{TEMPLATE} lacks the {PLACEHOLDER} placeholder")
    fragment = template.replace(PLACEHOLDER, json.dumps(model, separators=(",", ":")))
    (OUT / "viewer-fragment.html").write_text(fragment)
    VIEWER.write_text(
        '<!doctype html>\n<html lang="zh-CN">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + fragment)
    print(f"wrote {VIEWER.relative_to(ROOT)} ({VIEWER.stat().st_size / 1024:.0f} KB); "
          f"STLs in {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()

"""Extract the largest frame of a multi-resolution .ico as a 256x256 PNG.

Used by `make_deb.sh` for the Linux hicolor icon. Reading the checked-in
`packaging/cellsmith.ico` avoids a second source of truth for the artwork --
`packaging/make_icon.py` remains the only generator.

Usage:  python ico_to_png.py <in.ico> <out.png> [size]
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = 256


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    size = int(argv[3]) if len(argv) > 3 else TARGET

    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow is required to extract the icon. Run this with the "
              "CellSmithEnv interpreter (the makefile does), or "
              "`pip install pillow`.", file=sys.stderr)
        return 1

    if not src.is_file():
        print(f"ERROR: {src} not found", file=sys.stderr)
        return 1

    with Image.open(src) as im:
        # IcoImageFile exposes every embedded frame via `.ico.sizes()`; assigning
        # `.size` selects one, and `load()` decodes it. A non-ICO input just uses
        # its own single size.
        sizes = sorted(im.ico.sizes()) if hasattr(im, "ico") else [im.size]
        chosen = sizes[-1]
        if hasattr(im, "ico"):
            im.size = chosen
        im.load()
        out = im.convert("RGBA")
        if out.size != (size, size):
            out = out.resize((size, size), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        out.save(dst, "PNG", optimize=True)

    print(f"icon: {src.name} frame {chosen[0]}x{chosen[1]} -> "
          f"{size}x{size} {dst} ({dst.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Build WOFF2 subsets of MiSans VF split by unicode-range.

- latin: Basic Latin, Latin-1, punctuation, CJK punctuation, full-width forms
- common: GB2312 level-1 hanzi (3,755 common Chinese characters)
- ext:   everything else in the font (rare hanzi, extensions)

Each output is named with a content hash so it can be cached immutably.
Writes ``web/static/fonts/fonts.json`` with the produced file names.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_FILE = PROJECT_ROOT / "MiSans VF.ttf"
OUT_DIR = PROJECT_ROOT / "web" / "static" / "fonts"

LATIN_RANGES = (
    range(0x0000, 0x0100),   # Basic Latin + Latin-1
    range(0x2000, 0x2070),   # punctuation
    range(0x20A0, 0x20C0),   # currency
    range(0x2100, 0x2150),   # letterlike
    range(0x2190, 0x2200),   # arrows
    range(0x2200, 0x2300),   # math operators
    range(0x2500, 0x2580),   # box drawing
    range(0x3000, 0x3040),   # CJK punctuation
    range(0xFF00, 0xFFF0),   # full-width forms
)

LATIN_UNICODE_RANGES = (
    "U+0000-00FF",
    "U+2000-206F",
    "U+20A0-20BF",
    "U+2190-22FF",
    "U+3000-303F",
    "U+FF00-FFEF",
)


def gb2312_level1_chars() -> set[str]:
    """Common Chinese characters: GB2312 rows 16-55 (level 1)."""
    chars: set[str] = set()
    for high in range(0xB0, 0xD8):  # level-1 rows end at 0xD7
        for low in range(0xA1, 0xFF):
            try:
                chars.add(bytes([high, low]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return chars


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    return digest


def _write_subset(
    font: TTFont,
    unicodes: set[int],
    out_name: str,
) -> Path:
    options = subset.Options()
    options.flavor = "woff2"
    options.hinting = True
    options.desubroutinize = False
    options.layout_features = ["*"]
    options.name_IDs = [1, 2, 3, 4, 6]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=sorted(unicodes))
    subsetter.subset(font)
    out_path = OUT_DIR / out_name
    subset.save_font(font, str(out_path), options=options)
    return out_path


def main() -> int:
    if not FONT_FILE.exists():
        print(f"missing {FONT_FILE}", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    font = TTFont(str(FONT_FILE), fontNumber=0)
    try:
        cmap = font.getBestCmap()
        all_unicodes = set(cmap.keys())

        latin_unicodes: set[int] = set()
        for block in LATIN_RANGES:
            latin_unicodes.update(
                code for code in block if code in all_unicodes
            )

        common_chars = gb2312_level1_chars()
        common_unicodes = {ord(char) for char in common_chars}
        common_unicodes &= all_unicodes

        ext_unicodes = all_unicodes - latin_unicodes - common_unicodes

        produced: dict[str, dict[str, object]] = {}
        for name, unicodes, ranges in (
            ("MiSans-latin", latin_unicodes, LATIN_UNICODE_RANGES),
            ("MiSans-cjk-common", common_unicodes, ("U+4E00-9FFF",)),
            ("MiSans-cjk-ext", ext_unicodes, ("U+3400-4DBF", "U+4E00-9FFF")),
        ):
            out_path = _write_subset(font, unicodes, f"{name}.woff2")
            hashed_name = f"{name}.{_content_hash(out_path)}.woff2"
            final_path = OUT_DIR / hashed_name
            out_path.replace(final_path)
            produced[name] = {
                "file": hashed_name,
                "size_bytes": final_path.stat().st_size,
                "unicode_range": list(ranges),
            }
            print(
                f"{name:16s} {final_path.stat().st_size:>9,d} B  "
                f"glyphs={len(unicodes):,}"
            )
        (OUT_DIR / "fonts.json").write_text(
            json.dumps(produced, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    finally:
        font.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

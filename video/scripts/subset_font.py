"""Subset LXGW WenKai GB to the characters used by the video.

The full font is ~25 MB. The video only needs a few hundred glyphs, so this
keeps the public folder small and the render fast.
"""

from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public" / "fonts"
SOURCE = Path(
    os.environ.get(
        "LXGW_FONT",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Fonts"
        / "LXGWWenKaiGB-Regular.ttf",
    )
)
TARGET = PUBLIC / "LXGWWenKaiGB-Subset.ttf"
CHARS = ROOT / "out" / "font-chars.txt"

if not SOURCE.exists():
    raise SystemExit(
        f"LXGW WenKai GB not found at {SOURCE}. Set LXGW_FONT to the .ttf path."
    )

texts = []
for pattern in ("src/**/*.tsx", "src/**/*.ts", "SCRIPT.md"):
    for path in ROOT.glob(pattern):
        texts.append(path.read_text(encoding="utf-8"))

# Latin, punctuation, arrows and a few symbols used by code samples.
base = (
    "".join(chr(i) for i in range(32, 127))
    + "λ→⇒⊢≡·×′₀₁₂₃₄₅₆₇₈₉ⁿ"
    + "，。、；：！？（）【】《》“”‘’…—"
    + "αβγδεζηθικλμνξοπρστυφχψω"
    + "ΓΔΘΛΞΠΣΦΨΩ"
)
chars = set(base) | set("".join(texts))
CHARS.parent.mkdir(parents=True, exist_ok=True)
CHARS.write_text("".join(sorted(chars)), encoding="utf-8")

cmd = [
    sys.executable,
    "-m",
    "fontTools.subset",
    str(SOURCE),
    f"--text-file={CHARS}",
    f"--output-file={TARGET}",
    "--layout-features=*",
    "--no-hinting",
    "--desubroutinize",
]
subprocess.run(cmd, check=True)
print(f"{TARGET} {TARGET.stat().st_size} bytes")

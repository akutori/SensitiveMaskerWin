"""Generate assets/icon.ico (16/32/48/256 px) with a simple mask/shield glyph.

Dev-only tool; Pillow is a dev dependency only (see pyproject.toml
[project.optional-dependencies].dev), never imported at runtime by
cli/gui/masking_core.

Run: uv run python scripts/generate_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [16, 32, 48, 256]
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"

SHIELD_BLUE = (40, 90, 160, 255)
SHIELD_OUTLINE = (20, 45, 80, 255)
EYE_WHITE = (255, 255, 255, 230)


def _draw_shield(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size, size
    shield = [
        (w * 0.5, h * 0.05),
        (w * 0.90, h * 0.20),
        (w * 0.90, h * 0.55),
        (w * 0.5, h * 0.95),
        (w * 0.10, h * 0.55),
        (w * 0.10, h * 0.20),
    ]
    draw.polygon(shield, fill=SHIELD_BLUE, outline=SHIELD_OUTLINE)

    eye_w, eye_h = w * 0.14, h * 0.06
    draw.ellipse(
        [w * 0.30, h * 0.38, w * 0.30 + eye_w, h * 0.38 + eye_h], fill=EYE_WHITE
    )
    draw.ellipse(
        [w * 0.56, h * 0.38, w * 0.56 + eye_w, h * 0.38 + eye_h], fill=EYE_WHITE
    )
    return img


def generate_icon() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    base = _draw_shield(max(SIZES))
    base.save(OUTPUT_PATH, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Wrote {OUTPUT_PATH} with sizes {SIZES}")


if __name__ == "__main__":
    generate_icon()

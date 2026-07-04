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
SUPERSAMPLE = 4

SHIELD_BLUE_LIGHT = (52, 108, 186, 255)
SHIELD_BLUE_DARK = (28, 66, 128, 255)
SHIELD_OUTLINE = (14, 34, 66, 255)
MASK_SLIT = (235, 244, 255, 235)
MASK_SLIT_OUTLINE = (14, 34, 66, 200)


def _shield_points(w: float, h: float) -> list[tuple[float, float]]:
    return [
        (w * 0.5, h * 0.04),
        (w * 0.88, h * 0.19),
        (w * 0.88, h * 0.54),
        (w * 0.5, h * 0.96),
        (w * 0.12, h * 0.54),
        (w * 0.12, h * 0.19),
    ]


def _draw_shield(size: int) -> Image.Image:
    render_size = size * SUPERSAMPLE
    img = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w = h = render_size

    # Soft drop shadow, offset slightly down-right, for a bit of depth.
    shadow_offset = w * 0.02
    shadow = [(x + shadow_offset, y + shadow_offset) for x, y in _shield_points(w, h)]
    draw.polygon(shadow, fill=(0, 0, 0, 60))

    # Two-tone shield body: darker lower half gives a subtle gradient feel
    # without needing a real gradient fill.
    outline_width = max(1, round(w * 0.012))
    draw.polygon(_shield_points(w, h), fill=SHIELD_BLUE_LIGHT, outline=SHIELD_OUTLINE, width=outline_width)
    lower_half = [
        (w * 0.12, h * 0.50),
        (w * 0.88, h * 0.50),
        (w * 0.88, h * 0.54),
        (w * 0.5, h * 0.96),
        (w * 0.12, h * 0.54),
    ]
    draw.polygon(lower_half, fill=SHIELD_BLUE_DARK)
    draw.polygon(_shield_points(w, h), outline=SHIELD_OUTLINE, width=outline_width)

    # Mask-style eye slits: rounded rectangles instead of plain ellipses,
    # reading more like a mask than a face.
    slit_w, slit_h = w * 0.16, h * 0.065
    radius = slit_h / 2
    for slit_x in (w * 0.27, w * 0.57):
        box = [slit_x, h * 0.40, slit_x + slit_w, h * 0.40 + slit_h]
        draw.rounded_rectangle(box, radius=radius, fill=MASK_SLIT, outline=MASK_SLIT_OUTLINE, width=max(1, round(w * 0.006)))

    return img.resize((size, size), Image.LANCZOS)


def generate_icon() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Render once at the largest size (already supersampled+downsampled
    # for crisp edges) and let Pillow's ICO writer derive the smaller
    # frames from it -- Pillow's ICO plugin resizes from a single base
    # image rather than accepting independently pre-rendered frames.
    base = _draw_shield(max(SIZES))
    base.save(OUTPUT_PATH, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Wrote {OUTPUT_PATH} with sizes {SIZES}")


if __name__ == "__main__":
    generate_icon()

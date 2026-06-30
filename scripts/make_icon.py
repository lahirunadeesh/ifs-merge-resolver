"""
Generate app icons for IFS Merge Resolver.
Run: python3 scripts/make_icon.py
Produces: ui/static/icon.ico  (Windows)
          ui/static/icon.icns (macOS)
          ui/static/icon.png  (tray / fallback)
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "static")
os.makedirs(OUT_DIR, exist_ok=True)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # ── Background: dark rounded square ──────────────────────────────────────
    radius = s // 5
    bg_color = (13, 17, 23, 255)       # GitHub dark
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=bg_color)

    # ── Glowing circle ring (blue) ────────────────────────────────────────────
    ring_margin = s * 0.08
    ring_width  = max(2, s // 20)
    d.ellipse(
        [ring_margin, ring_margin, s - ring_margin, s - ring_margin],
        outline=(88, 166, 255, 200),
        width=ring_width,
    )

    # ── Git merge symbol (3 dots + 2 lines) ──────────────────────────────────
    cx = s / 2
    cy = s / 2
    dot_r   = max(2, s // 16)
    line_w  = max(1, s // 22)
    blue    = (88, 166, 255, 255)
    purple  = (188, 140, 255, 255)
    green   = (63, 185, 80, 255)

    # Three nodes: top-left (local), top-right (repo), bottom-center (merged)
    pad = s * 0.22
    n_local  = (cx - s * 0.18, cy - s * 0.16)
    n_repo   = (cx + s * 0.18, cy - s * 0.16)
    n_merged = (cx,            cy + s * 0.22)

    # Lines
    d.line([n_local,  n_merged], fill=blue,   width=line_w)
    d.line([n_repo,   n_merged], fill=purple, width=line_w)

    # Dots
    for pos, color in [(n_local, blue), (n_repo, purple), (n_merged, green)]:
        x, y = pos
        d.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=color)

    # ── "IFS" text ────────────────────────────────────────────────────────────
    font_size = max(8, s // 6)
    font = None
    for font_path in [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_path, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    text = "IFS"
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = font_size * len(text) * 0.6, font_size
    text_x = cx - tw / 2
    text_y = cy + s * 0.33
    d.text((text_x, text_y), text, font=font, fill=(230, 237, 243, 255))

    return img


# ── Generate sizes ────────────────────────────────────────────────────────────
sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
images = {sz: draw_icon(sz) for sz in sizes}

# PNG (tray icon + fallback)
png_path = os.path.join(OUT_DIR, "icon.png")
images[256].save(png_path)
print(f"Saved {png_path}")

# ICO (Windows) — multiple sizes embedded
ico_path = os.path.join(OUT_DIR, "icon.ico")
ico_images = [images[sz] for sz in [16, 32, 48, 64, 128, 256]]
ico_images[0].save(
    ico_path,
    format="ICO",
    sizes=[(sz, sz) for sz in [16, 32, 48, 64, 128, 256]],
    append_images=ico_images[1:],
)
print(f"Saved {ico_path}")

# ICNS (macOS) — use iconutil via PNG set
icns_dir = os.path.join(OUT_DIR, "icon.iconset")
os.makedirs(icns_dir, exist_ok=True)
icns_map = {
    16: "icon_16x16.png",       32:  "icon_16x16@2x.png",
    32: "icon_32x32.png",       64:  "icon_32x32@2x.png",
    128: "icon_128x128.png",    256: "icon_128x128@2x.png",
    256: "icon_256x256.png",    512: "icon_256x256@2x.png",
    512: "icon_512x512.png",    1024: "icon_512x512@2x.png",
}
for sz, name in icns_map.items():
    images[sz].save(os.path.join(icns_dir, name))

import subprocess
icns_path = os.path.join(OUT_DIR, "icon.icns")
result = subprocess.run(
    ["iconutil", "-c", "icns", icns_dir, "-o", icns_path],
    capture_output=True
)
if result.returncode == 0:
    print(f"Saved {icns_path}")
else:
    print("iconutil not available (non-Mac), skipping .icns")

print("Done!")

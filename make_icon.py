#!/usr/bin/env python3
# Eclipse Muster MCP
# Copyright © 2026 Cyan Eclipse Technologies LLC · cetech.ai
# Generate icon-512.png — brand §6: eclipse motif on navy (#0d1b2a),

"""Generate icon-512.png — brand §6: eclipse motif on navy (#0d1b2a),
one per-product glyph. Muster's glyph is the muster roll itself: a
register of person-rows, two rows linked by a merge arc, inside the
gradient eclipse ring. PIL only; deterministic."""
from PIL import Image, ImageDraw

S = 512
NAVY = (13, 27, 42, 255)
STOPS = [(15, 246, 247), (0, 212, 255), (123, 44, 191)]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def grad(t):
    return lerp(STOPS[0], STOPS[1], t * 2) if t < 0.5 else \
        lerp(STOPS[1], STOPS[2], (t - 0.5) * 2)


def main():
    img = Image.new("RGBA", (S, S), NAVY)
    d = ImageDraw.Draw(img)
    ring = [54, 54, 458, 458]
    for i in range(72):
        t = i / 72
        d.arc(ring, start=i * 5, end=i * 5 + 6, fill=grad(t), width=13)
    d.ellipse([126, 126, 386, 386], fill=NAVY)
    # The register: three person-rows (head dot + name line + id line).
    for i, y in enumerate((168, 246, 324)):
        d.ellipse([168, y, 204, y + 36], outline=grad(0.15 + 0.3 * i),
                  width=6)
        d.line([(224, y + 10), (330, y + 10)], fill=grad(0.3 + 0.2 * i),
               width=8)
        d.line([(224, y + 28), (292, y + 28)],
               fill=(160, 174, 192, 255), width=6)
    # Merge arc linking rows 1 and 2 (propose-only, drawn dashed by
    # short segments).
    for k in range(6):
        start = 200 + k * 12
        d.arc([330, 150, 402, 300], start=start, end=start + 7,
              fill=grad(0.8), width=6)
    img.save("icon-512.png")
    print("wrote icon-512.png", img.size, img.mode)


if __name__ == "__main__":
    main()

# Eclipse Muster MCP · © 2026 Cyan Eclipse Technologies LLC · cetech.ai

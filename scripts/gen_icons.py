"""生成 PWA / 任务栏图标（开发时运行，需要 Pillow）。

图形：深绿圆角底 + 朱红火漆印 + 挖空钥匙孔。
执行：python scripts/gen_icons.py
"""
import struct
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageOps
except ImportError:  # 仅生成图标时需要，不是运行时依赖
    raise SystemExit("生成图标需要 Pillow：pip install pillow")

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
SS = 4  # 超采样倍数

TILE_TOP = (32, 52, 39)
TILE_BOTTOM = (8, 13, 10)
SEAL_TOP = (211, 102, 75)
SEAL_BOTTOM = (160, 55, 38)
RIM = (122, 42, 29, 170)
INNER_RING = (255, 220, 205, 40)
HAIRLINE = (234, 228, 213, 28)


def vertical_gradient(size, top, bottom):
    gray = Image.linear_gradient("L").resize((size, size), Image.BILINEAR)
    return ImageOps.colorize(gray, black=top, white=bottom).convert("RGBA")


def rounded_mask(size, radius_ratio=0.225):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=255
    )
    return mask


def seal_mask(size):
    """火漆印形状：圆 - 钥匙孔。"""
    cx = cy = size / 2
    seal_r = size * 0.305
    circle = Image.new("L", (size, size), 0)
    ImageDraw.Draw(circle).ellipse(
        [cx - seal_r, cy - seal_r, cx + seal_r, cy + seal_r], fill=255
    )

    keyhole = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(keyhole)
    kr = size * 0.092
    kx = cx
    ky = cy - size * 0.035
    d.ellipse([kx - kr, ky - kr, kx + kr, ky + kr], fill=255)
    top_w = size * 0.082
    bot_w = size * 0.15
    stem_top = ky + kr * 0.35
    stem_bot = cy + size * 0.155
    d.polygon(
        [(kx - top_w / 2, stem_top), (kx + top_w / 2, stem_top),
         (kx + bot_w / 2, stem_bot), (kx - bot_w / 2, stem_bot)],
        fill=255,
    )
    d.ellipse(
        [kx - bot_w / 2, stem_bot - bot_w * 0.35, kx + bot_w / 2, stem_bot + bot_w * 0.35],
        fill=255,
    )
    return ImageChops.subtract(circle, keyhole), seal_r


def render(size, *, full_bleed=False, detail=True):
    """渲染一张 size×size 的 RGBA 图标。full_bleed 用于 maskable / iOS。"""
    px = size * SS
    tile = vertical_gradient(px, TILE_TOP, TILE_BOTTOM)
    if full_bleed:
        canvas = tile
    else:
        canvas = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        canvas.paste(tile, (0, 0), rounded_mask(px))

    # 火漆印（带钥匙孔镂空，露出底色）
    mask, seal_r = seal_mask(px)
    seal = vertical_gradient(px, SEAL_TOP, SEAL_BOTTOM)
    seal.putalpha(mask)
    canvas.alpha_composite(seal)

    cx = cy = px / 2
    if detail:
        # 印面压边 + 内圈，做出火漆章的层次
        edge = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        ed = ImageDraw.Draw(edge)
        ed.ellipse([cx - seal_r, cy - seal_r, cx + seal_r, cy + seal_r],
                   outline=RIM, width=max(1, int(px * 0.0035)))
        ring_r = seal_r * 0.86
        ed.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                   outline=INNER_RING, width=max(1, int(px * 0.0025)))
        canvas.alpha_composite(edge)

    if not full_bleed:
        # 圆角内发丝线，让图标在深色任务栏上仍有轮廓
        hair = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        inset = max(1, int(px * 0.008))
        ImageDraw.Draw(hair).rounded_rectangle(
            [inset, inset, px - 1 - inset, px - 1 - inset],
            radius=int(px * 0.215), outline=HAIRLINE, width=max(1, int(px * 0.0025)),
        )
        canvas.alpha_composite(hair)

    if SS > 1:
        canvas = canvas.resize((size, size), Image.LANCZOS)
    return canvas


def png_bytes(img):
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    frames = [(s, png_bytes(render(s, detail=s >= 64))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = b""
    for size, data in frames:
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    path.write_bytes(header + entries + b"".join(data for _, data in frames))


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    for size in (32, 192, 512):
        path = OUT / f"icon-{size}.png"
        render(size).save(path, optimize=True)
        print(f"written {path} ({path.stat().st_size} bytes)")

    render(180, full_bleed=True, detail=False).convert("RGB").save(OUT / "icon-180.png", optimize=True)
    print(f"written {OUT / 'icon-180.png'}")

    render(512, full_bleed=True).save(OUT / "icon-maskable-512.png", optimize=True)
    print(f"written {OUT / 'icon-maskable-512.png'}")

    write_ico(OUT / "icon.ico")
    print(f"written {OUT / 'icon.ico'}")


if __name__ == "__main__":
    main()

"""生成 PWA 图标（纯 Python PNG 写入，免 Pillow）。

绘制：圆角深色底 + 白色钥匙图形（圆环 + 齿柄）。
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"

BG = (15, 23, 42)       # #0f172a
FG = (56, 189, 248)     # #38bdf8 accent
WHITE = (236, 244, 255)


def rounded_square_mask(size: int, radius: int):
    mask = [[False] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            if dx >= radius or dy >= radius:
                inside = True
            else:
                rx, ry = radius - dx, radius - dy
                inside = rx * rx + ry * ry <= radius * radius
            mask[y][x] = inside
    return mask


def key_pixel(x: int, y: int, size: int):
    """返回该像素属于钥匙图形的哪种颜色；不属于返回 None。坐标归一到 0..1。"""
    u, v = (x + 0.5) / size, (y + 0.5) / size
    # 钥匙头：圆环中心 (0.38, 0.40) 外径 0.20 内径 0.11
    dx, dy = u - 0.38, v - 0.40
    d2 = dx * dx + dy * dy
    if 0.11**2 <= d2 <= 0.20**2:
        return WHITE
    # 柄：从圆心向右下到 (0.78, 0.72)，宽 0.07
    x1, y1, x2, y2 = 0.38, 0.40, 0.76, 0.70
    len2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
    t = max(0.0, min(1.0, ((u - x1) * (x2 - x1) + (v - y1) * (y2 - y1)) / len2))
    px, py = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
    dist2 = (u - px) ** 2 + (v - py) ** 2
    if dist2 <= 0.045**2:
        return WHITE
    # 齿：两颗向下的短齿
    for tx, ty1, ty2 in ((0.62, 0.66, 0.82), (0.72, 0.72, 0.88)):
        if abs(u - tx) <= 0.03 and ty1 <= v <= ty2:
            return WHITE
    return None


def render(size: int) -> bytes:
    radius = size // 5
    mask = rounded_square_mask(size, radius)
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            if not mask[y][x]:
                row += b"\x00\x00\x00\x00"
                continue
            glyph = key_pixel(x, y, size)
            color = glyph or BG
            row += bytes(color) + b"\xff"
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def make_ico(png_bytes: bytes, size: int) -> bytes:
    # ICO 容器：6 字节头 + 1 个 16 字节目录项 + PNG 数据（Vista+ 支持 PNG 编码项）
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png_bytes), 22)
    return header + entry + png_bytes


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        path = OUT / f"icon-{size}.png"
        path.write_bytes(render(size))
        print(f"written {path} ({path.stat().st_size} bytes)")
    ico_path = OUT / "icon.ico"
    ico_path.write_bytes(make_ico(render(256), 256))
    print(f"written {ico_path} ({ico_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

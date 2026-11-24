"""デスクトップ版のアイコンを作る(標準ライブラリだけ。PNG は zlib で、ICO は PNG を包む)。

    python scripts/make_desktop_icon.py      → src-tauri/icons/ に 32x32.png / 128x128.png / icon.png / icon.ico

絵は「棒グラフ3本」。ライン別の棒(青・橙・緑)を紺の角丸に置く。
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src-tauri" / "icons"
NAVY = (24, 33, 47, 255)
BARS = [((47, 111, 214, 255), 0.55), ((217, 121, 43, 255), 0.80), ((46, 154, 91, 255), 0.40)]


def pixels(size: int) -> list[list[tuple]]:
    img = [[(0, 0, 0, 0)] * size for _ in range(size)]
    r = size * 0.18
    for y in range(size):
        for x in range(size):
            dx = max(r - x, 0, x - (size - 1 - r))
            dy = max(r - y, 0, y - (size - 1 - r))
            if dx * dx + dy * dy <= r * r:
                img[y][x] = NAVY
    pad, gap = size * 0.2, size * 0.06
    width = (size - 2 * pad - 2 * gap) / 3
    base = size - pad
    for i, (color, h) in enumerate(BARS):
        x0 = pad + i * (width + gap)
        top = base - (size - 2 * pad) * h
        for y in range(int(top), int(base)):
            for x in range(int(x0), int(x0 + width)):
                img[y][x] = color
    return img


def png(size: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in pixels(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, blob in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    return head + entries + data


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    blobs = {s: png(s) for s in (16, 32, 48, 128, 256)}
    (OUT / "32x32.png").write_bytes(blobs[32])
    (OUT / "128x128.png").write_bytes(blobs[128])
    (OUT / "icon.png").write_bytes(blobs[256])
    (OUT / "icon.ico").write_bytes(ico([(s, blobs[s]) for s in (16, 32, 48, 256)]))
    print(f"アイコンを作りました: {OUT}")


if __name__ == "__main__":
    main()

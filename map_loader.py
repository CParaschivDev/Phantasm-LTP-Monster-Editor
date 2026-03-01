"""Simple, dependency-free loaders for MU map assets (.ozt, .att).

This module provides a best-effort loader that detects a raw tile buffer
at the end of common MU map files and returns a simple dict with
width/height and `tiles` as a list-of-rows (integers 0-255).

The loader is intentionally conservative: it doesn't attempt to fully
implement every variant of the formats, but will work with the typical
server-side `.att` payloads and client `.ozt` used in this project
(where a trailing 65536-byte tile buffer is common).
"""
from __future__ import annotations
from pathlib import Path
import math
from typing import Optional


def _try_extract_raw_tile_buffer(b: bytes) -> Optional[dict]:
    # Try common square sizes (descending)
    sizes = [512*512, 256*256, 128*128]
    L = len(b)
    for size in sizes:
        if L >= size:
            # prefer if the file ends with a raw tile buffer of this size
            # allow small header (<=512 bytes) before the buffer
            for header_len in range(0, 513):
                if header_len + size == L:
                    side = int(math.sqrt(size))
                    if side * side == size:
                        offset = header_len
                        tiles = b[offset:offset+size]
                        rows = [list(tiles[i*side:(i+1)*side]) for i in range(side)]
                        return {'width': side, 'height': side, 'tiles': rows, 'offset': offset}
    # fallback: check for 2x uint16 width/height at start
    if L >= 4:
        w = int.from_bytes(b[0:2], 'little')
        h = int.from_bytes(b[2:4], 'little')
        if w > 0 and h > 0 and w*h <= L-4:
            raw = b[4:4+w*h]
            rows = [list(raw[i*w:(i+1)*w]) for i in range(h)]
            return {'width': w, 'height': h, 'tiles': rows, 'offset': 4}
    return None


def load_map(path: str) -> Optional[dict]:
    """Load a `.ozt` or `.att` map file.

    Returns a dict {width, height, tiles, offset} or None if not recognized.
    """
    p = Path(path)
    if not p.exists():
        return None
    b = p.read_bytes()
    # fast path: extract trailing raw buffer
    res = _try_extract_raw_tile_buffer(b)
    if res:
        res['path'] = str(p)
        return res
    # last resort: try interpreting entire file as raw square
    L = len(b)
    side = int(math.isqrt(L))
    if side*side == L:
        rows = [list(b[i*side:(i+1)*side]) for i in range(side)]
        return {'width': side, 'height': side, 'tiles': rows, 'offset': 0, 'path': str(p)}
    return None


if __name__ == '__main__':
    import sys
    for f in sys.argv[1:]:
        r = load_map(f)
        if r is None:
            print(f'{f}: unknown format or failed to parse')
        else:
            print(f"{f}: {r['width']}x{r['height']} offset={r.get('offset')}")

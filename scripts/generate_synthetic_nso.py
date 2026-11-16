#!/usr/bin/env python3
"""Generate a minimal synthetic NSO0 ARM64 fixture for native nx18 CI.

The bytes are original test data, not extracted Nintendo game code.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def generate(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    header = bytearray(0x100)
    header[:4] = b"NSO0"
    for index in range(3):
        struct.pack_into("<III", header, 0x10 + index * 16,
                         0x100 + index * 0x1000, index * 0x1000, 0x1000)
    text = bytearray(b"\x1f\x20\x03\xd5" * 1024)  # AArch64 NOP
    text[:4] = b"\xc0\x03\x5f\xd6"  # AArch64 RET
    struct.pack_into("<I", text, 4, 0x1000)
    text[0x20:0x24] = b"\xc0\x03\x5f\xd6"
    ro = bytearray(0x1000)
    ro[:4] = b"MOD0"
    struct.pack_into("<i", ro, 0x10, 0x40)
    ro[0x40:0x44] = bytes([1, 3, 3, 3])
    struct.pack_into("<IIII", ro, 0x44, 0x1100, 1, 0x20, 0x1100)
    result = folder / "main"
    result.write_bytes(header + text + ro + bytes(0x1000))
    if result.stat().st_size != 0x3100:
        raise RuntimeError("synthetic ARM64 NSO has incorrect segment size")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("exefs", type=Path)
    args = parser.parse_args()
    print("Synthetic NSO:", generate(args.exefs))

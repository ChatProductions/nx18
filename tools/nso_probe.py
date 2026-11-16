#!/usr/bin/env python3
"""Read-only Switch NSO0 preflight. Python 3.9+, no Apple tools, keys, or network."""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

HEADER_SIZE = 0x100
SEGMENTS = ("text", "rodata", "data")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_nso(path: Path) -> dict:
    size = path.stat().st_size
    if size < HEADER_SIZE:
        raise ValueError("file smaller than 0x100-byte NSO header")
    with path.open("rb") as handle:
        header = handle.read(HEADER_SIZE)
    if header[:4] != b"NSO0":
        raise ValueError("file does not begin with NSO0")
    flags = u32(header, 0x0C)
    sections = []
    for i, name in enumerate(SEGMENTS):
        off = 0x10 + 0x10 * i
        file_offset = u32(header, off)
        memory_offset = u32(header, off + 4)
        uncompressed = u32(header, off + 8)
        compressed = bool(flags & (1 << i))
        stored = u32(header, 0x60 + 4 * i) if compressed else uncompressed
        if stored > size or file_offset > size - stored:
            raise ValueError(f"{name} section exceeds file bounds")
        if stored and file_offset < HEADER_SIZE:
            raise ValueError(f"{name} section overlaps the NSO header")
        sections.append({
            "name": name,
            "file_offset": file_offset,
            "memory_offset": memory_offset,
            "stored_bytes": stored,
            "uncompressed_bytes": uncompressed,
            "compressed": compressed,
        })
    return {
        "filename": path.name,
        "format": "NSO0",
        "file_bytes": size,
        "module_id_hex": header[0x40:0x60].hex(),
        "flags_hex": f"0x{flags:08x}",
        "bss_bytes": u32(header, 0x3C),
        "segments": sections,
    }


def inspect_exefs(folder: Path) -> dict:
    if not folder.is_dir():
        raise ValueError("expected an extracted ExeFS directory")
    candidates = sorted(
        (p for p in folder.iterdir()
         if p.is_file() and (p.name in {"main", "rtld", "sdk"}
                             or p.name.startswith("subsdk"))),
        key=lambda p: p.name,
    )
    modules, errors = [], []
    for path in candidates:
        try:
            modules.append(parse_nso(path))
        except (OSError, ValueError) as exc:
            errors.append({"file": path.name, "problem": str(exc)})
    return {
        "purpose": "Read-only Switch NSO static-recompilation preflight",
        "location": str(folder),
        "modules": modules,
        "errors": errors,
        "ready_for_rewriter": bool(modules) and not errors,
        "execution_or_gameplay_verified": False,
        "notes": [
            "Validates NSO0 headers and file ranges, not game compatibility.",
            "Does not decrypt, rewrite, load, or execute any game.",
            "No Apple Developer tools, Nintendo keys, or network needed.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exefs", type=Path, help="Extracted ExeFS directory (not encrypted NSP)")
    parser.add_argument("-o", "--output", type=Path, help="Save JSON report")
    args = parser.parse_args(argv)
    try:
        report = inspect_exefs(args.exefs)
    except (OSError, ValueError) as exc:
        print(f"nx18 NSO preflight: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if report["ready_for_rewriter"] else 1


if __name__ == "__main__":
    sys.exit(main())

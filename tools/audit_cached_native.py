#!/usr/bin/env python3
"""Read-only nx18 audit of a previously extracted/recompiled Switch game.

Use existing nxnative/ns2ios cache on a Windows PC. Scans only small headers,
TSV metadata, and ZIP directory entries; never reads full RomFS contents,
decrypts a game, copies game binaries, or uploads anything.

This does NOT claim two different nxnative shader/rewriter versions are
ABI-compatible. An incompatible Metal shader chain must be rebuilt properly.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

from game_targets import resolve_target
from nso_probe import parse_nso

BUILD_V196608 = {
    "main": "2a5afa507f906ab09ad623dfe7f18862",
    "rtld": "2cf5725b70d9684ea3ce2ee7526c3b84",
    "sdk": "d83a56a5558798414c78ec722867a7da",
    "subsdk0": "e2970aa61f198ea32fbb247932d90406",
}
GATES = {"cntpct", "cntvct", "obs", "spin", "svc"}
CHAIN_PATTERN = re.compile(r'^#define DMSH_CHAIN "([a-f0-9]+)"$', re.M)
SHADER_PATTERN = re.compile(r"b-([0-9a-f]{10,20})(?:\.img)?$")


def short_metadata(path: Path, limit: int = 1 << 16) -> str:
    with path.open("rb") as stream:
        return stream.read(limit).decode("utf-8", "replace")


def read_macho_header(stream) -> dict:
    # Only the first header page is consumed. Native app + Guest may be
    # hundreds of MB; there is no need to load the full Mach-O into RAM.
    head = stream.read(16 * 1024)
    if len(head) < 32:
        return {"format": "missing-or-short"}
    magic, cpu, subtype, filetype, ncmds, cmdbytes, flags, res = struct.unpack_from(
        "<IiiIIIII", head, 0)
    if magic != 0xFEEDFACF or cpu != 0x0100000C:
        return {"format": "not-arm64-macho"}
    if 32 + cmdbytes > len(head):
        return {"format": "arm64-macho", "deployment": "unreadable"}
    pos = 32
    for _ in range(ncmds):
        if pos + 8 > 32 + cmdbytes:
            break
        op, length = struct.unpack_from("<II", head, pos)
        if length < 8 or pos + length > 32 + cmdbytes:
            break
        if op == 0x32 and length >= 24:
            platform, minos = struct.unpack_from("<II", head, pos + 8)
            return {
                "format": "arm64-macho",
                "kind": "app" if filetype == 2 else "framework" if filetype == 6 else str(filetype),
                "ios_platform": platform == 2,
                "min_ios": f"{minos >> 16}.{(minos >> 8) & 255}.{minos & 255}",
            }
        pos += length
    return {"format": "arm64-macho", "deployment": "unknown"}


def audit_ipa(path: Path) -> dict:
    with zipfile.ZipFile(path, "r") as archive:
        found = {}
        for info in archive.infolist():
            rel = info.filename
            if re.fullmatch(r"Payload/[^/]+\.app/[^/]+", rel) and not rel.endswith(".plist"):
                # Confirm the format rather than relying on the executable name.
                with archive.open(info) as f:
                    details = read_macho_header(f)
                if details["format"] == "arm64-macho":
                    found["host"] = dict(details, bytes=info.file_size)
            if re.fullmatch(r"Payload/[^/]+\.app/Frameworks/Guest.framework/Guest", rel):
                with archive.open(info) as f:
                    found["guest"] = dict(read_macho_header(f), bytes=info.file_size)
        return {
            "path": str(path),
            "archive_bytes": path.stat().st_size,
            "binaries": found,
            "compatible_with_iOS18": bool(found.get("host", {}).get("min_ios", "").startswith(
                ("16.", "17.", "18.")) and found.get("guest", {}).get("min_ios", "").startswith(
                ("16.", "17.", "18."))),
        }


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def audit(work: Path, *, target: str = "terminator",
          legacy_root: Path | None = None, ipa: Path | None = None) -> dict:
    work = work.resolve()
    if not work.is_dir():
        raise ValueError("work folder does not exist: " + str(work))
    t = resolve_target(target)
    scan = {
        "target": t.name,
        "title_id": t.title_id,
        "source": str(work),
        "exefs": [],
        "rewrite": [],
        "shader_images": [],
        "legacy_chain": None,
        "gameplay_verified": False,
        "can_reuse_existing_shader_image_with_Metal3": None,
    }
    # Real game source is never copied, hashed in full, or uploaded.
    for folder in work.rglob("ExeFS"):
        if not folder.is_dir():
            continue
        modules = []
        for name in ("main", "rtld", "subsdk0", "sdk", "subsdk1", "subsdk2"):
            path = folder / name
            if not path.is_file():
                continue
            try:
                entry = parse_nso(path)
            except (OSError, ValueError) as error:
                modules.append({"name": name, "error": str(error)})
                continue
            build_id = entry["module_id_hex"]
            expected = BUILD_V196608.get(name) if t.slug == "terminator2d" else None
            modules.append({
                "name": name,
                "build_id": build_id,
                "matches_known_v196608": build_id.startswith(expected) if expected else None,
                "stored_bytes": path.stat().st_size,
            })
        if modules:
            scan["exefs"].append({
                "folder": relative(folder, work),
                "modules": modules,
            })

    for path in work.rglob("main.fixups.tsv"):
        folder = path.parent
        mod_names = []
        gates = set()
        build_ids = {}
        for f in folder.glob("*.fixups.tsv"):
            mod_names.append(f.name[:-len(".fixups.tsv")])
            m = re.search(r"^# BUILD_ID\s+([0-9a-f]+)", short_metadata(f), re.M)
            if m: build_ids[f.name[:-len(".fixups.tsv")]] = m.group(1)
        for f in folder.glob("*.gates.tsv"):
            for line in short_metadata(f).splitlines():
                fields = line.split("\t")
                if len(fields) >= 2 and not line.startswith("#"):
                    gates.add(fields[1])
        scan["rewrite"].append({
            "folder": relative(folder, work),
            "modules": sorted(mod_names),
            "build_ids": build_ids,
            "gate_kinds": sorted(gates),
            "supported_gate_kinds": sorted(GATES),
            "unknown_gate_kinds": sorted(gates - GATES),
            "reuse_requires_host_ABI_verification": True,
        })

    # Look only at filenames/sizes of shader container images, not contents.
    for path in work.rglob("b-*.img"):
        match = SHADER_PATTERN.fullmatch(path.name)
        if match and path.is_file():
            scan["shader_images"].append({
                "path": relative(path, work),
                "chain": match.group(1),
                "bytes": path.stat().st_size,
            })
    if legacy_root is not None:
        head = legacy_root / "dm/gfx/nvn/legacy/dmsh_chain.h"
        if not head.is_file():
            raise ValueError("legacy Metal3 shader header is missing: " + str(head))
        m = CHAIN_PATTERN.search(head.read_text())
        if not m: raise ValueError("legacy shader-chain header is invalid")
        scan["legacy_chain"] = m.group(1)
        scan["can_reuse_existing_shader_image_with_Metal3"] = bool(
            scan["shader_images"] and all(
                image["chain"] == scan["legacy_chain"]
                for image in scan["shader_images"]))
    if ipa is not None:
        scan["existing_ipa"] = audit_ipa(ipa)
    scan["next_step"] = (
        "Reuse local ExeFS and rewriter inputs if compatible; do not relabel "
        "an iOS26 shader-chain image as Metal3. Compile the native host, "
        "then build chain-matched shaders and assemble a newly signed IPA."
    )
    return scan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True, type=Path,
                    help="Existing Switch game _pack folder on Windows")
    ap.add_argument("--target", default="terminator")
    ap.add_argument("--legacy-root", type=Path, help="Legacy nxnative checkout for shader ABI comparison")
    ap.add_argument("--ipa", type=Path, help="Optional previous game IPA (only ZIP directory and Mach-O headers scanned)")
    ap.add_argument("--out", type=Path, help="Local JSON output file (do not upload if paths are private)")
    args = ap.parse_args()
    try:
        result = audit(args.work, target=args.target,
                       legacy_root=args.legacy_root, ipa=args.ipa)
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print("[nx18] cache audit: " + str(error), file=sys.stderr)
        return 1
    output = json.dumps(result, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print("Local audit written:", args.out)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

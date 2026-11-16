#!/usr/bin/env python3
"""Build an iOS17 native Guest.framework from nx18-rewritten NSOs on Windows.

Requires the legacy nxnative tree AFTER LegacyShell/apply_legacy_shell.py.
Uses xinerqu/ns2ios-shell's existing compiler-free Mach-O generator, retargeted
to iOS17, never an emulator, JIT, or untrusted executable-memory workaround.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import plistlib
import re
import struct
from pathlib import Path

from game_targets import resolve_target, target_from_id
LC_BUILD_VERSION = 0x32
MH_DYLIB = 0x6
ARM64_CPU = 0x0100000C
MINOS_17 = 17 << 16


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def macho_minos(path: Path, expected_kind: int = MH_DYLIB) -> int:
    # Validate only the structural fields needed to reject iOS26 artifacts.
    with path.open("rb") as f:
        header = f.read(32)
        if len(header) != 32: raise ValueError("short Mach-O header")
        magic, cpu, _, kind, cmds, size, _, _ = struct.unpack("<IiiIIIII", header)
        if magic != 0xFEEDFACF or cpu != ARM64_CPU or kind != expected_kind:
            raise ValueError("not an iOS arm64 dynamic library")
        if size > 16384 - 32:
            raise ValueError("load commands exceed first 16KiB header page")
        commands = f.read(size)
    pos = 0
    for _ in range(cmds):
        if pos + 8 > len(commands): raise ValueError("truncated Mach-O load command")
        op, n = struct.unpack_from("<II", commands, pos)
        if n < 8 or pos + n > len(commands):
            raise ValueError("invalid Mach-O load command size")
        if op == LC_BUILD_VERSION:
            if n < 24: raise ValueError("truncated LC_BUILD_VERSION")
            platform, minos = struct.unpack_from("<II", commands, pos + 8)
            if platform != 2: raise ValueError("framework is not an iOS image")
            return minos
        pos += n
    raise ValueError("LC_BUILD_VERSION missing")


def write_guest(rewritten: Path, legacy: Path, out: Path,
                target_id: str | None = None) -> dict:
    rewritten, legacy, out = rewritten.resolve(), legacy.resolve(), out.resolve()
    metadata = rewritten / "rewrite-manifest.json"
    if not metadata.is_file():
        raise ValueError("missing rewrite-manifest.json: run rewrite_exefs.py first")
    data = json.loads(metadata.read_text(encoding="utf-8"))
    target = resolve_target(target_id) if target_id is not None else target_from_id(data["title_id"])
    if data.get("title_id") != target.title_id:
        raise ValueError("target ID does not match the rewritten modules")
    modules = data.get("modules", [])
    names = [m.get("name") for m in modules]
    if not names or "main" not in names or len(set(names)) != len(names):
        raise ValueError("missing or duplicated rewritten main module")
    if any(not re.fullmatch(r"(main|rtld|sdk|subsdk[0-9]+)", n) for n in names):
        raise ValueError("unrecognized module name")
    for module in modules:
        name = module["name"]
        for suffix, item in module.get("rewriter_outputs", {}).items():
            file = rewritten / (name + "." + suffix)
            if not file.is_file() or digest(file) != item.get("sha256"):
                raise ValueError("rewriter output hash mismatch: " + str(file))
        if not (rewritten / (name + ".patched.bin")).is_file():
            raise ValueError("missing native image: " + name)

    py = legacy / "dm/tools/guest_dylib.py"
    if not py.is_file():
        raise ValueError("missing patched guest_dylib.py (run apply_legacy_shell.py)")
    spec = importlib.util.spec_from_file_location("nx18_guest_writer", py)
    if spec is None or spec.loader is None:
        raise ValueError("cannot import upstream Mach-O generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.MIN_IOS != MINOS_17 or "MinimumOSVersion</key><string>17.0" not in module.INFO_PLIST:
        raise ValueError("guest generator is not retargeted to iOS17")

    out.mkdir(parents=True, exist_ok=True)
    framework, nbytes = module.write(str(rewritten), str(out), names,
                                     bundle_id=target.bundle_id + ".guest", name="Guest")
    library = Path(framework) / "Guest"
    plist = Path(framework) / "Info.plist"
    minos = macho_minos(library)
    with plist.open("rb") as f:
        plist_data = plistlib.load(f)
    if minos != MINOS_17 or plist_data.get("MinimumOSVersion") != "17.0":
        raise ValueError("generated guest framework targets the wrong iOS release")
    result = {
        "title_id": target.title_id,
        "target_name": target.name,
        "target_priority": target.priority,
        "guest_framework": str(framework),
        "modules": names,
        "image_bytes": nbytes,
        "image_sha256": digest(library),
        "minimum_ios": "17.0",
        "adhoc_signed_macho_generated": True,
        "embedded_in_ipa": False,
        "gameplay_verified": False,
    }
    (out / "guest18-manifest.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rewritten", required=True, type=Path)
    p.add_argument("--legacy", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--target", help="Optional target alias or 16-digit title ID; checked against rewrite manifest")
    a = p.parse_args()
    print(json.dumps(write_guest(a.rewritten, a.legacy, a.out, target_id=a.target), indent=2))


if __name__ == "__main__":
    main()

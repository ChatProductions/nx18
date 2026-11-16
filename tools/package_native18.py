#!/usr/bin/env python3
"""Stage a native Switch game's rewritten code/assets into nx18 Metal3 shell.

Local, offline Windows-compatible packer. Consumes results from real native
tools; does not emulate Switch hardware, decrypt an NSP, or compile game code.
Produces an UNSIGNED IPA that must be re-signed, including nested frameworks.
A packaged IPA is not evidence that a game boots on an iPhone.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

from build_guest18 import EXPECTED_TITLE, MINOS_17, macho_minos

TABLES = ("shader_map.tsv", "c1_full.tsv", "cb_extent.tsv",
          "shader_pairs.tsv", "pso_pairs.tsv", "pso_manifest.tsv")
GUEST_TABLE_ENDINGS = (".fixups.tsv", ".gates.tsv", ".cuts.tsv", ".obs.tsv")


def unpack_shell(archive: Path, root: Path) -> Path:
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            name = member.filename
            bits = Path(name).parts
            if bits == ("Payload",) and member.is_dir():
                continue
            if (not bits or bits[0] != "Payload" or
                len(bits) < 2 or bits[1] != "DmIOS.app" or
                any(b in ("", ".", "..") for b in bits) or
                name.startswith("/") or "\\" in name):
                raise ValueError("unsafe or unexpected game-free shell path: " + name)
            mode = member.external_attr >> 16
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise ValueError("symlink in unsigned shell archive")
            target = root.joinpath(*bits)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                if mode & 0o111: target.chmod(target.stat().st_mode | 0o755)
    app = root / "Payload" / "DmIOS.app"
    if not (app / "DmIOS").is_file() or not (app / "Info.plist").is_file():
        raise ValueError("game-free IPA has no DmIOS executable or Info.plist")
    return app


def parse_profile(path: Path) -> dict[str, str]:
    fields = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        part = line.split("\t", 1)
        if len(part) < 2: raise ValueError("invalid runtime game profile TSV")
        fields[part[0]] = part[1].strip()
    if fields.get("title_id", "").upper() != EXPECTED_TITLE:
        raise ValueError("runtime profile is not the Ezio Collection base title")
    for name in ("program_id", "modules", "romfs_marker", "mem_reserve",
                 "app_pool"):
        if not fields.get(name):
            raise ValueError("runtime profile is missing " + name)
    return fields


def chain_from_header(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^\s*#define\s+DMSH_CHAIN\s+"([A-Za-z0-9_-]+)"',
                      text, flags=re.MULTILINE)
    if not match: raise ValueError("no legacy DMSH_CHAIN in chain header")
    return match.group(1)


def package(shell: Path, guest: Path, rewritten: Path,
            profile: Path, shader_tables: Path, shaders: Path,
            legacy_chain_header: Path, output: Path,
            romfs: Path | None = None, control: Path | None = None) -> dict:
    for path in (shell, profile, legacy_chain_header):
        if not path.is_file(): raise ValueError("missing input " + str(path))
    if not guest.is_dir() or not rewritten.is_dir() or not shader_tables.is_dir():
        raise ValueError("missing native guest, rewritten modules or shader tables")
    fields = parse_profile(profile)
    if not (guest / "Guest").is_file():
        raise ValueError("Guest.framework is missing its native binary")
    if macho_minos(guest / "Guest") != MINOS_17:
        raise ValueError("Guest Mach-O does not target iOS 17")
    with (guest / "Info.plist").open("rb") as f:
        gp = plistlib.load(f)
    if gp.get("MinimumOSVersion") != "17.0":
        raise ValueError("Guest Info.plist is not iOS 17 compatible")

    rewrite_manifest = json.loads(
        (rewritten / "rewrite-manifest.json").read_text(encoding="utf-8"))
    if rewrite_manifest.get("title_id") != EXPECTED_TITLE:
        raise ValueError("rewritten modules have a different title ID")
    module_names = {x["name"] for x in rewrite_manifest["modules"]}
    if "main" not in module_names or not (module_names - {"rtld"}).issubset(
            set(fields["modules"].split())):
        raise ValueError("guest modules and runtime profile disagree")
    chain = chain_from_header(legacy_chain_header)
    if shaders.name != "b-" + chain or not shaders.is_dir():
        raise ValueError("shader directory does not match legacy Metal3 ABI chain")
    for required in ("shader_map.tsv", "c1_full.tsv"):
        if not (shader_tables / required).is_file():
            raise ValueError("missing shader table " + required)
    first = (shader_tables / "c1_full.tsv").open(encoding="utf-8").readline()
    if not first.startswith("# chain b-" + chain + " "):
        raise ValueError("shader tables are from a different translation chain")

    with tempfile.TemporaryDirectory(prefix="nx18-packing-") as directory:
        root = Path(directory)
        app = unpack_shell(shell, root)
        if macho_minos(app / "DmIOS", expected_kind=2) != MINOS_17:
            raise ValueError("game-free app was not compiled for iOS 17")
        if (app / "Frameworks").exists():
            raise ValueError("game-free shell unexpectedly contains frameworks")
        (app / "Frameworks").mkdir()
        shutil.copytree(guest, app / "Frameworks" / "Guest.framework")
        dm = app / "dm"
        dm.mkdir(exist_ok=True)
        shutil.copy2(profile, dm / "profile.tsv")
        if control:
            if not control.is_file(): raise ValueError("control.nacp missing")
            shutil.copy2(control, dm / "control.nacp")

        for path in rewritten.iterdir():
            if path.is_file() and path.name.endswith(GUEST_TABLE_ENDINGS):
                shutil.copy2(path, dm / path.name)
        for name in TABLES:
            source = shader_tables / name
            if source.is_file(): shutil.copy2(source, dm / name)
        msl_dest = app / "msl"
        msl_dest.mkdir(exist_ok=True)
        shutil.copytree(shaders, msl_dest / shaders.name)
        if romfs:
            if romfs.is_file():
                shutil.copy2(romfs, app / "romfs.img")
            elif romfs.is_dir():
                shutil.copytree(romfs, app / "romfs")
            else: raise ValueError("RomFS source not found")

        plist = app / "Info.plist"
        with plist.open("rb") as f: info = plistlib.load(f)
        info["CFBundleDisplayName"] = "Assassin's Creed II"
        info["CFBundleIdentifier"] = "org.nx18.ac2"
        with plist.open("wb") as f: plistlib.dump(info, f)

        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists(): raise ValueError("output already exists (will not overwrite)")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=4, allowZip64=True) as z:
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    z.write(file, file.relative_to(root).as_posix())

    return {"output": str(output), "title_id": EXPECTED_TITLE,
            "guest_modules": sorted(module_names), "legacy_chain": chain,
            "romfs_packed": romfs is not None,
            "unsigned": True, "full_resigning_required": True,
            "iPhone_13_gameplay_verified": False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("shell", "guest", "rewritten", "profile",
                 "shader-tables", "shaders", "legacy-chain-header", "output"):
        p.add_argument("--" + flag, required=True, type=Path)
    p.add_argument("--romfs", type=Path)
    p.add_argument("--control", type=Path)
    a = p.parse_args()
    args = vars(a)
    args["shader_tables"] = args.pop("shader_tables")
    args["legacy_chain_header"] = args.pop("legacy_chain_header")
    try:
        result = package(**args)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        print("[nx18] package refused: " + str(e), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

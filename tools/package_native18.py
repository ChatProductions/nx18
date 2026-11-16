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

from build_guest18 import MINOS_17, macho_minos, digest
from game_targets import resolve_target, target_from_id, title_id

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


def parse_profile(path: Path, expected_title: str | None = None) -> dict[str, str]:
    fields = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        part = line.split("\t", 1)
        if len(part) < 2: raise ValueError("invalid runtime game profile TSV")
        fields[part[0]] = part[1].strip()
    recorded = title_id(fields.get("title_id", ""))
    if expected_title and recorded != expected_title:
        raise ValueError("runtime profile title ID disagrees with the selected game")
    fields["title_id"] = recorded
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
            romfs: Path | None = None, control: Path | None = None,
            target_id: str | None = None) -> dict:
    for path in (shell, profile, legacy_chain_header):
        if not path.is_file(): raise ValueError("missing input " + str(path))
    if not guest.is_dir() or not rewritten.is_dir() or not shader_tables.is_dir():
        raise ValueError("missing native guest, rewritten modules or shader tables")
    rewrite_manifest = json.loads(
        (rewritten / "rewrite-manifest.json").read_text(encoding="utf-8"))
    target = resolve_target(target_id) if target_id is not None else target_from_id(rewrite_manifest["title_id"])
    if rewrite_manifest.get("title_id") != target.title_id:
        raise ValueError("selected game disagrees with the rewritten NSO manifest")
    fields = parse_profile(profile, expected_title=target.title_id)
    if not (guest / "Guest").is_file():
        raise ValueError("Guest.framework is missing its native binary")
    if macho_minos(guest / "Guest") != MINOS_17:
        raise ValueError("Guest Mach-O does not target iOS 17")
    with (guest / "Info.plist").open("rb") as f:
        gp = plistlib.load(f)
    if gp.get("MinimumOSVersion") != "17.0":
        raise ValueError("Guest Info.plist is not iOS 17 compatible")

    # Do not combine the code of one Switch game with another game's
    # framework: the Mach-O itself has no trustworthy embedded title field.
    guest_manifest_path = guest.parent / "guest18-manifest.json"
    if not guest_manifest_path.is_file():
        raise ValueError("missing guest18-manifest.json for native code provenance")
    guest_manifest = json.loads(guest_manifest_path.read_text(encoding="utf-8"))
    if guest_manifest.get("title_id") != target.title_id:
        raise ValueError("Guest.framework belongs to a different Switch title")
    if guest_manifest.get("image_sha256") != digest(guest / "Guest"):
        raise ValueError("Guest.framework binary does not match signed-code manifest")
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
        info["CFBundleDisplayName"] = target.name
        info["CFBundleIdentifier"] = target.bundle_id
        with plist.open("wb") as f: plistlib.dump(info, f)

        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists(): raise ValueError("output already exists (will not overwrite)")
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=4, allowZip64=True) as z:
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    z.write(file, file.relative_to(root).as_posix())

    return {"output": str(output), "title_id": target.title_id,
            "target_name": target.name, "target_priority": target.priority,
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
    p.add_argument("--target", help="Optional game alias/title ID; checked against all input manifests")
    a = p.parse_args()
    args = vars(a)
    args["target_id"] = args.pop("target")
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

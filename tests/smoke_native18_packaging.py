#!/usr/bin/env python3
"""Windows CI end-to-end assembler smoke with synthetic ARM64, not commercial ROMs.

Precondition: tools/rewrite_exefs.py ran the real upstream NSO rewriter,
and tools/build_guest18.py generated a real Apple-formatted Guest.framework.
The 'shell' in this test is a synthetic Mach-O scaffold, NOT a bootable app.
"""
from __future__ import annotations

import argparse
import io
import json
import plistlib
import re
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from package_native18 import package
from build_guest18 import macho_minos, MINOS_17


def synthetic_shell(path: Path) -> None:
    # Thin, valid-enough Mach-O header to exercise package version gating;
    # intentionally no UIKit code or game, NOT executable on an iPhone.
    macho = struct.pack("<IiiIIIII",
        0xfeedfacf, 0x0100000c, 0, 2, 1, 24, 0, 0)
    macho += struct.pack("<IIIIII", 0x32, 24, 2, MINOS_17, MINOS_17, 0)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("Payload/", b"")
        z.writestr("Payload/DmIOS.app/Info.plist",
            plistlib.dumps({
                "CFBundleIdentifier": "org.nx18.shell",
                "CFBundleDisplayName": "nx18 native shell smoke",
                "CFBundleExecutable": "DmIOS",
                "MinimumOSVersion": "17.0",
            }))
        z.writestr("Payload/DmIOS.app/DmIOS", macho)


def run(legacy: Path, rewritten: Path, native: Path) -> Path:
    head = (legacy / "dm/gfx/nvn/legacy/dmsh_chain.h")
    if not head.exists():
        raise RuntimeError("missing legacy Metal 3 shader-chain header")
    m = re.search(r'#define\s+DMSH_CHAIN\s+"([a-f0-9]+)"', head.read_text())
    if not m: raise RuntimeError("invalid legacy renderer shader-chain header")
    chain = m.group(1)
    manifest = json.loads((rewritten / "rewrite-manifest.json").read_text())
    tid = manifest["title_id"]
    with tempfile.TemporaryDirectory(prefix="nx18-synth-ipa-") as scratch:
        root = Path(scratch)
        shell = root / "shell-scaffold.ipa"
        synthetic_shell(shell)
        profile = root / "profile.tsv"
        profile.write_text(
            "title_id\t" + tid + "\n"
            "program_id\t" + tid + "\n"
            "name\tSynthetic Terminator test\n"
            "modules\tmain\n"
            "romfs_marker\tSystem/Resource\n"
            "mem_reserve\t0x100000000\n"
            "app_pool\t0xcd500000\n"
        )
        tables = root / "tables"
        tables.mkdir()
        (tables / "shader_map.tsv").write_text("# synthetic; no shaders\n")
        (tables / "c1_full.tsv").write_text(
            "# chain b-" + chain + " inputs synthetic fixture\n")
        shaders = root / ("b-" + chain)
        shaders.mkdir()
        (shaders / "inputs.tsv").write_text("game\t" + tid + "\n")
        out = root / "native18-synthetic-UNBOOTABLE.ipa"
        result = package(
            shell, native / "Guest.framework", rewritten,
            profile, tables, shaders, head, out
        )
        assert result["unsigned"] and not result["iPhone_13_gameplay_verified"]
        assert result["title_id"] == tid
        with zipfile.ZipFile(out) as z:
            members = set(z.namelist())
            assert "Payload/DmIOS.app/Frameworks/Guest.framework/Guest" in members
            assert "Payload/DmIOS.app/dm/profile.tsv" in members
            assert "Payload/DmIOS.app/dm/main.fixups.tsv" in members
            info = plistlib.loads(z.read("Payload/DmIOS.app/Info.plist"))
            assert info["CFBundleIdentifier"] == "org.nx18.game.t" + tid.lower()
            assert len(z.read("Payload/DmIOS.app/Frameworks/Guest.framework/Guest")) > 0
        print("PASS: synthetic title-matched native image, framework, tables, "
              "legacy shader-chain and IPA ZIP staging")
        print("NOTE: synthetic shell scaffold is not runnable, and this is "
              "NOT a working Terminator build.")
        return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--rewritten", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    a = parser.parse_args()
    run(a.legacy, a.rewritten, a.native)

"""Synthetic tests of reuse auditing; all data are tiny fixtures, never ROMs."""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from audit_cached_native import audit, audit_ipa, read_macho_header, BUILD_V196608


def minimal_nso(build_id: str) -> bytes:
    header = bytearray(0x100)
    header[:4] = b"NSO0"
    header[0x40:0x50] = bytes.fromhex(build_id)
    for i in range(3):
        struct.pack_into("<III", header, 0x10 + 16 * i,
                         0x100 + 0x20 * i, 0x2000 * i, 0x20)
    return bytes(header) + b"\x00" * 0x60


def macho(min_ios: int, kind: int) -> bytes:
    return (
        struct.pack("<IiiIIIII", 0xfeedfacf, 0x0100000c,
                    0, kind, 1, 24, 0, 0)
        + struct.pack("<IIIIII", 0x32, 24, 2, min_ios << 16,
                      min_ios << 16, 0)
    )


class CachedWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / "0100B51020B68000_pack"
        exefs = self.work / "extract/v196608.partial/ExeFS"
        exefs.mkdir(parents=True)
        (exefs / "main").write_bytes(minimal_nso(BUILD_V196608["main"]))
        (exefs / "sdk").write_bytes(minimal_nso(BUILD_V196608["sdk"]))
        rew = self.work / "build/rewritten"
        rew.mkdir(parents=True)
        (rew / "main.fixups.tsv").write_text(
            "# BUILD_ID\t" + BUILD_V196608["main"] + "\n"
            "# PATCH_OFF\t0x10000\n")
        (rew / "main.gates.tsv").write_text(
            "0x100\tspin\t0\t0x200\n"
            "0x120\tcustomgate\t1\t0x300\n")
        shader = self.work / "shader-cache/b-352884811607.img"
        shader.parent.mkdir(parents=True)
        shader.write_bytes(b"MTLB" * 4)
        self.legacy = self.root / "vendor/nxnative"
        header = self.legacy / "dm/gfx/nvn/legacy/dmsh_chain.h"
        header.parent.mkdir(parents=True)
        header.write_text('#define DMSH_CHAIN "c6c6ac82aed1"\n')

    def test_detect_previous_game_and_incompatible_shader_chain(self):
        result = audit(self.work, target="terminator", legacy_root=self.legacy)
        self.assertEqual(result["title_id"], "0100B51020B68000")
        mods = result["exefs"][0]["modules"]
        self.assertTrue(all(x["matches_known_v196608"] for x in mods))
        self.assertIn("customgate", result["rewrite"][0]["unknown_gate_kinds"])
        self.assertEqual(result["shader_images"][0]["chain"], "352884811607")
        self.assertEqual(result["legacy_chain"], "c6c6ac82aed1")
        self.assertFalse(result["can_reuse_existing_shader_image_with_Metal3"])
        self.assertFalse(result["gameplay_verified"])

    def test_missing_game_cache_fails(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            audit(self.root / "missing")

    def test_previous_ios26_ipa_is_rejected_for_ios18(self):
        ipa = self.root / "Terminator2D_old.ipa"
        with zipfile.ZipFile(ipa, "w") as z:
            z.writestr("Payload/DmIOS.app/DmIOS", macho(26, 2))
            z.writestr("Payload/DmIOS.app/Frameworks/Guest.framework/Guest",
                       macho(26, 6))
        record = audit_ipa(ipa)
        self.assertEqual(record["binaries"]["host"]["min_ios"], "26.0.0")
        self.assertEqual(record["binaries"]["guest"]["min_ios"], "26.0.0")
        self.assertFalse(record["compatible_with_iOS18"])

    def test_ios17_host_with_ios26_guest_is_incompatible(self):
        ipa = self.root / "mixed.ipa"
        with zipfile.ZipFile(ipa, "w") as z:
            z.writestr("Payload/DmIOS.app/DmIOS", macho(17, 2))
            z.writestr("Payload/DmIOS.app/Frameworks/Guest.framework/Guest",
                       macho(26, 6))
        self.assertFalse(audit_ipa(ipa)["compatible_with_iOS18"])

    def test_future_nfs_profile_is_not_assumed_terminator(self):
        result = audit(self.work, target="nfshp")
        self.assertEqual(result["title_id"], "010029B0118E8000")
        self.assertIsNone(result["exefs"][0]["modules"][0]["matches_known_v196608"])


if __name__ == "__main__":
    unittest.main()

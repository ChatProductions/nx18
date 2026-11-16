"""Prevent cross-game code/profile/framework combinations in the generic nx18 pipeline."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_guest18 import write_guest
from package_native18 import parse_profile, package
from game_targets import resolve_target


class TitleBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile.tsv"
        self.rewrite = self.root / "rewrite"
        self.rewrite.mkdir()
        self.guest = self.root / "Guest.framework"
        self.guest.mkdir()
        self.shell = self.root / "shell.ipa"
        self.shell.write_bytes(b"placeholder")
        self.chain = self.root / "dmsh_chain.h"
        self.chain.write_text('#define DMSH_CHAIN "legacy"\n')
        self.shader_tables = self.root / "tables"
        self.shader_tables.mkdir()
        self.shaders = self.root / "b-legacy"
        self.shaders.mkdir()

    def profile_for(self, tid):
        self.profile.write_text(
            "title_id\t" + tid + "\n"
            "program_id\t" + tid + "\n"
            "modules\tmain sdk\n"
            "romfs_marker\tSystem/Resource\n"
            "mem_reserve\t0x100000000\n"
            "app_pool\t0xcd500000\n",
            encoding="utf-8"
        )

    def write_manifest(self, tid):
        (self.rewrite / "rewrite-manifest.json").write_text(
            json.dumps({"title_id": tid, "modules": [{"name": "main"}]}))

    def test_terminator_profile(self):
        self.profile_for("0100B51020B68000")
        row = parse_profile(self.profile, expected_title="0100B51020B68000")
        self.assertEqual(row["title_id"], resolve_target("terminator").title_id)

    def test_profile_for_other_game_rejected(self):
        self.profile_for("0100670014482000")
        with self.assertRaisesRegex(ValueError, "disagrees"):
            parse_profile(self.profile, expected_title="0100B51020B68000")

    def test_guest_generation_rejects_wrong_game_before_writing(self):
        self.write_manifest("010029B0118E8000")
        with self.assertRaisesRegex(ValueError, "target ID does not match"):
            write_guest(self.rewrite, self.root / "vendor", self.root / "out",
                        target_id="terminator")
        self.assertFalse((self.root / "out").exists())

    def test_packager_rejects_mixed_game_before_binary_reads(self):
        self.write_manifest("0100B51020B68000")
        self.profile_for("0100670014482000")
        with self.assertRaisesRegex(ValueError, "disagrees"):
            package(self.shell, self.guest, self.rewrite, self.profile,
                    self.shader_tables, self.shaders, self.chain,
                    self.root / "result.ipa")
        self.assertFalse((self.root / "result.ipa").exists())

    def test_packager_rejects_wrong_explicit_title(self):
        self.write_manifest("0100B51020B68000")
        self.profile_for("0100B51020B68000")
        with self.assertRaisesRegex(ValueError, "selected game disagrees"):
            package(self.shell, self.guest, self.rewrite, self.profile,
                    self.shader_tables, self.shaders, self.chain,
                    self.root / "result.ipa", target_id="ac2")


if __name__ == "__main__":
    unittest.main()

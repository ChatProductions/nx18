"""Offline NX18 export -> ARM64 rewrite -> iOS17 Guest handoff tests.
No commercial game data, Nintendo keys, or Apple SDK involved.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from continue_native18 import validate_export, continue_native, main


def synthetic_nso() -> bytes:
    h = bytearray(0x100)
    h[:4] = b"NSO0"
    for k in range(3):
        struct.pack_into("<III", h, 0x10 + k * 0x10,
                         0x100 + k * 0x20, k * 0x2000, 0x20)
    return bytes(h) + (b"\x1f\x20\x03\xd5" * 24)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.exefs = self.base / "export"
        self.exefs.mkdir()
        self.upstream = self.base / "vendor" / "nxnative"
        self.work = self.base / "work"
        (self.exefs / "main").write_bytes(synthetic_nso())
        self.manifest = {
            "schema_version": 1,
            "stage": "decrypted-exefs",
            "title_id": "0100B51020B68000",
            "nca_file": "synthetic.nca",
            "files": [{
                "name": "main",
                "size_bytes": (self.exefs / "main").stat().st_size,
                "sha256": hashlib.sha256((self.exefs / "main").read_bytes()).hexdigest(),
            }],
            "keys_embedded": False,
            "gameplay_verified": False,
        }
        (self.exefs / "nx18-export.json").write_text(json.dumps(self.manifest))

    def test_sidecar_verifies_real_bytes_and_title_id(self):
        result = validate_export(self.exefs, None)
        self.assertEqual(result["title_id"], self.manifest["title_id"])
        self.assertEqual(result["modules"], ["main"])
        self.assertTrue(result["export_manifest_verified"])

    def test_verify_only_writes_no_binary_or_work_dir(self):
        data = continue_native(self.exefs, self.upstream, self.work,
                               verify_only=True)
        self.assertEqual(data["stage"], "validated-decrypted-exefs")
        self.assertFalse(data["rewrite_performed"])
        self.assertFalse(self.work.exists())

    def test_changes_after_export_are_rejected_before_rewriting(self):
        with (self.exefs / "main").open("ab") as f:
            f.write(b"tampered")
        with self.assertRaisesRegex(ValueError, "length|changed"):
            continue_native(self.exefs, self.upstream, self.work)
        self.assertFalse(self.work.exists())

    def test_wrong_title_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "disagrees"):
            continue_native(self.exefs, self.upstream, self.work,
                            selected_title="010029B0118E8000")

    def test_unlisted_nso_file_is_rejected(self):
        (self.exefs / "sdk").write_bytes(synthetic_nso())
        with self.assertRaisesRegex(ValueError, "unlisted executable"):
            validate_export(self.exefs, None)

    def test_unsafe_manifest_file_path_is_rejected(self):
        self.manifest["files"][0]["name"] = "../main"
        (self.exefs / "nx18-export.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            validate_export(self.exefs, None)

    def test_older_exefs_requires_explicit_title(self):
        (self.exefs / "nx18-export.json").unlink()
        with self.assertRaisesRegex(ValueError, "--title-id"):
            validate_export(self.exefs, None)
        self.assertFalse(validate_export(self.exefs, "0100B51020B68000")
                         ["export_manifest_verified"])

    def test_refuses_build_output_inside_source_or_vendor(self):
        for destination in (self.exefs / "build", self.exefs.parent,
                            self.upstream / "build"):
            with self.assertRaisesRegex(ValueError, "output"):
                continue_native(self.exefs, self.upstream, destination)
        self.assertFalse((self.exefs / "build").exists())

    def test_invokes_real_pipeline_wrappers_as_one_stage(self):
        observed = []

        def rewrite(exefs, upstream, output, *, title_id, jobs):
            observed.append(("rewrite", str(exefs), title_id, jobs))
            output.mkdir(parents=True, exist_ok=True)
            (output / "rewrite-manifest.json").write_text("{}")
            return {"modules": [{"name": "main"}]}

        def guest(rewrite_dir, upstream, native, *, target_id):
            observed.append(("guest", str(rewrite_dir), target_id))
            f = native / "Guest.framework"
            f.mkdir(parents=True)
            (f / "Guest").write_bytes(b"synthetic output, never signed")
            (native / "guest18-manifest.json").write_text("{}")
            return {"guest_framework": str(f)}

        with patch("continue_native18.run_rewrite", side_effect=rewrite), \
             patch("continue_native18.write_guest", side_effect=guest):
            result = continue_native(self.exefs, self.upstream, self.work,
                                     selected_title="0100B51020B68000", jobs=2)
        self.assertEqual([x[0] for x in observed], ["rewrite", "guest"])
        self.assertEqual(observed[0][2], self.manifest["title_id"])
        self.assertEqual(observed[1][2], self.manifest["title_id"])
        self.assertTrue(result["rewrite_completed"])
        self.assertTrue(result["guest_built"])
        self.assertFalse(result["ipa_packaged"])
        self.assertFalse(result["iPhone_gameplay_verified"])
        report = json.loads((self.work / "pipeline-report.json").read_text())
        self.assertEqual(report["stage"], "rewritten-arm64-and-ios17-guest")

    def test_cli_verify_only(self):
        self.assertEqual(main([str(self.exefs), "--verify-only"]), 0)
        self.assertFalse(self.work.exists())

    def test_rejects_rewriting_existing_output(self):
        (self.work / "rewrite").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "previous rewrite"):
            continue_native(self.exefs, self.upstream, self.work)


if __name__ == "__main__":
    unittest.main()

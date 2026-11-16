"""The wrapper actually invokes a rewriter (stubbed here), and validates its files."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rewrite_exefs import run_rewrite, checked_upstream


def nso_fixture():
    h = bytearray(0x100)
    h[:4] = b"NSO0"
    for i in range(3):
        struct.pack_into("<III", h, 0x10 + i * 16, 0x100 + i * 0x20,
                         i * 0x2000, 0x20)
    return bytes(h) + b"\x1f\x20\x03\xd5" * 24  # ARM64 NOP words (synthetic only)


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exe = self.root / "ExeFS"
        self.exe.mkdir()
        (self.exe / "main").write_bytes(nso_fixture())
        self.upstream = self.root / "nxnative"
        (self.upstream / "dm" / "tools").mkdir(parents=True)
        for fn in ("patch_nso.py", "nso.py", "nso_asm.py"):
            (self.upstream / "dm" / "tools" / fn).write_text("# placeholder\n")
        self.output = self.root / "rewritten"
        self.calls = []

    def fake_rewriter(self, argv, *, cwd, env, check):
        self.calls.append((argv, cwd, env["DM_GAME"], env["DM_REWRITE_J"]))
        assert check is True
        out = Path(argv[3])
        name = argv[4]
        for suffix in ("patched.bin", "fixups.tsv", "gates.tsv"):
            (out / f"{name}.{suffix}").write_bytes(b"fixture")

    def test_native_rewriter_invoked_and_manifest_written(self):
        result = run_rewrite(self.exe, self.upstream, self.output,
                             title_id="0100670014482000",
                             runner=self.fake_rewriter)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][0][1].endswith("patch_nso.py"))
        self.assertEqual(self.calls[0][2], "0100670014482000")
        self.assertEqual(result["modules"][0]["name"], "main")
        self.assertTrue((self.output / "main.patched.bin").exists())
        mf = json.loads((self.output / "rewrite-manifest.json").read_text())
        self.assertEqual(mf["host_or_ipa_built"], False)
        self.assertIn("sha256", mf["modules"][0]["rewriter_outputs"]["patched.bin"])

    def test_missing_output_fails_closed(self):
        def missing(argv, **kwargs):
            out = Path(argv[3])
            (out / "main.patched.bin").write_bytes(b"nonempty")

        with self.assertRaisesRegex(RuntimeError, "expected"):
            run_rewrite(self.exe, self.upstream, self.output,
                        title_id="0100670014482000", runner=missing)
        self.assertFalse((self.output / "rewrite-manifest.json").exists())

    def test_invalid_title_refused(self):
        with self.assertRaisesRegex(ValueError, "title ID"):
            run_rewrite(self.exe, self.upstream, self.output, title_id="../secret",
                        runner=self.fake_rewriter)
        self.assertFalse(self.calls)

    def test_missing_main_refused(self):
        (self.exe / "main").unlink()
        (self.exe / "rtld").write_bytes(nso_fixture())
        with self.assertRaisesRegex(ValueError, "main module"):
            run_rewrite(self.exe, self.upstream, self.output, title_id="0100670014482000",
                        runner=self.fake_rewriter)

    def test_requires_real_upstream_paths(self):
        (self.upstream / "dm" / "tools" / "patch_nso.py").unlink()
        with self.assertRaisesRegex(ValueError, "compatible nxnative checkout"):
            checked_upstream(self.upstream)

    def test_disallow_writing_over_input(self):
        with self.assertRaisesRegex(ValueError, "output must not overwrite"):
            run_rewrite(self.exe, self.upstream, self.exe,
                        title_id="0100670014482000", runner=self.fake_rewriter)


if __name__ == "__main__":
    unittest.main()

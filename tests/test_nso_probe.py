"""Synthetic NSO tests: no commercial game data."""
import struct
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from nso_probe import inspect_exefs, parse_nso


def fixture(compressed=False):
    header = bytearray(0x100)
    header[:4] = b"NSO0"
    if compressed:
        struct.pack_into("<I", header, 0x0C, 1)
    for i in range(3):
        struct.pack_into("<III", header, 0x10 + i * 0x10,
                         0x100 + i * 0x20, i * 0x2000,
                         0x40 if i == 0 else 0x20)
        struct.pack_into("<I", header, 0x60 + i * 4, 0x20)
    struct.pack_into("<I", header, 0x3C, 0x4000)
    return bytes(header) + b"\x42" * 0x60


class ProbeTests(unittest.TestCase):
    def test_valid_nso(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "main"
            p.write_bytes(fixture())
            result = parse_nso(p)
            self.assertEqual(result["bss_bytes"], 0x4000)
            self.assertEqual(result["segments"][1]["stored_bytes"], 0x20)
            self.assertFalse(result["segments"][0]["compressed"])

    def test_compressed_nso(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "main"
            p.write_bytes(fixture(compressed=True))
            result = parse_nso(p)
            self.assertEqual(result["segments"][0]["stored_bytes"], 0x20)
            self.assertEqual(result["segments"][0]["uncompressed_bytes"], 0x40)

    def test_bad_bounds(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "main"
            blob = bytearray(fixture())
            struct.pack_into("<I", blob, 0x10, 0xFFFFFFF0)
            p.write_bytes(blob)
            with self.assertRaisesRegex(ValueError, "exceeds file bounds"):
                parse_nso(p)

    def test_directory(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            (folder / "main").write_bytes(fixture())
            (folder / "main.npdm").write_bytes(b"not an NSO")
            result = inspect_exefs(folder)
            self.assertEqual(len(result["modules"]), 1)
            self.assertTrue(result["ready_for_rewriter"])
            self.assertFalse(result["execution_or_gameplay_verified"])

    def test_reject_fake(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            (folder / "main").write_bytes(b"bad")
            result = inspect_exefs(folder)
            self.assertEqual(len(result["errors"]), 1)
            self.assertFalse(result["ready_for_rewriter"])


if __name__ == "__main__":
    unittest.main()

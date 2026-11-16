"""nx18 title selection must never silently substitute Assassin's Creed II."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from game_targets import resolve_target, target_from_id, TARGETS


class GameTargetTests(unittest.TestCase):
    def test_terminator_first(self):
        t = resolve_target("terminator")
        self.assertEqual(t.title_id, "0100B51020B68000")
        self.assertEqual(t.priority, "first-test")
        self.assertEqual(t.bundle_id, "org.nx18.game.t0100b51020b68000")

    def test_nfs_fallback(self):
        self.assertEqual(resolve_target("nfshp").title_id, "010029B0118E8000")

    def test_ac2_deferred(self):
        self.assertEqual(resolve_target("ac2").priority, "long-term")

    def test_all_ids_distinct(self):
        self.assertEqual(len({t.title_id for t in TARGETS}), 3)

    def test_custom_game_id(self):
        t = resolve_target("0abcD12345678900")
        self.assertEqual(t.title_id, "0ABCD12345678900")
        self.assertEqual(t.compatibility, "unverified")
        self.assertEqual(target_from_id(t.title_id), t)

    def test_invalid_id_is_rejected(self):
        for invalid in ("", "ac3", "../keys", "0x0100B51020B68000", "0100B51020B6800g"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    resolve_target(invalid)


if __name__ == "__main__":
    unittest.main()

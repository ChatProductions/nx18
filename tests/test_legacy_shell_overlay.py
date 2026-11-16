"""Synthetic upstream layouts exercise the native iOS17 Metal3 shell overlay.
No commercial game files, keys, or Apple SDK needed.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LegacyShell"))
from apply_legacy_shell import apply, NEUTRAL


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.legacy = self.root / "legacy"
        self.shell = self.root / "shell"
        self.main = self.legacy / "dm/ios/Sources/main.m"
        self._write(self.main, '''
static char *g_argv[4]; static int g_argc;
    front_hud_env();
    g_argv[0] = strdup("dmhost"); g_argv[1] = strdup(dm.fileSystemRepresentation); g_argc = 2;
    dm_host_preload_start(g_argc, g_argv);
''')
        self._write(self.legacy / "dm/host/loader_legacy.inc",
                    "int dm_set_game_image_header(const void *header) { return 1; }\n")
        self._write(self.legacy / "dm/gfx/nvn/nvn_mtl_legacy.inc",
                    "#ifdef DM_SHELL\nnewLibraryWithSource\n#endif\n")
        self._write(self.legacy / "dm/gfx/nvn/legacy/dmsh_chain.h",
                    '#define DMSH_CHAIN "c6c6ac82aed1"\n')
        self._write(self.legacy / "dm/ios/project.yml",
                    "deploymentTarget: DM_IOS_DEPLOYMENT_TARGET\n")
        self._write(self.shell / f"dm/games/{NEUTRAL}/game.tsv",
                    "title_id\t0000000000000000\nname\tShell\n")
        self._write(self.shell / f"dm/games/{NEUTRAL}/dmsh_chain.h",
                    '#define DMSH_CHAIN "000000000000"\n')
        self._write(self.shell / "dm/tools/guest_dylib.py",
                    'MIN_IOS = 26 << 16\n'
                    'INFO_PLIST = "<key>MinimumOSVersion</key><string>26.0</string>"\n')

    def _write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_backport_preserves_legacy_chain(self):
        result = apply(self.legacy, self.shell)
        self.assertEqual(result["iOS_minimum"], "17.0")
        self.assertEqual(result["renderer"], "legacy Metal 3")
        chain = (self.legacy / f"dm/games/{NEUTRAL}/dmsh_chain.h").read_text()
        self.assertIn('c6c6ac82aed1', chain)
        self.assertNotIn('000000000000', chain)
        main = self.main.read_text()
        self.assertIn('nx18_guest_prepare(nx18_names, 16)', main)
        self.assertIn('DM_PROFILE', main)
        self.assertLess(main.index('setenv("DM_PROFILE"'),
                        main.index('front_hud_env()'))
        self.assertLess(main.index('nx18_guest_prepare(nx18_names, 16)'),
                        main.index('dm_host_preload_start(g_argc, g_argv)'))
        guest = (self.legacy / "dm/tools/guest_dylib.py").read_text()
        self.assertIn('MIN_IOS = 17 << 16', guest)
        self.assertIn('<string>17.0</string>', guest)
        self.assertNotIn('26.0', guest)
        self.assertTrue((self.legacy / "dm/ios/Sources/NX18Guest.m").exists())

    def test_fail_closed_on_new_unrecognized_upstream(self):
        self.main.write_text("new API; source anchors changed\n")
        with self.assertRaisesRegex(RuntimeError, "expected one"):
            apply(self.legacy, self.shell)

    def test_refuse_missing_legacy_chain(self):
        (self.legacy / "dm/gfx/nvn/legacy/dmsh_chain.h").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing upstream"):
            apply(self.legacy, self.shell)

    def test_no_double_patch(self):
        apply(self.legacy, self.shell)
        with self.assertRaisesRegex(RuntimeError, "already patched"):
            apply(self.legacy, self.shell)


if __name__ == "__main__":
    unittest.main()

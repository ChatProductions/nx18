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
        self._write(self.legacy / "dm/ios/Sources/front_ios_legacy.inc",
                    "// Synthetic legacy UIKit host with no live settings.\n")
        self._write(self.legacy / "dm/ios/Sources/Launcher.swift",
                    'if #available(iOS 26.0, *) { button.buttonStyle(.glassProminent) } else { button.buttonStyle(.borderedProminent) }\n')
        # The real upstream tree has dm/tools; the synthetic test fixture must too.
        (self.legacy / "dm/tools").mkdir(parents=True, exist_ok=True)
        self._write(self.legacy / "dm/host/hle_jit.c",
                    """    if (e->plugin) {
        if (e->plugin->fini) ((void (*)(void))(e->plugin->base + e->plugin->fini))();
        nro_unload_alone(e->plugin);   // the loader's: under its locks, with its check of stacks borrowing the plugin's data
        munmap((void *)e->rx, e->rx_size);
    }   // a served image stays mapped in the layout
""")
        self._write(self.legacy / "dm/host/loader_legacy.inc",
                    "int dm_set_game_image_header(const void *header) { return 1; }\n")
        self._write(self.legacy / "dm/ios/Sources/DmGraphicsCapabilities.h",
                    '    if (@available(iOS 26.0, *)) {\n'
                    '        interpolation = [MTLFXFrameInterpolatorDescriptor supportsDevice:device];\n'
                    '        interpolation4 = [MTLFXFrameInterpolatorDescriptor supportsMetal4FX:device];\n'
                    '    }\n')
        self._write(self.legacy / "dm/ios/Sources/DmGamepad_legacy.inc",
                    """    if (@available(iOS 27.0, *)) { g_motion.deviceMotionBody = body; g_motion_body = YES; LOG("front end: the phone's motion comes in the pad view's frame (deviceMotionBody)"); }\n""")
        self._write(self.legacy / "dm/gfx/vk/hle_vk.m",
                    "        if (@available(iOS 26.0, tvOS 26.0, macOS 26.0, *)) "
                    "sd.lodBias = fminf(fmaxf(ci->mipLodBias, -15), 15);"
                    "   // Metal 26's sampler bias; the device reports maxSamplerLodBias 15\n")
        self._write(self.legacy / "dm/gfx/nvn/nvn_mtl.m",
                    '#include "legacy/nvn_mtl_legacy.inc"\n')
        self._write(self.legacy / "dm/gfx/nvn/legacy/nvn_mtl_legacy.inc",
                    "#ifdef DM_SHELL\nnewLibraryWithSource\n#endif\nstatic uint64_t g_pq_in;\n"
                    "static int present_encode(id<MTLCommandBuffer> cb, id<MTLTexture> src, id<MTLTexture> dst, const int crop[4]);\n"
                    + ("""double dw = dst.width, dh = dst.height, s = fmin(dw / cw, dh / ch);
MTLViewport vp = {floor((dw - cw * s) / 2), floor((dh - ch * s) / 2), round(cw * s), round(ch * s), 0, 1};
if (fabs((dw / dh) / ((double)cw / ch) - 1) < 0.01) vp = (MTLViewport){0, 0, dw, dh, 0, 1};
""" * 2))
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
        launcher = (self.legacy / "dm/ios/Sources/Launcher.swift").read_text()
        self.assertIn("button.buttonStyle(.borderedProminent)", launcher)
        self.assertNotIn(".glassProminent", launcher)
        metal3vk = (self.legacy / "dm/gfx/vk/hle_vk.m").read_text()
        self.assertNotIn("sd.lodBias", metal3vk)
        caps = (self.legacy / "dm/ios/Sources/DmGraphicsCapabilities.h").read_text()
        self.assertNotIn("MTLFXFrameInterpolatorDescriptor", caps)
        render = (self.legacy / "dm/gfx/nvn/legacy/nvn_mtl_legacy.inc").read_text()
        self.assertIn("void mtl_present_progress", render)
        self.assertIn("*queued = g_pq_in", render)
        self.assertIn("*done = g_pq_done", render)
        self.assertIn("pthread_mutex_lock(&g_pq_mu)", render)
        legacy_front = (self.legacy / "dm/ios/Sources/front_ios_legacy.inc").read_text()
        self.assertIn("bool dm_setting_live(const char *env, const char *value)", legacy_front)
        self.assertIn("return false;", legacy_front)
        self.assertIn("void mtl_present_layer(uint32_t w, uint32_t h)", render)
        self.assertIn("atomic_store_explicit(&g_nx18_vi_layer_wh", render)
        self.assertEqual(render.count("nx18_present_aspect(cw, ch"), 2)
        self.assertEqual(render.count("round(content_w * s)"), 2)
        self.assertNotIn("round(cw * s)", render)

        gamepad = (self.legacy / "dm/ios/Sources/DmGamepad_legacy.inc").read_text()
        self.assertNotIn("g_motion.deviceMotionBody = body", gamepad)
        jit = (self.legacy / "dm/host/hle_jit.c").read_text()
        self.assertIn("#if TARGET_OS_IPHONE", jit)
        self.assertIn("cannot unload JIT NRO plugins", jit)
        self.assertIn("#else", jit)
        self.assertIn("nro_unload_alone(e->plugin)", jit)





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

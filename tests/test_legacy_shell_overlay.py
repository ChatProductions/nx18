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
        self._write(self.legacy / "dm/ios/Sources/GameMenu.swift",
                    "items.append(Unmanaged<UIMenu>.fromOpaque(dm_quit_menu()).takeRetainedValue())\n")
        self._write(self.legacy / "dm/ios/Sources/front_ios_legacy.inc",
                    """const char *front_ios_boot_message(void);
- (void)viewDidLoad {
    front_ios_power_watch();
    if (!front_ios_boot_ok()) {   // No game files: show a hint and do not start the host
        return;
    }
}
- (void)viewDidAppear:(BOOL)a {
    [super viewDidAppear:a];
    if (!front_ios_boot_ok() && front_ios_boot_message() && !self.presentedViewController) {
        return;
    }
}
UIViewController *front_ios_root(void) {
    return [DmRootVC new];
}
""")
        self._write(self.legacy / "dm/ios/Sources/Launcher.swift",
                    'if #available(iOS 26.0, *) { button.buttonStyle(.glassProminent) } else { button.buttonStyle(.borderedProminent) }\n'
                    '    gameMenuModel = model   // the in-game menu shows and saves the same choices (GameMenu.swift)\n')
        # The real upstream tree has dm/tools; the synthetic test fixture must too.
        (self.legacy / "dm/tools").mkdir(parents=True, exist_ok=True)
        self._write(self.legacy / "dm/host/hle_jit.c",
                    """    const char *serve = dm_jit_serve_dir();
    if (e->plugin) {
        if (e->plugin->fini) ((void (*)(void))(e->plugin->base + e->plugin->fini))();
        nro_unload_alone(e->plugin);   // the loader's: under its locks, with its check of stacks borrowing the plugin's data
        munmap((void *)e->rx, e->rx_size);
    }   // a served image stays mapped in the layout
""")
        self._write(self.legacy / "dm/host/hle_hid.c",
                    '                if (!strcmp(line, "restop")) { void dm_gfx_restop(void); dm_gfx_restop(); continue; }'
                    '   // what the residency set holds (nvn_mtl.m res_top)\n'
                    '                    if (sscanf(line + 8, "%31s %llx %lli %511s", key, &a, &n, path) == 4) '
                    'dm_gfx_bufsnap(key, a, (size_t)n, path); '
                    'else LOG("DM_CTL: bufsnap <shader key> <hex address> <bytes> <path>"); continue; }\n')
        self._write(self.legacy / "dm/host/loader_legacy.inc",
                    "int dm_set_game_image_header(const void *header) { return 1; }\n"
                    "int dm_main_imports(const char *prefix) {\n    return 0;\n}\n")
        self._write(self.legacy / "dm/host/hle_lifecycle.c",
                    "#include <unistd.h>\n")
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
                    "deploymentTarget: DM_IOS_DEPLOYMENT_TARGET\n"
                    "        excludes: [Info.plist]\n")
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
        project_text = (self.legacy / "dm/ios/project.yml").read_text()
        self.assertIn("excludes: [Info.plist, GameMenu.swift]", project_text)

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
        self.assertNotIn("gameMenuModel = model", launcher)
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
        self.assertIn("nx18_show_nsp_studio((__bridge void *)self)", legacy_front)
        self.assertIn("nx18_make_nsp_studio_root()", legacy_front)
        self.assertIn("(__bridge_transfer UIViewController *)", legacy_front)
        self.assertLess(legacy_front.index("nx18_make_nsp_studio_root()"),
                        legacy_front.index("return [DmRootVC new];"))
        native_importer = (self.legacy / "dm/ios/Sources/NX18Import.swift").read_text()
        self.assertIn('UIHostingController(rootView: StudioView())', native_importer)
        self.assertIn('@_cdecl("nx18_make_nsp_studio_root")', native_importer)
        self.assertIn("if (!front_ios_boot_ok()) return;", legacy_front)
        sources = self.legacy / "dm/ios/Sources"
        view = (sources / "NX18StudioView.swift").read_text()
        self.assertIn("struct StudioView: View", view)
        self.assertNotIn("@main", view)
        self.assertIn("NSPInspector.inspect(url:", view)
        self.assertIn('NX18DocumentPicker.open(', view)
        self.assertIn('NSP-Inbox', view)
        self.assertIn('loadKeysFromInbox()', view)
        self.assertIn('refreshNSPInbox()', view)
        self.assertNotIn('.fileImporter(', view)
        native_picker = (sources / "NX18DocumentPicker.swift").read_text()
        self.assertIn("UIDocumentPickerViewController", native_picker)
        self.assertIn("func documentPicker(", native_picker)
        self.assertIn("UIApplication.shared.connectedScenes", native_picker)
        for filename in ("NX18Import.swift", "NX18NSPInspector.swift",
                         "NX18NSPExtractor.swift", "NX18NCAHeader.swift",
                         "NX18MetalProbe.swift", "NX18BCDecode.swift",
                         "NX18NCAPayload.swift", "NX18DocumentPicker.swift"):
            self.assertTrue((sources / filename).is_file(), filename)
        menu = (self.legacy / "dm/ios/Sources/GameMenu.swift").read_text()
        self.assertNotIn("dm_quit_menu()", menu)
        self.assertIn("modern quit prompt absent", menu)

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
        self.assertIn('die("nx18 iOS17: nn::jit requires offline signed-image integration")', jit)
        self.assertIn("serve = dm_jit_serve_dir();", jit)
        self.assertNotIn("const char *serve = dm_jit_serve_dir();", jit)
        hid = (self.legacy / "dm/host/hle_hid.c").read_text()
        self.assertIn("restop unavailable in the iOS17 Metal3 legacy renderer", hid)
        self.assertIn("#if TARGET_OS_IPHONE && !defined(DM_NVN_MODERN_RENDERER)", hid)
        self.assertIn("dm_gfx_restop();", hid)
        self.assertIn("bufsnap unavailable in the iOS17 Metal3 legacy renderer", hid)
        self.assertIn("#if TARGET_OS_IPHONE && !defined(DM_NVN_MODERN_RENDERER)", hid)
        self.assertIn("dm_gfx_bufsnap(key, a, (size_t)n, path);", hid)
        loader = (self.legacy / "dm/host/loader_legacy.inc").read_text()
        self.assertIn("int dm_game_imports(const char *prefix)", loader)
        self.assertIn('g_mod[i].nro || !strcmp(g_mod[i].name, "main")', loader)
        self.assertIn("m->symtab[k].st_shndx", loader)
        lifecycle = (self.legacy / "dm/host/hle_lifecycle.c").read_text()
        self.assertIn("void dm_gfx_quit_begin(void)", lifecycle)
        self.assertIn("void dm_gfx_quit(int budget_ms)", lifecycle)
        self.assertIn("nvn_cache_flush();", lifecycle)
        self.assertIn("dispatch_semaphore_wait", lifecycle)
        self.assertIn("#if TARGET_OS_IPHONE && !defined(DM_NVN_MODERN_RENDERER)", lifecycle)








    def test_fail_closed_on_new_unrecognized_upstream(self):
        self.main.write_text("new API; source anchors changed\n")
        with self.assertRaisesRegex(RuntimeError, "expected one"):
            apply(self.legacy, self.shell)

    def test_refuse_missing_legacy_chain(self):
        (self.legacy / "dm/gfx/nvn/legacy/dmsh_chain.h").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing upstream"):
            apply(self.legacy, self.shell)

    def test_upstream_import_scanner_is_not_duplicated(self):
        loader = self.legacy / "dm/host/loader_legacy.inc"
        scanner = """
int dm_game_imports(const char *prefix) {
    for (int i = 0; i < g_nmod; i++) if (g_mod[i].nro || !strcmp(g_mod[i].name, "main")) {
        module_t *m = &g_mod[i];
        if (!m->symtab[k].st_shndx) return 1;
    }
    return 0;
}
"""
        loader.write_text(loader.read_text() + scanner)
        apply(self.legacy, self.shell)
        self.assertEqual(loader.read_text().count("int dm_game_imports("), 1)

    def test_reject_incompatible_upstream_import_scanner(self):
        loader = self.legacy / "dm/host/loader_legacy.inc"
        loader.write_text(loader.read_text() +
                          "\nint dm_game_imports(const char *x) {\n    return 0;\n}\n")
        with self.assertRaisesRegex(RuntimeError, "semantics changed"):
            apply(self.legacy, self.shell)

    def test_upstream_classic_graphics_quit_is_not_duplicated(self):
        nvn = self.legacy / "dm/gfx/nvn/legacy/hle_nvn.c.inc"
        self._write(nvn, """void dm_gfx_quit_begin(void) {}
void dm_gfx_quit(int wait_ms) { if (wait_ms > 0) mtl_warm_wait(wait_ms); }
""")
        apply(self.legacy, self.shell)
        lifecycle = (self.legacy / "dm/host/hle_lifecycle.c").read_text()
        self.assertNotIn("void dm_gfx_quit_begin(", lifecycle)
        self.assertNotIn("void dm_gfx_quit(int budget_ms)", lifecycle)

    def test_upstream_present_progress_not_duplicated(self):
        renderer = self.legacy / "dm/gfx/nvn/legacy/nvn_mtl_legacy.inc"
        renderer.write_text(renderer.read_text() + """
void mtl_present_progress(uint64_t *queued, uint64_t *done) {
    pthread_mutex_lock(&g_pq_mu);
    *queued = g_pq_in;
    *done = g_pq_done;
    pthread_mutex_unlock(&g_pq_mu);
}
""")
        apply(self.legacy, self.shell)
        result = renderer.read_text()
        self.assertEqual(result.count("void mtl_present_progress("), 1)

    def test_reject_unrecognized_import_scanner(self):
        loader = self.legacy / "dm/host/loader_legacy.inc"
        loader.write_text(loader.read_text().replace(
            "int dm_main_imports(const char *prefix) {",
            "int renamed_main_imports(const char *prefix) {"))
        with self.assertRaisesRegex(RuntimeError, "main-import symbol scanner"):
            apply(self.legacy, self.shell)

    def test_reject_unrecognized_shutdown_abi(self):
        life = self.legacy / "dm/host/hle_lifecycle.c"
        life.write_text("modern-only graphics shutdown API\n")
        with self.assertRaisesRegex(RuntimeError, "shutdown ABI changed"):
            apply(self.legacy, self.shell)

    def test_reject_unrecognized_restop_command(self):
        hid = self.legacy / "dm/host/hle_hid.c"
        hid.write_text("new diagnostics command API\n")
        with self.assertRaisesRegex(RuntimeError, "restop handler changed"):
            apply(self.legacy, self.shell)

    def test_reject_unrecognized_jit_entry(self):
        jit = self.legacy / "dm/host/hle_jit.c"
        jit.write_text(jit.read_text().replace(
            "const char *serve = dm_jit_serve_dir();",
            "const char *serve = get_other_serve_dir();"))
        with self.assertRaisesRegex(RuntimeError, "nn::jit serve entry changed"):
            apply(self.legacy, self.shell)

    def test_no_double_patch(self):
        apply(self.legacy, self.shell)
        with self.assertRaisesRegex(RuntimeError, "already patched"):
            apply(self.legacy, self.shell)


if __name__ == "__main__":
    unittest.main()

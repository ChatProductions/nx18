#!/usr/bin/env python3
"""Backport game-free signed Guest.framework loading to the iOS17 Metal3 host.

Required inputs:
  --legacy  local checkout of widmonstertony/nxnative ios16-ios17-compat
  --shell   local checkout of xinerqu/ns2ios-shell
No game content or keys are read. This is a host-source integration step.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
NEUTRAL = "0000000000000000"


def replace_one(text: str, old: str, new: str, where: str) -> str:
    occurrences = text.count(old)
    if occurrences != 1:
        raise RuntimeError(f"{where}: expected one unmodified anchor, found {occurrences}")
    return text.replace(old, new, 1)


def apply(legacy: Path, shell: Path) -> dict:
    legacy, shell = legacy.resolve(), shell.resolve()
    main_file = legacy / "dm/ios/Sources/main.m"
    loader = legacy / "dm/host/loader_legacy.inc"
    renderer = legacy / "dm/gfx/nvn/legacy/nvn_mtl_legacy.inc"
    project = legacy / "dm/ios/project.yml"
    needed = (main_file, loader, renderer, project,
              shell / "dm/tools/guest_dylib.py",
              shell / f"dm/games/{NEUTRAL}/game.tsv",
              legacy / "dm/gfx/nvn/legacy/dmsh_chain.h")
    missing = [str(p) for p in needed if not p.is_file()]
    if missing:
        raise RuntimeError("missing upstream file(s): " + ", ".join(missing))
    # Fail before touching the XcodeGen project or any upstream file.
    # A second overlay application must not partially mutate a source tree.
    if "NX18_SHELL" in main_file.read_text(encoding="utf-8"):
        raise RuntimeError("already patched; use a fresh legacy checkout")
    if "int dm_set_game_image_header(const void *header)" not in loader.read_text(encoding="utf-8"):
        raise RuntimeError("legacy host is missing its external image setter")
    metal = renderer.read_text(encoding="utf-8")
    # nvn_mtl.m compiles legacy/nvn_mtl_legacy.inc on iOS, NOT the
    # similarly named top-level nvn_mtl_legacy.inc copy. Fixes must land
    # in the compiled source or an ARM64 linker error survives silently.
    wrapper = legacy / "dm/gfx/nvn/nvn_mtl.m"
    if not wrapper.is_file():
        raise RuntimeError("NVN renderer translation unit is missing")
    nvn_wrapper = wrapper.read_text(encoding="utf-8")
    if '#include "legacy/nvn_mtl_legacy.inc"' not in nvn_wrapper:
        raise RuntimeError("legacy Metal3 translation unit changed: inspect compiled include")

    if "newLibraryWithSource" not in metal or "#ifdef DM_SHELL" not in metal:
        raise RuntimeError("expected iOS17 on-device MSL compiler branch is missing")
    if "DM_IOS_DEPLOYMENT_TARGET" not in project.read_text(encoding="utf-8"):
        raise RuntimeError("legacy project cannot be retargeted to iOS17")
    # GameMenu.swift is used by the modern iOS26 controller frontend only.
    # The legacy iOS17 DmGamepad_legacy.inc and front_ios_legacy.inc never
    # call dm_game_menu. Compiling the modern menu forces unsupported
    # dm_pad_layout_set/dm_quit_menu into the legacy link. Exclude it at
    # the XcodeGen source-list level rather than adding fake controller APIs.
    project_text = project.read_text(encoding="utf-8")
    excludes = "        excludes: [Info.plist]"
    if project_text.count(excludes) != 1:
        raise RuntimeError("legacy XcodeGen Sources exclusion changed upstream")
    project.write_text(
        project_text.replace(excludes,
                             "        excludes: [Info.plist, GameMenu.swift]", 1),
        encoding="utf-8")

    original = main_file.read_text(encoding="utf-8")
    if "NX18_SHELL" in original:
        raise RuntimeError("already patched; use a fresh legacy checkout")

    updated = replace_one(
        original,
        "static char *g_argv[4]; static int g_argc;",
        """#ifdef NX18_SHELL
int nx18_guest_prepare(const char **names, int capacity);
#endif
static char *g_argv[20]; static int g_argc;""",
        "main.m argument list",
    )
    updated = replace_one(
        updated,
        '''    g_argv[0] = strdup("dmhost"); g_argv[1] = strdup(dm.fileSystemRepresentation); g_argc = 2;
    dm_host_preload_start(g_argc, g_argv);''',
        '''    g_argv[0] = strdup("dmhost"); g_argv[1] = strdup(dm.fileSystemRepresentation); g_argc = 2;
#ifdef NX18_SHELL
    // Before any native guest relocation, dyld must load the signed game
    // framework and the legacy loader must select that image's sections.
    const char *nx18_names[16] = {0};
    int nx18_n = nx18_guest_prepare(nx18_names, 16);
    if (nx18_n <= 0) {
        fprintf(stderr, "nx18: no signed game code to launch; cancelling preload\\n");
        return 0;
    }
    for (int k = 0; k < nx18_n; k++)
        g_argv[g_argc++] = strdup(nx18_names[k]);
#endif
    dm_host_preload_start(g_argc, g_argv);''',
        "main.m native preload",
    )
    # The modern font/save-data service asks about imports in main AND
    # dynamically loaded NROs. The older Metal3 loader already parses real
    # ELF symbols but only exposes dm_main_imports(). Implement the expanded
    # query on those parsed symbol tables; never return a fabricated answer.
    loader_source = loader.read_text(encoding="utf-8")
    main_imports = "int dm_main_imports(const char *prefix) {"
    if loader_source.count(main_imports) != 1:
        raise RuntimeError("legacy main-import symbol scanner changed upstream")
    expanded_imports = """
// nx18 iOS17: match modern loader semantics for main and NRO imports.
int dm_game_imports(const char *prefix) {
    size_t n = strlen(prefix);
    for (int i = 0; i < g_nmod; i++) if (g_mod[i].nro || !strcmp(g_mod[i].name, "main")) {
        module_t *m = &g_mod[i];
        for (unsigned k = 1; k < m->nsym; k++)
            if (!m->symtab[k].st_shndx && !strncmp(m->strtab + m->symtab[k].st_name, prefix, n))
                return 1;
    }
    return 0;
}
"""
    if "int dm_game_imports(" in loader_source:
        # Newer upstream branches already implement this API. Do not insert
        # a duplicate symbol; verify that it still checks main + NRO imports
        # rather than silently accepting an incompatible version.
        begin = loader_source.index("int dm_game_imports(")
        finish = loader_source.find("\n}\n", begin)
        if finish == -1:
            raise RuntimeError("upstream game-import scanner is incomplete")
        implementation = loader_source[begin:finish + 3]
        for required in ("g_mod[i].nro", 'g_mod[i].name, "main"',
                         "m->symtab[k].st_shndx", "return 1;"):
            if required not in implementation:
                raise RuntimeError("upstream game-import scanner semantics changed")
    else:
        start = loader_source.index(main_imports)
        end = loader_source.find("\n}\n", start)
        if end == -1:
            raise RuntimeError("unterminated legacy main-import symbol scanner")
        loader_source = (loader_source[:end + 3] + expanded_imports +
                         loader_source[end + 3:])
        loader.write_text(loader_source, encoding="utf-8")

    # The legacy host already has a runtime game profile (DM_PROFILE), so
    # preserve each game's real memory layout, title ID and RomFS marker
    # instead of hardcoding the neutral shell profile.
    profile_anchor = '    front_hud_env();'
    profile_injection = '''#ifdef NX18_SHELL
    // A user's game-profile TSV is carried in the signed app's dm folder.
    // Set it BEFORE the first dm_profile() call and before guest relocation.
    NSString *nx18_profile = [res stringByAppendingPathComponent:@"dm/profile.tsv"];
    if ([fm fileExistsAtPath:nx18_profile]) {
        setenv("DM_PROFILE", nx18_profile.fileSystemRepresentation, 1);
        fprintf(stderr, "nx18: per-game runtime profile loaded from dm/profile.tsv\\n");
    } else {
        fprintf(stderr, "nx18: no runtime game profile installed yet\\n");
    }
#endif
    front_hud_env();'''
    updated = replace_one(updated, profile_anchor, profile_injection,
                          "main.m runtime game profile")
    # Xcode 16.4 does not know SwiftUI's iOS26 Liquid Glass button style,
    # even inside #available(iOS 26.0, *). Keep the iOS17-compatible branch
    # as the sole expression in the @ViewBuilder.
    launcher = legacy / "dm/ios/Sources/Launcher.swift"
    if not launcher.is_file():
        raise RuntimeError("legacy launcher Swift source is missing")
    swift = launcher.read_text(encoding="utf-8")
    modern_menu_binding = '    gameMenuModel = model   // the in-game menu shows and saves the same choices (GameMenu.swift)'
    if swift.count(modern_menu_binding) != 1:
        raise RuntimeError("modern GameMenu model binding changed in legacy Launcher.swift")
    swift = swift.replace(modern_menu_binding,
        '    // nx18 legacy: gameMenuModel is part of excluded modern-only GameMenu.swift.')
    glass = ('if #available(iOS 26.0, *) { '
             'button.buttonStyle(.glassProminent) } else { '
             'button.buttonStyle(.borderedProminent) }')
    if swift.count(glass) == 1:
        swift = swift.replace(glass, 'button.buttonStyle(.borderedProminent)')
        launcher.write_text(swift, encoding="utf-8")
    elif ".glassProminent" in swift:
        raise RuntimeError("unhandled SwiftUI iOS26 .glassProminent reference")
    # A change in upstream SwiftUI sources can add more newer SDK usages.
    for source in (legacy / "dm/ios/Sources").glob("*.swift"):
        if ".glassProminent" in source.read_text(encoding="utf-8"):
            raise RuntimeError("SwiftUI 26 style remains in " + str(source))

    # Another iOS26-only declaration leaked into the cross-API Vulkan
    # fallback. The Xcode16.4 Metal SDK does not declare lodBias, even with
    # a runtime @available guard. On iOS18 the original guard never runs;
    # dropping this setter preserves the iOS18 behavior (bias unsupported).
    vk_source = legacy / "dm/gfx/vk/hle_vk.m"
    if not vk_source.is_file():
        raise RuntimeError("missing Vulkan compatibility source")
    vk = vk_source.read_text(encoding="utf-8")
    bias_line = ('        if (@available(iOS 26.0, tvOS 26.0, macOS 26.0, *)) '
                 'sd.lodBias = fminf(fmaxf(ci->mipLodBias, -15), 15);'
                 '   // Metal 26\'s sampler bias; the device reports maxSamplerLodBias 15')
    if vk.count(bias_line) != 1:
        raise RuntimeError("cannot safely remove newer-SDK-only sampler LOD bias")
    vk = vk.replace(bias_line,
        '        // nx18 iOS17: Metal3 sampler has no lodBias; omit '
        'Metal26-only setter.')
    vk_source.write_text(vk, encoding="utf-8")

    # iOS26's MetalFX frame interpolator class is absent from Xcode16.4.
    # These were capability probes only (actual framegen integration pending).
    # Retain MetalFX spatial/temporal scaling, mark interpolation unsupported.
    graphics = legacy / "dm/ios/Sources/DmGraphicsCapabilities.h"
    if not graphics.is_file():
        raise RuntimeError("legacy MetalFX capability header is missing")
    cap = graphics.read_text(encoding="utf-8")
    modern = '''    if (@available(iOS 26.0, *)) {
        interpolation = [MTLFXFrameInterpolatorDescriptor supportsDevice:device];
        interpolation4 = [MTLFXFrameInterpolatorDescriptor supportsMetal4FX:device];
    }'''
    if cap.count(modern) != 1:
        raise RuntimeError("iOS26 MetalFX probe was changed upstream")
    cap = cap.replace(modern,
        "    // nx18/iOS17: MetalFX frame interpolation is an iOS26 API; "
        "keep the two capabilities disabled.")
    graphics.write_text(cap, encoding="utf-8")

    # iOS27 CMMotionManager.deviceMotionBody is unavailable to the iOS18
    # SDK. On older devices phone_motion_start already maps hardware-frame
    # sensor readings through interface orientation. Leave that path intact.
    gamepad = legacy / "dm/ios/Sources/DmGamepad_legacy.inc"
    if not gamepad.is_file():
        raise RuntimeError("legacy gamepad motion source is missing")
    gp = gamepad.read_text(encoding="utf-8")
    body_line = """    if (@available(iOS 27.0, *)) { g_motion.deviceMotionBody = body; g_motion_body = YES; LOG("front end: the phone's motion comes in the pad view's frame (deviceMotionBody)"); }"""
    if gp.count(body_line) != 1:
        raise RuntimeError("iOS27 deviceMotionBody source differs; cannot patch safely")
    gp = gp.replace(body_line,
        '    // nx18 iOS17/18: use hardware-frame gyro + orientation mapping.')
    gamepad.write_text(gp, encoding="utf-8")

    # The modern HLE JIT service calls nro_unload_alone(), a standalone NRO
    # lifecycle method absent from the legacy loader. iOS cannot execute
    # dynamically generated guest code and CreateJitEnvironment already dies
    # before loading such a plugin. On iOS18 explicitly reject the impossible
    # teardown path; preserve the original logic on other platforms.
    jit = legacy / "dm/host/hle_jit.c"
    if not jit.is_file():
        raise RuntimeError("legacy JIT service source is missing")
    src = jit.read_text(encoding="utf-8")
    old_unload = '''    if (e->plugin) {
        if (e->plugin->fini) ((void (*)(void))(e->plugin->base + e->plugin->fini))();
        nro_unload_alone(e->plugin);   // the loader's: under its locks, with its check of stacks borrowing the plugin's data
        munmap((void *)e->rx, e->rx_size);
    }   // a served image stays mapped in the layout'''
    new_unload = '''#if TARGET_OS_IPHONE
    // A JIT plugin could never have loaded: iOS CreateJitEnvironment refuses it.
    if (e->plugin) die("nx18 iOS legacy loader cannot unload JIT NRO plugins");
#else
    if (e->plugin) {
        if (e->plugin->fini) ((void (*)(void))(e->plugin->base + e->plugin->fini))();
        nro_unload_alone(e->plugin);
        munmap((void *)e->rx, e->rx_size);
    }
#endif
    // A served image stays mapped in the native image layout.'''
    if src.count(old_unload) != 1:
        raise RuntimeError("legacy JIT service teardown changed upstream")
    jit.write_text(src.replace(old_unload, new_unload), encoding="utf-8")
    # iOS17 Metal3 uses loader_legacy.inc, which has no JIT layout/serve
    # implementation. The modern hle_jit.c calls dm_jit_serve_dir() even
    # though the legacy loader never defines it: an arm64 link failure.
    # This is deliberately NOT a fake service provider. Reject nn::jit at
    # runtime until a truly signed offline JIT-image pipeline is integrated.
    # macOS retains upstream capture/serve behavior unchanged.
    jit_source = jit.read_text(encoding="utf-8")
    serve_call = "    const char *serve = dm_jit_serve_dir();"
    if jit_source.count(serve_call) != 1:
        raise RuntimeError("upstream nn::jit serve entry changed; review legacy compatibility")
    jit_source = jit_source.replace(serve_call, """    const char *serve = NULL;
#if TARGET_OS_IPHONE
    // Legacy iOS17 loader cannot reserve/map an offline signed JIT image.
    // Never silently attempt dynamic code generation on a sideloaded iPhone.
    die("nx18 iOS17: nn::jit requires offline signed-image integration");
#else
    serve = dm_jit_serve_dir();
#endif""", 1)
    jit.write_text(jit_source, encoding="utf-8")


    # Modern hle_hid.c's DM_CTL "restop" is a diagnostics-only graphics
    # residency dump from the newer renderer. The iOS17 Metal3 renderer
    # does not export dm_gfx_restop(), so retaining that call fails arm64
    # linking. Keep the command intact on modern builds and Mac hosts;
    # report the unavailable command explicitly on legacy iPhones.
    hid = legacy / "dm/host/hle_hid.c"
    if not hid.is_file():
        raise RuntimeError("legacy HID service source is missing")
    hid_source = hid.read_text(encoding="utf-8")
    restop_call = ('                if (!strcmp(line, "restop")) { '
                   'void dm_gfx_restop(void); dm_gfx_restop(); continue; }'
                   '   // what the residency set holds (nvn_mtl.m res_top)')
    if hid_source.count(restop_call) != 1:
        raise RuntimeError("upstream DM_CTL restop handler changed; review legacy renderer ABI")
    restop_legacy = """                if (!strcmp(line, "restop")) {
#if TARGET_OS_IPHONE && !defined(DM_NVN_MODERN_RENDERER)
                    LOG("DM_CTL: restop unavailable in the iOS17 Metal3 legacy renderer");
#else
                    void dm_gfx_restop(void);
                    dm_gfx_restop();
#endif
                    continue;
                }"""

    # GPU buffer snapshots are a developer-only DM_CTL command added by
    # the modern renderer. Its callable entry is absent in legacy Metal3.
    # Preserve the command on modern platforms; expose honest diagnostics
    # on the legacy iPhone rather than inventing captured GPU data.
    bufsnap_call = ('                    if (sscanf(line + 8, "%31s %llx %lli %511s", '
                    'key, &a, &n, path) == 4) dm_gfx_bufsnap(key, a, (size_t)n, path); '
                    'else LOG("DM_CTL: bufsnap <shader key> <hex address> <bytes> <path>"); '
                    'continue; }')
    if hid_source.count(bufsnap_call) != 1:
        raise RuntimeError("upstream DM_CTL bufsnap handler changed; review Metal3")
    bufsnap_legacy = """#if TARGET_OS_IPHONE && !defined(DM_NVN_MODERN_RENDERER)
                    LOG("DM_CTL: bufsnap unavailable in the iOS17 Metal3 legacy renderer");
#else
                    if (sscanf(line + 8, "%31s %llx %lli %511s", key, &a, &n, path) == 4)
                        dm_gfx_bufsnap(key, a, (size_t)n, path);
                    else LOG("DM_CTL: bufsnap <shader key> <hex address> <bytes> <path>");
#endif
                    continue; }"""
    hid_source = hid_source.replace(bufsnap_call, bufsnap_legacy, 1)
    hid.write_text(hid_source.replace(restop_call, restop_legacy, 1),
                   encoding="utf-8")

    # Modern exit/handoff saves Metal pipelines through dm_gfx_quit*.
    # The legacy renderer owns a real MTLBinaryArchive persistence API,
    # nvn_cache_flush(), but not these lifecycle entry points. Adapt the
    # modern, deadline-bounded lifecycle to the actual legacy archive.
    # Avoid fake successful writes or blocking indefinitely on shutdown.
    lifecycle = legacy / "dm/host/hle_lifecycle.c"
    if not lifecycle.is_file():
        raise RuntimeError("legacy host shutdown source is missing")
    life_src = lifecycle.read_text(encoding="utf-8")
    life_anchor = "#include <unistd.h>\n"
    if life_src.count(life_anchor) != 1 or "void dm_gfx_quit_begin(" in life_src:
        raise RuntimeError("legacy graphics shutdown ABI changed upstream")
    life_bridge = """#if TARGET_OS_IPHONE && !defined(DM_NVN_MODERN_RENDERER)
// The legacy NVN Metal3 cache really serializes its MTLBinaryArchive.
void nvn_cache_flush(void);
static dispatch_once_t g_nx18_cache_quit_once;
static dispatch_semaphore_t g_nx18_cache_quit_done;
void dm_gfx_quit_begin(void) {
    dispatch_once(&g_nx18_cache_quit_once, ^{
        g_nx18_cache_quit_done = dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            nvn_cache_flush();
            dispatch_semaphore_signal(g_nx18_cache_quit_done);
        });
    });
}
void dm_gfx_quit(int budget_ms) {
    dm_gfx_quit_begin();
    if (budget_ms <= 0) return;
    if (dispatch_semaphore_wait(g_nx18_cache_quit_done,
            dispatch_time(DISPATCH_TIME_NOW, (int64_t)budget_ms * NSEC_PER_MSEC)))
        LOG("nx18 iOS17: Metal3 pipeline archive flush exceeded shutdown budget");
}
#endif
"""
    nvn_impl = legacy / "dm/gfx/nvn/legacy/hle_nvn.c.inc"
    has_upstream_lifecycle = False
    if nvn_impl.is_file():
        upstream_quit = nvn_impl.read_text(encoding="utf-8")
        has_begin = "void dm_gfx_quit_begin(void)" in upstream_quit
        has_wait = "void dm_gfx_quit(int " in upstream_quit
        if has_begin != has_wait:
            raise RuntimeError("incomplete upstream Metal3 shutdown ABI")
        has_upstream_lifecycle = has_begin and has_wait
        if has_upstream_lifecycle and "mtl_warm_wait(" not in upstream_quit:
            raise RuntimeError("upstream graphics shutdown semantics changed")
    if not has_upstream_lifecycle:
        lifecycle.write_text(life_src.replace(life_anchor, life_anchor + life_bridge, 1),
                             encoding="utf-8")
    # If the upstream classic NVN interface now owns these functions,
    # retain it verbatim. The fallback is for older upstream revisions only;
    # duplicate implementations cause a genuine arm64 linker error.

    # The newer vi::ListFrameHistory service reads queued/completed
    # presentation ticket counts. The legacy Metal3 renderer already owns
    # g_pq_in and g_pq_done but lacked the small locked accessor expected by
    # hle_vi.c. Expose its REAL queue state; do not fabricate frame numbers.
    mtl = renderer.read_text(encoding="utf-8")
    progress_anchor = "static uint64_t g_pq_in;"
    if mtl.count(progress_anchor) != 1:
        raise RuntimeError("legacy present-queue declaration changed upstream")
    progress = '''static uint64_t g_pq_in;
void mtl_present_progress(uint64_t *queued, uint64_t *done) {
    pthread_mutex_lock(&g_pq_mu);
    if (queued) *queued = g_pq_in;
    if (done) *done = g_pq_done;
    pthread_mutex_unlock(&g_pq_mu);
}'''
    if "void mtl_present_progress(" in mtl:
        # Upstream recently acquired the real queue-state API. Preserve the
        # native implementation rather than introducing a second symbol.
        begin = mtl.index("void mtl_present_progress(")
        finish = mtl.find("\n}\n", begin)
        if finish == -1:
            raise RuntimeError("upstream present-progress API is incomplete")
        implementation = mtl[begin:finish + 3]
        for required in ("pthread_mutex_lock(&g_pq_mu)",
                         "g_pq_in", "g_pq_done", "pthread_mutex_unlock(&g_pq_mu)"):
            if required not in implementation:
                raise RuntimeError("upstream present-progress API semantics changed")
    else:
        renderer.write_text(mtl.replace(progress_anchor, progress, 1),
                            encoding="utf-8")

    # Newer nn::vi::CreateLayer(width,height) calls mtl_present_layer().
    # The iOS17 Metal3 renderer did not export it. Record the requested VI
    # layer aspect and apply it in BOTH present encoders; preserve the texture
    # crop and UVs, which are already correct for the original swapchain.
    # An uninitialized size retains the old texture-based aspect behavior.
    mtl = renderer.read_text(encoding="utf-8")
    layer_anchor = ("static int present_encode(id<MTLCommandBuffer> cb, "
                    "id<MTLTexture> src, id<MTLTexture> dst, const int crop[4]);")
    layer_bridge = """static _Atomic uint64_t g_nx18_vi_layer_wh;
void mtl_present_layer(uint32_t w, uint32_t h) {
    if (!w || !h || w >= 0x10000 || h >= 0x10000) return;
    atomic_store_explicit(&g_nx18_vi_layer_wh,
                          ((uint64_t)w << 32) | h, memory_order_release);
}
// The VI layer dictates display aspect; the game's swapchain texture still
// dictates the sampling rectangle, crop and UV coordinates.
static void nx18_present_aspect(NSUInteger texture_w, NSUInteger texture_h,
                                double *content_w, double *content_h) {
    uint64_t wh = atomic_load_explicit(&g_nx18_vi_layer_wh, memory_order_acquire);
    *content_w = wh ? (double)(wh >> 32) : (double)texture_w;
    *content_h = wh ? (double)(wh & 0xffffffffu) : (double)texture_h;
}
static int present_encode(id<MTLCommandBuffer> cb, id<MTLTexture> src, id<MTLTexture> dst, const int crop[4]);"""
    if mtl.count(layer_anchor) != 1 or "void mtl_present_layer(" in mtl:
        raise RuntimeError("legacy Metal3 layer-size ABI changed upstream")
    mtl = mtl.replace(layer_anchor, layer_bridge, 1)
    aspect_calc = "double dw = dst.width, dh = dst.height, s = fmin(dw / cw, dh / ch);"
    if mtl.count(aspect_calc) != 2:
        raise RuntimeError("expected two legacy present-viewport calculations")
    mtl = mtl.replace(aspect_calc,
        "double dw = dst.width, dh = dst.height, content_w, content_h;\n"
        "    nx18_present_aspect(cw, ch, &content_w, &content_h);\n"
        "    double s = fmin(dw / content_w, dh / content_h);")
    orig_viewport = ("MTLViewport vp = {floor((dw - cw * s) / 2), "
                     "floor((dh - ch * s) / 2), round(cw * s), "
                     "round(ch * s), 0, 1};")
    new_viewport = ("MTLViewport vp = {floor((dw - content_w * s) / 2), "
                    "floor((dh - content_h * s) / 2), round(content_w * s), "
                    "round(content_h * s), 0, 1};")
    orig_fill = ("if (fabs((dw / dh) / ((double)cw / ch) - 1) < 0.01) "
                 "vp = (MTLViewport){0, 0, dw, dh, 0, 1};")
    new_fill = ("if (fabs((dw / dh) / (content_w / content_h) - 1) < 0.01) "
                "vp = (MTLViewport){0, 0, dw, dh, 0, 1};")
    if mtl.count(orig_viewport) != 2 or mtl.count(orig_fill) != 2:
        raise RuntimeError("legacy viewport ABI changed; refusing partial layer backport")
    mtl = mtl.replace(orig_viewport, new_viewport)
    mtl = mtl.replace(orig_fill, new_fill)
    renderer.write_text(mtl, encoding="utf-8")

    # The current GameMenu.swift asks front_ios.m whether a Setting can
    # be changed live. The legacy front_ios_legacy.inc has no such API.
    # Returning false hides those unsupported rows; controller layout and
    # Quit remain in the menu. Do NOT report that a setting was applied.
    legacy_front = legacy / "dm/ios/Sources/front_ios_legacy.inc"
    if not legacy_front.is_file():
        raise RuntimeError("legacy front-end source is missing")
    front = legacy_front.read_text(encoding="utf-8")
    if "dm_setting_live(" in front:
        raise RuntimeError("legacy front-end now implements live settings; review backport")
    front += """
// nx18 iOS17/18: the modern in-game menu probes for live settings.
// Legacy frontend has no dynamic setting handler. Hide unsupported entries.
bool dm_setting_live(const char *env, const char *value) {
    (void)env; (void)value;
    return false;
}
"""
    legacy_front.write_text(front, encoding="utf-8")

    # A game-free IPA has no RomFS and no signed Guest.framework yet. Offer
    # the existing, tested Swift NSP importer instead of the legacy error.
    # Only the missing-game path is redirected; a completed native game IPA
    # continues through the normal Metal3 game frontend.
    frontend = legacy / "dm/ios/Sources/front_ios_legacy.inc"
    source = frontend.read_text(encoding="utf-8")
    source = replace_one(source,
        "const char *front_ios_boot_message(void);",
        """const char *front_ios_boot_message(void);
#ifdef NX18_SHELL
void nx18_show_nsp_studio(void *view_controller);
void *nx18_make_nsp_studio_root(void);
#endif""", "native iOS NSP bridge")
    source = replace_one(source,
        "    front_ios_power_watch();\n    if (!front_ios_boot_ok()) {",
        """#ifdef NX18_SHELL
    if (!front_ios_boot_ok()) return;  // on-device NSP picker comes in viewDidAppear
#endif
    front_ios_power_watch();
    if (!front_ios_boot_ok()) {""", "native iOS no-RomFS startup")
    source = replace_one(source,
        "    if (!front_ios_boot_ok() && front_ios_boot_message() && !self.presentedViewController) {",
        """#ifdef NX18_SHELL
    if (!front_ios_boot_ok()) {
        if (!self.launched) {
            self.launched = YES;
            nx18_show_nsp_studio((__bridge void *)self);
        }
        return;
    }
#endif
    if (!front_ios_boot_ok() && front_ios_boot_message() && !self.presentedViewController) {""",
        "native iOS NSP picker presentation")
    # A game-free app must open its actual importer as the ROOT view.
    # Older versions tried presenting a modal in viewDidAppear, which left
    # users looking at the original game launcher with no NSP picker.
    # Returning UIHostingController directly bypasses that unreliable modal
    # and makes the Files button visible immediately on app launch.
    source = replace_one(source,
        "UIViewController *front_ios_root(void) {",
        """UIViewController *front_ios_root(void) {
#ifdef NX18_SHELL
    if (!front_ios_boot_ok()) {
        return (__bridge_transfer UIViewController *)nx18_make_nsp_studio_root();
    }
#endif""", "native iOS root NSP importer")
    frontend.write_text(source, encoding="utf-8")

    # The Studio importer already handles fileImporter, PFS0 indexing and
    # optional in-memory header-key scan. Reuse it without a second @main:
    # the legacy host's UIApplicationMain remains the only entry point.
    studio = HERE.parent / "Studio"
    studio_entry = (studio / "NX18App.swift").read_text(encoding="utf-8")
    view_anchor = "struct StudioView: View {"
    if studio_entry.count(view_anchor) != 1 or studio_entry.count("@main") != 1:
        raise RuntimeError("Studio entrypoint changed; cannot embed inspector safely")
    sources = legacy / "dm/ios/Sources"
    (sources / "NX18StudioView.swift").write_text(
        "import SwiftUI\nimport Foundation\nimport UniformTypeIdentifiers\n\n" +
        studio_entry[studio_entry.index(view_anchor):], encoding="utf-8")
    for filename in ("NSPInspector.swift", "NSPExtractor.swift",
                     "NCAHeader.swift", "NCAPayload.swift", "MetalProbe.swift",
                     "NX18DocumentPicker.swift"):
        destination = filename if filename.startswith("NX18") else "NX18" + filename
        shutil.copyfile(studio / filename, sources / destination)
    shutil.copyfile(HERE.parent / "Runtime/BCDecode.swift",
                    sources / "NX18BCDecode.swift")
    shutil.copyfile(HERE / "NX18Import.swift",
                    sources / "NX18Import.swift")


    # Modern GameMenu's Quit item relies on the modern UIKit quit-prompt
    # state machine (dm_quit_menu), absent from front_ios_legacy.inc.
    # Do not fake it with exit(0) and risk discarding the game's save data.
    # The iOS system Home gesture remains available to leave the app.
    menu_path = legacy / "dm/ios/Sources/GameMenu.swift"
    if not menu_path.is_file():
        raise RuntimeError("legacy GameMenu Swift source is missing")
    menu = menu_path.read_text(encoding="utf-8")
    quit_item = "items.append(Unmanaged<UIMenu>.fromOpaque(dm_quit_menu()).takeRetainedValue())"
    if menu.count(quit_item) != 1:
        raise RuntimeError("legacy in-game Quit menu call changed upstream")
    menu = menu.replace(quit_item,
        "// nx18 legacy iOS17/18: modern quit prompt absent; omit unsafe quit action.")
    menu_path.write_text(menu, encoding="utf-8")

    main_file.write_text(updated, encoding="utf-8")
    shutil.copyfile(HERE / "NX18Guest.m",
                    legacy / "dm/ios/Sources/NX18Guest.m")

    profile = legacy / "dm/games" / NEUTRAL
    profile.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(shell / "dm/games" / NEUTRAL / "game.tsv",
                    profile / "game.tsv")
    # Critical: the modern iOS26 shell carries a 000000000000 placeholder
    # shader-chain header. The legacy Metal3 renderer uses a COMPILED chain
    # identifier (e.g. c6c6ac82aed1). Never import the iOS26 placeholder.
    shutil.copyfile(legacy / "dm/gfx/nvn/legacy/dmsh_chain.h",
                    profile / "dmsh_chain.h")

    # Reuse upstream's actual Mach-O generator; change both the on-disk
    # LC_BUILD_VERSION and the plist minimum OS. Its original is iOS26.
    guest_source = (shell / "dm/tools/guest_dylib.py").read_text(encoding="utf-8")
    guest_source = replace_one(guest_source,
        "MIN_IOS = 26 << 16", "MIN_IOS = 17 << 16",
        "Guest framework Mach-O deployment target")
    guest_source = replace_one(guest_source,
        "<key>MinimumOSVersion</key><string>26.0</string>",
        "<key>MinimumOSVersion</key><string>17.0</string>",
        "Guest framework Info.plist minimum OS")
    (legacy / "dm/tools/guest_dylib.py").write_text(
        guest_source, encoding="utf-8")

    # Launcher/controller/shader assets remain from the legacy branch.
    # The game-free host still needs a validated shader-resource pipeline
    # and a final signed package before any gameplay can be claimed.
    return {
        "legacy": str(legacy),
        "native_guest_bridge": "dm/ios/Sources/NX18Guest.m",
        "generator": "dm/tools/guest_dylib.py",
        "iOS_minimum": "17.0",
        "renderer": "legacy Metal 3",
        "game_built": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--shell", type=Path, required=True)
    args = parser.parse_args()
    print(apply(args.legacy, args.shell))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

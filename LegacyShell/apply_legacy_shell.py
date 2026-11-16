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
    renderer = legacy / "dm/gfx/nvn/nvn_mtl_legacy.inc"
    project = legacy / "dm/ios/project.yml"
    needed = (main_file, loader, renderer, project,
              shell / "dm/tools/guest_dylib.py",
              shell / f"dm/games/{NEUTRAL}/game.tsv",
              legacy / "dm/gfx/nvn/legacy/dmsh_chain.h")
    missing = [str(p) for p in needed if not p.is_file()]
    if missing:
        raise RuntimeError("missing upstream file(s): " + ", ".join(missing))
    if "int dm_set_game_image_header(const void *header)" not in loader.read_text():
        raise RuntimeError("legacy host is missing its external image setter")
    metal = renderer.read_text()
    if "newLibraryWithSource" not in metal or "#ifdef DM_SHELL" not in metal:
        raise RuntimeError("expected iOS17 on-device MSL compiler branch is missing")
    if "DM_IOS_DEPLOYMENT_TARGET" not in project.read_text():
        raise RuntimeError("legacy project cannot be retargeted to iOS17")

    original = main_file.read_text()
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
    guest_source = (shell / "dm/tools/guest_dylib.py").read_text()
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

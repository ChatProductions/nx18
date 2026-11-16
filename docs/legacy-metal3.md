# Legacy Metal 3 bring-up: verified source path, remaining integration

Source line investigated: \`widmonstertony/nxnative\` branch \`ios16-ios17-compat\` (or the codebase matching the checked-out \`vendor/nxnative\` SHA).

## Important existing capability

The legacy renderer's \`dm/gfx/nvn/nvn_mtl_legacy.inc\` already contains an
\`#ifdef DM_SHELL\` branch in its Metal library loader. That branch detects a
source-form shader resource (not starting with \`MTLB\`) and compiles it through
\`-[MTLDevice newLibraryWithSource:options:error:]\`. There are additional
\`newLibraryWithSource\` call sites for software/GPU texture paths.

**Implication:** iPhone-side Metal source compilation is not a greenfield
implementation. We should reuse this proven code path, rather than introduce
an incompatible Metal 4 queue or require the Windows Metal Developer Tools.

**Not yet shown:** a complete game-free iOS shell, an AC2-specific shader
resource built for the legacy chain, the game loader's guest module mapping,
or a playable A15 result. \`DM_SHELL\` in a renderer does *not* mean the native
host and signing flow already support it.

## Two distinct upstream foundations

- \`widmonstertony/nxnative\`: iOS 16.1/17 target and Metal 3 renderer,
  suitable for investigation as an iOS 18 host. Its rewriter is Unix-fork-based
  for parallel scans, so the nx18 Windows wrapper forces one worker.
- \`xinerqu/ns2ios-shell\`: game-free host, guest-framework creation,
  on-device shader preparation, and the cross-platform Windows packer.
  But its current shell is an iOS **26** / Metal **4** build.

Next objective: **backport the game-free host/Guest.framework loader and
source-only shader packaging into the legacy host**, without taking the iOS 26
deployment target or Metal 4 command queue. Verify the Mach-O deployment
version and linked dynamic libraries before even attempting AC2.

The \`nx18 Studio\` inspection IPA is a separate research tool. It is **not**
the above game-free runtime.

Sources:
- https://github.com/widmonstertony/nxnative/blob/ios16-ios17-compat/dm/gfx/nvn/nvn_mtl_legacy.inc
- https://github.com/widmonstertony/nxnative/blob/ios16-ios17-compat/dm/ios/project.yml
- https://github.com/xinerqu/ns2ios-shell/blob/main/.shell-overlay.txt
- https://github.com/xinerqu/ns2ios-shell/blob/main/dm/ios/tools/shell_build.sh

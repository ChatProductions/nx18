# nx18

**Experimental Switch-native recompilation for iPhone 13 / iOS 18.7.8.** The target game is the **Nintendo Switch** release of *Assassin's Creed II* in *The Ezio Collection* (title ID `0100670014482000`). No console emulator, streaming, or runtime JIT.

## What exists today

- An **on-device iOS Studio** targeting **iOS 17+** (including iOS 18.7.8), built as an **unsigned IPA in GitHub Actions**, so you do not need Xcode or the Apple Developer download portal on Windows.
- A **real, bounds-checked PFS0/NSP indexer and streaming extractor** on-device. It reads the container and can copy encrypted NCA/ticket files locally without uploading keys, ROMs or account information.
- A Linux/macOS smoke test for the indexer.
- A CI audit of a real **Metal 3 / iOS 16.1** nxnative derivative to anchor the legacy runtime work.

**Important: This is not yet a playable AC2 IPA or a full NSP converter.** The NCA decryption/update layering, executable static rewriting, guest service layer, prelinked game binary, BC texture fallback, Metal 3 shader conversion, and final IPA assembly are outstanding. The Studio deliberately does not offer a fake "Play" or "Convert" button. Game code must be linked into a signed iOS-compatible Mach-O before executing; putting an NSP inside an IPA does not port it.

## Desired end-to-end pipeline

1. Import your legally obtained Switch base game and update on the iPhone.
2. Decode PFS0/NCA containers using local keys, validate AC2 title/program IDs, and layer updates.
3. Statically rewrite Switch ARM64 modules into an **iOS 18-compatible, pre-linkable native image**; no JIT and no emulated CPU.
4. Translate shaders to Metal Shading Language, with BC texture decompression/format fallbacks for the **A15** GPU.
5. Insert native code into a game-free **Metal 3** host, generate an unsigned IPA, and hand it to AltStore/LiveContainer for signing and installation.
6. Test the AC2 menu, actual gameplay, saves, audio, memory limits and frame pacing on an **iPhone 13 / 4 GB / iOS 18.7.8**.

The system cannot skip step 3 or code-signing: iOS disallows arbitrary executable pages for an unspecial-entitled third-party app.

## Download and use the Studio

Open [Actions](../../actions/workflows/ios-studio.yml) and select the latest successful run. Download the `nx18-studio-unsigned-ipa` artifact, unpack it and install its IPA through an Apple-ID sideloader that signs unsigned apps. The Studio imports a local `.nsp` from Files; it can extract its encrypted components locally, but **does not decrypt or upload** the game. Its inspection report can be shared for development. An `.xci` is not parsed yet.

If the Actions run fails, its build log is the authority; **do not assume an artifact exists**.

## Baselines investigated

- [widmonstertony/nxnative](https://github.com/widmonstertony/nxnative): iOS 16.1 / Metal 3-compatible native host; iPhone 13 and AC2 still unverified.
- [xinerqu/ns2ios-shell](https://github.com/xinerqu/ns2ios-shell): useful game-free shell and Windows packer; its current iOS target is **26.0**, so it cannot be used unmodified.
- [jhaizhou-ops/S2Arm](https://github.com/jhaizhou-ops/S2Arm): AC2/Ezio Collection Switch title `0100670014482000` has Mac gameplay evidence; its Windows packer requires Apple's Metal developer tools.

Any reused upstream code must preserve the upstream license and third-party attribution. No copyrighted game data, keys, or firmware belong in this repository.

## Development

- Studio source: `Studio/`
- PFS0 smoke test: `Tests/InspectorSmoke.swift`
- Build script: `scripts/build_studio.sh`
- Legacy renderer audit: `scripts/audit_legacy.py`
- CI: `.github/workflows/`

**Release maturity:** initial import and inspection proof of concept, **not** a finished Switch-to-iOS recompiler.

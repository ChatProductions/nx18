# nx18

**Experimental Switch-native recompilation for iPhone 13 / iOS 18.7.8.** The target game is the **Nintendo Switch** release of *Assassin's Creed II* in *The Ezio Collection* (title ID `0100670014482000`). No console emulator, streaming, or runtime JIT.

## Development track: native Metal 3 host and signed game code

The project has moved beyond a standalone inspection app. The active codepath is **game-agnostic**, with title-specific profiles for compatibility:

- **iOS 17/18 game-free native host**: [LegacyShell](LegacyShell/) backports signed `Guest.framework` loading into the established Metal 3 nxnative runtime, preserving its older iOS deployment target.
- **Windows native ARM64 rewriting**: [rewrite_exefs.py](tools/rewrite_exefs.py) uses the real existing NSO rewriter; it does not emulate a Switch CPU.
- **iOS 17 signed-code framework**: [build_guest18.py](tools/build_guest18.py) turns rewritten ARM64 modules into the Mach-O `Guest.framework` consumed by the legacy host.
- **Game-specific runtime settings**: the shell loads `dm/profile.tsv` so the selected game's program ID, memory layout, RomFS marker and service parameters do not inherit the shell placeholder.
- **Offline package assembly**: [package_native18.py](tools/package_native18.py) stages the host, rewritten modules, compatible legacy shader resources, profile and RomFS into an unsigned IPA. The final game IPA still needs signing.
- **CI host compilation**: [shell18.yml](.github/workflows/shell18.yml) builds the actual native Metal 3 host using a GitHub-hosted Xcode 16.4 runner, not the user's Windows PC.

**Verification boundary:** these are committed integration sources. Successful host compilation, a compatible per-game shader chain, a signed installable game and iPhone 13 gameplay have **not** been confirmed. An unsigned shell or package assembled without matching shaders is not playable.

[Engineering state and exact steps](docs/native18_pipeline.md)

## First-game test priorities (storage-sensitive)

| Priority | Switch game | Base title ID | Reason |
| --- | --- | --- | --- |
| **Now** | Terminator 2D: NO FATE | `0100B51020B68000` | Small first real-game target (~692 MB Switch download), prior ns2ios-shell Windows attempt; no huge AC2 transfer needed |
| **Fallback** | Need for Speed: Hot Pursuit Remastered | `010029B0118E8000` | Existing nxnative compatibility research, but a large ~8.1 GB download and A15 viability unproven |
| **Later** | Assassin's Creed II / The Ezio Collection | `0100670014482000` | Intended end goal; transfer deferred until storage is available |

Choose any registered game or a custom 16-digit Switch title ID:

```powershell
python tools/game_targets.py --list
python tools/rewrite_exefs.py "C:\Switch\Terminator\ExeFS" --upstream vendor/nxnative --output work/terminator-rewrite --title-id 0100B51020B68000
python tools/build_guest18.py --rewritten work/terminator-rewrite --legacy vendor/nxnative --out work/terminator-guest --target terminator
```

The code is generic but **no game has been verified playable on iPhone 13**. Existing game-specific shader/Horizon patches still matter. No proprietary game files or keys should be committed or uploaded to Actions.

## What exists today

- An **on-device iOS Studio** targeting **iOS 17+** (including iOS 18.7.8), built as an **unsigned IPA in GitHub Actions**, so you do not need Xcode or the Apple Developer download portal on Windows.
- A **real, bounds-checked PFS0/NSP indexer and streaming extractor** on-device. It reads the container and can copy encrypted NCA/ticket files locally without uploading keys, ROMs or account information.
- **Local `prod.keys` import** to AES-XTS-decode **only NCA headers**, identify the actual Switch ProgramId, and compare it to the Ezio Collection title ID. Keys are kept in session memory, never committed or shared; game content remains encrypted.
- An on-device **Metal Shading Language compiler + render-pass probe**: uses the iPhone GPU to compile an original triangle shader and submit a completed offscreen draw, **without Metal Developer Tools for Windows**. This tests the technique, not Switch graphics.
- A pure Swift **BC1 and BC3 to RGBA8 decoder** intended as an A15 GPU texture-format fallback, with edge-block and alpha tests. It is not yet wired into the NVN renderer.
- A macOS smoke test for the indexer, NCA header cryptography and texture decoding.
- A CI audit of a real **Metal 3 / iOS 16.1** nxnative derivative to anchor the legacy runtime work.
- A **Windows native static-rewrite adapter** to the real `widmonstertony/nxnative` `patch_nso.py` engine (Capstone 5). It generates `*.patched.bin`, `*.fixups.tsv` and gate data, plus a reproducibility manifest from a locally decrypted ExeFS. A [Windows CI smoke workflow](.github/workflows/rewrite-smoke.yml) exercises it on a synthetic ARM64 module.

**Important: This is not yet a playable AC2 IPA or a full NSP converter.** The NCA payload decryption/update layering, **on-device** executable rewriting, guest service layer, prelinked game binary, NVN integration for BC texture fallback, Metal 3 shader conversion, and final IPA assembly are outstanding. The Windows rewriter is **wired up but not yet AC2-tested or iOS-linked**. The Studio deliberately does not offer a fake "Play" or "Convert" button. Game code must be linked into a signed iOS-compatible Mach-O before executing; putting an NSP inside an IPA does not port it.


### Windows ARM64 rewrite stage (now wired to actual nxnative source)

The wrapper **calls the real** `dm/tools/patch_nso.py` in the iOS 16/17 legacy nxnative fork rather than using a dummy rewriter. It keeps the existing NSO preflight, records input/output SHA-256 hashes and verifies the output contains patched native images and host fixup/gate tables. This stage makes no IPA and does not require an Apple download.

On your Windows machine, clone nx18 or pull the latest changes, then open PowerShell in the repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
python .\tools\rewrite_exefs.py "F:\Roms\AC2\exefs" --upstream .\vendor\nxnative --output .\work\rewrite --title-id 0100670014482000 --jobs 2
```

Use your **already extracted, decrypted ExeFS** directory. `main`, `rtld`, `sdk` and `subsdk*` are ordinary NSO files; an NSP/XCI is not valid input to this command. Output is under `work/rewrite/` with `rewrite-manifest.json`. The upstream checkout's exact Git revision is recorded, so subsequent builds can be reproduced. Do not upload your game files or keys to GitHub.

**Unverified:** nxnative's rewriter has not yet been run on your actual AC2 NSOs, and the resulting output has not been linked to the iOS18 Metal3 host. You will still need to sign an eventual game IPA.


## Device-first workflow, Windows fallback

**Priority:** on-device conversion and packaging on the iPhone. Windows is permitted only for tasks that cannot practically be completed on-device. No requirement to download from Apple's Developer website or install the Apple Metal Developer Tools for Windows.

| Task | Preferred location | Alternative |
| --- | --- | --- |
| NSP import, PFS0 extraction, NCA header identification | iPhone | Python/LibHac tools on Windows if needed |
| NSO inspection and static recompilation | iPhone if practical | Windows Python, .NET and LLVM-based tools |
| Shader translation (NVN/SPIR-V to MSL) | iPhone if practical | Windows SPIRV-Cross or equivalent translator; output **MSL source**, not a Windows-compiled metallib |
| MSL compilation | iPhone **Metal API** | GitHub-hosted macOS runner if required; never require Metal Developer Tools for Windows |
| iOS native shell | Reusable unsigned shell | GitHub-hosted Xcode build (this does use Apple Xcode **on GitHub**, not on the user's PC) |
| Signing/install | User's existing AltStore/LiveContainer workflow | Other compatible Apple-ID sideloader |

The current iOS Studio workflow uses GitHub-hosted Xcode. The Windows tools are separate; using them does not require installing Xcode or signing into the Apple Developer downloads site on the Windows PC.

**Execution/signing limitation:** This hybrid architecture is research-stage. A stock sideloaded iPhone app cannot generate new executable code and run it as unsigned code. We must identify a legitimate prelinked native-image strategy, with required signing/reinstallation, before a fully on-device game build can be claimed. A Windows program alone cannot bypass iOS code-signing.

### Windows-native code preflight (implemented)

After legally extracting your own Switch game's `ExeFS` directory, the basic NSO validation runs with **stock Python 3.9+** and no other software:

```powershell
python tools/nso_probe.py "C:\Games\Ezio\exefs" -o "ac2_nso_preflight.json"
python -m unittest discover -s tests -p test_nso_probe.py -v
```

The preflight checks NSO0 headers and executable segment bounds for `main`, `rtld`, `sdk` and `subsdk*`. It reports section lengths, compression flags and module IDs. It does **not** decrypt NSOs, perform static recompilation, or make AC2 boot. The resulting report does not contain game code or cryptographic keys.

## Desired end-to-end pipeline

1. Import your legally obtained Switch base game and update on the iPhone.
2. Decode PFS0/NCA containers using local keys, validate AC2 title/program IDs, and layer updates.
3. Statically rewrite Switch ARM64 modules into an **iOS 18-compatible, pre-linkable native image**; no JIT and no emulated CPU.
4. Translate shaders to Metal Shading Language, with BC texture decompression/format fallbacks for the **A15** GPU.
5. Insert native code into a game-free **Metal 3** host, generate an unsigned IPA, and hand it to AltStore/LiveContainer for signing and installation.
6. Test the AC2 menu, actual gameplay, saves, audio, memory limits and frame pacing on an **iPhone 13 / 4 GB / iOS 18.7.8**.

The system cannot skip step 3 or code-signing: iOS disallows arbitrary executable pages for an unspecial-entitled third-party app.

## Download and use the Studio

Open [Actions](../../actions/workflows/ios-studio.yml) and select the latest successful run. Download the `nx18-studio-unsigned-ipa` artifact, unpack it and install its IPA through an Apple-ID sideloader that signs unsigned apps. The Studio imports a local `.nsp` from Files; it can extract its encrypted components and, given your own keys, inspect **NCA headers only**. It does not decrypt NCA game data, run the game, or upload files. Its inspection report can be shared for development. An `.xci` is not parsed yet.

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

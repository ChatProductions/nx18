# Terminator 2D: NO FATE — reuse existing Windows build

First native nx18 target: Switch title 0100B51020B68000, version v196608
(display version 1.0.3), iPhone 13 / iOS 18.7.8.

## Prior local conversion (gameplay still unverified)

The earlier Windows ns2ios conversion logs showed the game was extracted
and rewritten already, with the following exact 16-byte build IDs:

| ExeFS | Build ID |
| --- | --- |
| main | 2a5afa507f906ab09ad623dfe7f18862 |
| rtld | 2cf5725b70d9684ea3ce2ee7526c3b84 |
| sdk | d83a56a5558798414c78ec722867a7da |
| subsdk0 | e2970aa61f198ea32fbb247932d90406 |

Previous recorded outputs:
- ExeFS: ~33.6 MB; RomFS: ~553.8 MB, 14 entries.
- Unity IL2CPP/FMOD markers and Nintendo NVN graphics.
- 530 translated Metal-source shaders; no Apple compiler required.
- Old shader library: b-352884811607.img (~15.9 MB).
- Old Guest.framework: ~74.3 MB.
- Prior Terminator2D_test.ipa: ~557 MB; no verified device boot.

## Important ABI mismatch

The audited Metal3 legacy renderer uses shader chain c6c6ac82aed1,
not the older output 352884811607. A shader library's name encodes its
translation chain; those chains may differ in binding layouts and helper
ABI. Renaming the old image is not a valid conversion. Previously
rewritten game images also need a host gate/fixup ABI check.

## Read-only Windows audit

The native nx18 repo now contains tools/audit_cached_native.py.
Run it against your already existing local game-work directory;
no NSP re-extraction, large game transfer or Apple SDK is necessary.

    python tools/audit_cached_native.py --work "C:\YourSwitchWork\0100B51020B68000_pack" --target terminator --legacy-root vendor\nxnative --out work\terminator-cache-audit.json

If an earlier assembled IPA is available, add:

    --ipa "C:\YourOutput\Terminator2D_test.ipa"

The tool reads short NSO/fixup headers, gates, shader image filenames,
and (optionally) the iOS deployment metadata in the old IPA. It does not
read the full RomFS, decrypt or copy game files, or upload anything.

The resulting JSON report contains local absolute paths: keep it private.

## Next native milestones

1. Verify that the actual GitHub Actions native Metal3 host builds.
2. Inspect the previously extracted v196608 ExeFS and saved rewritten
   images; reuse only data whose ABI matches the legacy runtime.
3. Build a game-specific runtime profile from its NPDM and existing
   profile. Prior provisional memory values: mem_reserve 0x140000000,
   mem_alias 0x118000000, mem_stack 0x10000000, app_pool 0xCD500000,
   sys_resource 0x1000000. Verify against the actual game, not guesses.
4. Regenerate the Metal3-compatible shader chain and its shader_map.tsv,
   c1_full.tsv and companion libraries; do not relabel the iOS26 image.
5. Assemble the real signed iOS18 IPA and test on an iPhone 13.

nx18 can also produce a slim unsigned IPA without bundling RomFS. That
reduces packaging size, but actual local gameplay still needs the game
data to be present on the phone.


## Actual iPhone export comparison (17 November 2026)

Two real, user-supplied **decrypted ExeFS** export ZIPs were validated
*locally* without putting their game content into GitHub:

| Module | Earlier build ID | Updated build ID | Changed? |
| --- | --- | --- | --- |
| main | `8f0efdd5ba1378d406350fffc82f50c9` | `2a5afa507f906ab09ad623dfe7f18862` | Yes |
| rtld | `2cf5725b70d9684ea3ce2ee7526c3b84` | same | No |
| sdk | `d83a56a5558798414c78ec722867a7da` | same | No |
| subsdk0 | `e2970aa61f198ea32fbb247932d90406` | same | No |

The update's `main.npdm` also changed; the size remains 1604 bytes.
The updated `main` compressed NSO is **25,529,733 bytes**, compared with
**25,298,605 bytes** previously (+231,128 bytes). Every file passed its
NX18-export manifest SHA-256 check, and all **12** NSO segments
decompressed and matched their internal SHA-256 hashes.

**The updated full ExeFS is the native-rewriter input**, not the earlier
base `main`. The updated main's build ID matches the earlier Windows
conversion record above. Recording this identity is not a native code
rewrite and not evidence of an on-device boot.

This repository has no uploaded copyrighted ExeFS or RomFS data. The local
inspection runtime used for the uploads had no Capstone 5 installation and
could not reach the package mirror/upstream checkout, so no real-game
`Guest.framework` could be produced in that runtime. The existing Windows
native pipeline remains tested with synthetic input, not with the uploaded
game code. All assets and gameplay verification remain incomplete.

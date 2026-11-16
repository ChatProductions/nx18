#!/usr/bin/env python3
"""Fail closed if our prospective iOS 18 native baseline loses its legacy Metal route."""
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("vendor/nxnative")
project = root / "dm/ios/project.yml"
legacy = root / "dm/gfx/nvn/nvn_mtl_legacy.inc"
source = root / "dm/ios/tools/build_ipa.sh"
missing = [str(p) for p in (project, legacy, source) if not p.is_file()]
if missing:
    raise SystemExit("FAIL: missing legacy base files: " + ", ".join(missing))
p = project.read_text(encoding="utf-8")
v = legacy.read_text(encoding="utf-8")
checks = {
    "configurable deployment target": "DM_IOS_DEPLOYMENT_TARGET" in p,
    "legacy Apple A10 CPU baseline": "-mcpu=apple-a10" in p,
    "traditional Metal header": "<Metal/Metal.h>" in v,
    "no hardcoded iOS 26.0 deployment": 'iOS: "26.0"' not in p,
}
for name, ok in checks.items():
    print(("PASS" if ok else "FAIL") + ": " + name)
if not all(checks.values()):
    raise SystemExit("Legacy runtime audit failed")
print("PASS: legacy baseline is suitable for PORTING, not a built AC2 runtime.")

#!/usr/bin/env python3
"""Windows/Linux/macOS frontend to nxnative's REAL native NSO rewriter.

Input: locally extracted Switch ExeFS/ (main, rtld, sdk, subsdk*).
Output: native-rewritten *.patched.bin plus fixup/gate tables and manifest.
It does NOT compile a host or make an IPA, and is NOT an emulator.
Requires a local checkout of widmonstertony/nxnative, Capstone 5, and lz4.
No Xcode, Apple Developer account, Metal Windows SDK, prod.keys, or network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from nso_probe import inspect_exefs

MODULE_NAME = re.compile(r"(?:main|rtld|sdk|subsdk[0-9]+)\Z")
TITLE_ID = re.compile(r"[0-9a-fA-F]{16}\Z")
EXPECTED_FILES = ("patched.bin", "fixups.tsv", "gates.tsv")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for part in iter(lambda: src.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def checked_upstream(root: Path) -> Path:
    rewrite = root / "dm" / "tools" / "patch_nso.py"
    required = ("nso.py", "nso_asm.py")
    if not rewrite.is_file() or any(not (rewrite.parent / p).is_file() for p in required):
        raise ValueError(
            f"Not a compatible nxnative checkout: {root} "
            "(missing dm/tools/patch_nso.py, nso.py or nso_asm.py)"
        )
    return rewrite


def git_revision(root: Path) -> str | None:
    try:
        run = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        rev = run.stdout.strip()
        return rev if re.fullmatch(r"[0-9a-f]{40}", rev) else None
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def run_rewrite(exefs: Path, upstream: Path, output: Path, *,
                title_id: str, jobs: int = 2,
                python: str = sys.executable,
                runner=None) -> dict:
    if not TITLE_ID.fullmatch(title_id):
        raise ValueError("title ID must be 16 hexadecimal digits")
    if jobs < 1 or jobs > 32:
        raise ValueError("jobs must be between 1 and 32")
    rewrite = checked_upstream(upstream.resolve())
    report = inspect_exefs(exefs)
    if not report["ready_for_rewriter"]:
        raise ValueError("ExeFS preflight failed: " + json.dumps(report["errors"]))
    names = {m["filename"] for m in report["modules"]}
    if "main" not in names:
        raise ValueError("ExeFS must contain a valid main module")
    if not all(MODULE_NAME.fullmatch(n) for n in names):
        raise ValueError("unsafe module name in ExeFS")

    output = output.resolve()
    if output == exefs.resolve() or output == upstream.resolve():
        raise ValueError("output must not overwrite source or the upstream checkout")
    output.mkdir(parents=True, exist_ok=True)
    if runner is None:
        runner = subprocess.run

    env = os.environ.copy()
    env["DM_GAME"] = title_id.upper()
    env["DM_REWRITE_J"] = str(jobs)
    # Explicitly do not read/copy prod.keys or original game files into this repository.
    manifest = {
        "schema_version": 1,
        "stage": "switch-arm64-static-rewrite-only",
        "source_exefs": str(exefs.resolve()),
        "source_revision": git_revision(upstream),
        "title_id": title_id.upper(),
        "upstream_rewriter": str(rewrite),
        "platform": "Windows-compatible Python subprocess",
        "modules": [],
        "host_or_ipa_built": False,
        "gameplay_verified": False,
    }
    for module in report["modules"]:
        name = module["filename"]
        inp = (exefs / name).resolve(strict=True)
        mod_out = output / name
        mod_out.mkdir(parents=True, exist_ok=True)
        argv = [python, str(rewrite), str(inp), str(mod_out), name]
        print(f"[nx18] rewriting {name} ({module['file_bytes']} bytes)…", flush=True)
        try:
            runner(argv, cwd=str(upstream / "dm"), env=env, check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"nxnative rewriter failed on {name}: {error}") from error

        products = {}
        for suffix in EXPECTED_FILES:
            p = mod_out / f"{name}.{suffix}"
            if not p.is_file() or p.stat().st_size == 0:
                raise RuntimeError(f"rewriter did not produce expected {p.name}")
            products[suffix] = {
                "relative_path": str(p.relative_to(output)),
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
        manifest["modules"].append({
            "name": name,
            "nso_input_sha256": sha256_file(inp),
            "nso_build_id": module["module_id_hex"],
            "rewriter_outputs": products,
        })
    mf = output / "rewrite-manifest.json"
    mf.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[nx18] {len(manifest['modules'])} modules rewritten; manifest: {mf}", flush=True)
    print("[nx18] Native runtime / signing / shaders / AC2 gameplay NOT tested.", flush=True)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exefs", type=Path, help="Extracted, decrypted ExeFS directory")
    parser.add_argument("--upstream", required=True, type=Path,
                        help="Local nxnative checkout, e.g. vendor/nxnative")
    parser.add_argument("--output", type=Path, default=Path("work") / "rewrite")
    parser.add_argument("--title-id", default="0100670014482000")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        run_rewrite(args.exefs.resolve(), args.upstream, args.output,
                    title_id=args.title_id, jobs=args.jobs)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[nx18] ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

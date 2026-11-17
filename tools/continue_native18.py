#!/usr/bin/env python3
"""Continue an iPhone NX18 ExeFS export through REAL ARM64 rewriting and Guest.framework.

Works on Windows 11 with Python; no Xcode or Apple Developer download.
Requires the same local nxnative checkout prepared by scripts/setup-windows.ps1.
Does not run games, decrypt RomFS, translate shaders or sign an iOS app.
No Nintendo keys or game data are uploaded to GitHub Actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from build_guest18 import write_guest
from game_targets import title_id
from nso_probe import inspect_exefs
from rewrite_exefs import run_rewrite

MODULE = re.compile(r"(?:main|rtld|sdk|subsdk[0-9]+)\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
EXPORT = "nx18-export.json"


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_export(exefs: Path, selected_title: str | None) -> dict:
    """Fail closed on edited files, wrong title, bad manifest or missing main.

    The manifest is a provenance and integrity check, not a cryptographic
    Nintendo signature or proof that the selected title actually owns an NCA.
    """
    exefs = exefs.resolve(strict=True)
    if not exefs.is_dir():
        raise ValueError("ExeFS export must be a directory")
    manifest_path = exefs / EXPORT
    if manifest_path.is_file():
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        if doc.get("schema_version") != 1 or doc.get("stage") != "decrypted-exefs":
            raise ValueError("unrecognized NX18 ExeFS export schema/stage")
        actual_title = title_id(doc.get("title_id", ""))
        entries = doc.get("files")
        if not isinstance(entries, list) or not entries:
            raise ValueError("ExeFS export manifest lists no files")
        seen: set[str] = set()
        for record in entries:
            if not isinstance(record, dict):
                raise ValueError("invalid ExeFS export entry")
            name = record.get("name")
            if (not isinstance(name, str) or not name or
                    name in {".", ".."} or "/" in name or "\\" in name or
                    name in seen):
                raise ValueError("unsafe or duplicate exported filename")
            seen.add(name)
            child = exefs / name
            if child.is_symlink() or not child.is_file():
                raise ValueError(f"missing or symlinked exported file: {name}")
            amount = record.get("size_bytes")
            sha = record.get("sha256")
            if (type(amount) is not int or amount < 0 or
                    child.stat().st_size != amount or
                    not isinstance(sha, str) or not SHA256.fullmatch(sha)):
                raise ValueError(f"bad length or SHA-256 record: {name}")
            if digest(child) != sha:
                raise ValueError(f"ExeFS file changed after export: {name}")
        # All relevant code must appear in the checksum manifest.
        for child in exefs.iterdir():
            if child.is_file() and MODULE.fullmatch(child.name) and child.name not in seen:
                raise ValueError(f"unlisted executable module: {child.name}")
    else:
        if selected_title is None:
            raise ValueError(
                "nx18-export.json not found; pass --title-id to identify legacy ExeFS")
        actual_title = title_id(selected_title)

    if selected_title is not None and actual_title != title_id(selected_title):
        raise ValueError("selected title ID disagrees with iPhone ExeFS export")

    report = inspect_exefs(exefs)
    names = {row["filename"] for row in report["modules"]}
    if not report["ready_for_rewriter"] or "main" not in names:
        raise ValueError("decrypted NSO preflight failed: " +
                         json.dumps(report["errors"]))
    if any(not MODULE.fullmatch(name) for name in names):
        raise ValueError("unexpected NSO module name")
    return {
        "title_id": actual_title,
        "modules": sorted(names),
        "export_manifest_verified": manifest_path.is_file(),
        "nso_header_verified": True,
        "gameplay_verified": False,
    }


def continue_native(exefs: Path, upstream: Path, output: Path, *,
                    selected_title: str | None = None, jobs: int = 2,
                    verify_only: bool = False) -> dict:
    exefs = exefs.resolve(strict=True)
    upstream = upstream.resolve()
    output = output.resolve()
    if output == exefs or exefs in output.parents or output in exefs.parents:
        raise ValueError("output must not be inside or above the extracted ExeFS")
    if output == upstream or upstream in output.parents or output in upstream.parents:
        raise ValueError("output must not overwrite the nxnative checkout")
    binding = validate_export(exefs, selected_title)
    if verify_only:
        return {"stage": "validated-decrypted-exefs", **binding,
                "rewrite_performed": False, "guest_built": False,
                "iPhone_gameplay_verified": False}

    rewrite = output / "rewrite"
    native = output / "native"
    if any(item.exists() for item in (rewrite, native, output / "pipeline-report.json")):
        raise ValueError("output contains a previous rewrite; choose a clean --output")
    manifest = run_rewrite(
        exefs, upstream, rewrite, title_id=binding["title_id"], jobs=jobs)
    guest = write_guest(rewrite, upstream, native, target_id=binding["title_id"])
    report = {
        "schema_version": 1,
        "stage": "rewritten-arm64-and-ios17-guest",
        "source_exefs": str(exefs),
        "title_id": binding["title_id"],
        "export_manifest_verified": binding["export_manifest_verified"],
        "nso_header_verified": True,
        "modules": binding["modules"],
        "rewritten_manifest": str(rewrite / "rewrite-manifest.json"),
        "guest_framework": guest["guest_framework"],
        "guest_manifest": str(native / "guest18-manifest.json"),
        "rewrite_completed": bool(manifest.get("modules")),
        "guest_built": True,
        "shaders_translated": False,
        "romfs_included": False,
        "ipa_packaged": False,
        "ipa_signed": False,
        "iPhone_gameplay_verified": False,
        "next_gate": "Generate compatible Metal3 shader chain and RomFS, package into an unsigned IPA, re-sign all nested code",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "pipeline-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("exefs", type=Path, help="nx18-native-input/<export-id> folder from the iPhone")
    p.add_argument("--upstream", type=Path, default=Path("vendor/nxnative"),
                   help="nxnative checkout patched for iOS17 with scripts/setup-windows.ps1")
    p.add_argument("--output", type=Path, default=Path("work/native-from-phone"))
    p.add_argument("--title-id", help="Required for older ExeFS folders without nx18-export.json")
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--verify-only", action="store_true",
                   help="Validate source/checksums, do not rewrite or emit native images")
    args = p.parse_args(argv)
    try:
        result = continue_native(args.exefs, args.upstream, args.output,
                                 selected_title=args.title_id,
                                 jobs=args.jobs, verify_only=args.verify_only)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print("nx18 native continuation stopped: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

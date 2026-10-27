"""Verify exact parity between a sealed CoDIR-IA ZIP and SHA256SUMS.

Usage:
    python scripts/verify_zip_manifest.py /path/to/CoDIR-IA-....zip

The verifier checks three independent contracts:
1. every non-directory ZIP member except SHA256SUMS is manifest-listed;
2. every manifest path exists exactly once in the ZIP;
3. every member hash matches the manifest.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import PurePosixPath


def verify_zip_manifest(zip_path: str) -> dict[str, object]:
    errors: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        files = [n for n in zf.namelist() if not n.endswith("/")]
        if not files:
            return {"ok": False, "errors": ["empty ZIP"], "files": 0, "manifested": 0}
        roots = {PurePosixPath(n).parts[0] for n in files}
        if len(roots) != 1:
            errors.append(f"expected one root directory, got {sorted(roots)}")
        root = next(iter(roots))
        manifest_name = f"{root}/SHA256SUMS"
        if manifest_name not in files:
            return {"ok": False, "errors": errors + ["SHA256SUMS missing"],
                    "files": len(files), "manifested": 0}
        raw = zf.read(manifest_name).decode("utf-8", errors="strict")
        manifest: dict[str, str] = {}
        for lineno, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                digest, rel = line.split("  ", 1)
            except ValueError:
                errors.append(f"invalid manifest line {lineno}: {line!r}")
                continue
            rel = rel.strip().replace("\\", "/")
            if rel in manifest:
                errors.append(f"duplicate manifest path: {rel}")
            manifest[rel] = digest.strip().lower()
        actual_rel = {
            str(PurePosixPath(n).relative_to(root))
            for n in files if n != manifest_name
        }
        manifest_rel = set(manifest)
        missing = sorted(manifest_rel - actual_rel)
        extra = sorted(actual_rel - manifest_rel)
        if missing:
            errors.append(f"manifested paths missing from ZIP: {missing[:10]}")
        if extra:
            errors.append(f"ZIP paths absent from manifest: {extra[:10]}")
        for rel in sorted(actual_rel & manifest_rel):
            data = zf.read(f"{root}/{rel}")
            got = hashlib.sha256(data).hexdigest()
            if got != manifest[rel]:
                errors.append(f"hash mismatch: {rel}")
    return {
        "ok": not errors,
        "errors": errors,
        "files": len(files),
        "manifested": len(manifest),
        "root": root,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: verify_zip_manifest.py <archive.zip>", file=sys.stderr)
        return 2
    report = verify_zip_manifest(argv[1])
    print(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

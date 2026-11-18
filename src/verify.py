"""
Check a de-identified folder against its source:
- no removed element is present, emptied elements are empty, no private tags
- every UID differs from the source, and the series structure is unchanged
- pixel data is byte-identical
- PatientIdentityRemoved is YES

    python src/verify.py SOURCE_DIR ANON_DIR
"""

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pydicom

from anonymise import EMPTY, REMOVE, UID_TAGS


def pixel_hash(ds):
    return hashlib.sha256(ds.PixelData).hexdigest()


def scan(root, with_pixels):
    out = []
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            try:
                out.append(pydicom.dcmread(p, stop_before_pixels=not with_pixels))
            except Exception:
                pass
    return out


def verify(source_dir, anon_dir):
    src, anon = scan(source_dir, True), scan(anon_dir, True)
    problems = []
    src_uids = {str(ds.get(k)) for ds in src for k in UID_TAGS if k in ds}
    for ds in anon:
        for kw in REMOVE:
            if kw in ds:
                problems.append(f"{ds.SOPInstanceUID[-8:]}: {kw} present")
        for kw in EMPTY:
            if kw in ds and str(ds.data_element(kw).value).strip():
                problems.append(f"{ds.SOPInstanceUID[-8:]}: {kw} not empty")
        if any(el.tag.is_private for el in ds):
            problems.append(f"{ds.SOPInstanceUID[-8:]}: private tags")
        for k in UID_TAGS:
            if k in ds and str(ds.get(k)) in src_uids:
                problems.append(f"{ds.SOPInstanceUID[-8:]}: {k} not replaced")
        if ds.get("PatientIdentityRemoved") != "YES":
            problems.append(f"{ds.SOPInstanceUID[-8:]}: PatientIdentityRemoved not YES")

    def structure(dsets):
        return sorted(Counter(str(d.SeriesInstanceUID) for d in dsets).values())

    checks = {
        "files": (len(src), len(anon)),
        "series_sizes_match": structure(src) == structure(anon),
        "pixels_identical": sorted(map(pixel_hash, src)) == sorted(map(pixel_hash, anon)),
        "header_problems": len(problems),
    }
    return checks, problems


def main():
    parser = argparse.ArgumentParser(description="Verify de-identified DICOM against its source")
    parser.add_argument("source_dir")
    parser.add_argument("anon_dir")
    args = parser.parse_args()
    checks, problems = verify(args.source_dir, args.anon_dir)
    for k, v in checks.items():
        print(f"{k}: {v}")
    for p in problems[:20]:
        print("  " + p)
    ok = checks["series_sizes_match"] and checks["pixels_identical"] and not problems
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

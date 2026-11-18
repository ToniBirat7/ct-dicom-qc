"""
Header audit of CT series: one row per series, with the checks that decide
whether a series can be used for 3D analysis.

Identifying values are never printed: the report only says whether a tag is filled.

    python src/audit.py DATA_DIR --out results/audit.csv
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from series import group_series, order_slices, slice_positions

IDENTIFYING = [
    "PatientName", "PatientID", "PatientBirthDate", "OtherPatientIDs", "PatientAddress",
    "InstitutionName", "InstitutionAddress", "ReferringPhysicianName", "OperatorsName",
    "PerformingPhysicianName", "AccessionNumber", "StationName", "DeviceSerialNumber",
]


def filled(ds, tag):
    return tag in ds and str(ds.get(tag, "")).strip() not in ("", "ANONYMOUS")


def audit_series(uid, items):
    ordered = order_slices(items)
    first = ordered[0][1]
    pos = slice_positions(ordered)
    gaps = np.diff(pos)
    step = float(np.median(gaps)) if len(gaps) else np.nan
    orient = {tuple(np.round(np.array(ds.ImageOrientationPatient, dtype=float), 4)) for _, ds in ordered}
    spacing = {tuple(map(float, ds.PixelSpacing)) for _, ds in ordered if "PixelSpacing" in ds}
    thickness = float(first.get("SliceThickness", np.nan) or np.nan)
    o = np.array(first.ImageOrientationPatient, dtype=float)
    normal = np.cross(o[:3], o[3:])

    row = {
        "series_uid_suffix": uid[-12:],
        "modality": first.get("Modality", ""),
        "body_part": first.get("BodyPartExamined", ""),
        "manufacturer": first.get("Manufacturer", ""),
        "kvp": first.get("KVP", ""),
        "n_slices": len(ordered),
        "rows_cols": f"{first.Rows}x{first.Columns}",
        "pixel_spacing_mm": "x".join(f"{v:.3f}" for v in next(iter(spacing))) if spacing else "",
        "slice_thickness_mm": thickness,
        "slice_step_mm": round(step, 3),
        "photometric": first.get("PhotometricInterpretation", ""),
        "bits_stored": first.get("BitsStored", ""),
        "rescale_slope": first.get("RescaleSlope", ""),
        "rescale_intercept": first.get("RescaleIntercept", ""),
        "identifying_tags_filled": sum(filled(first, t) for t in IDENTIFYING),
        "private_tags": sum(1 for el in first if el.tag.is_private),
    }
    issues = []
    if len(orient) > 1:
        issues.append("mixed orientation")
    if len(spacing) > 1:
        issues.append("mixed pixel spacing")
    if len(gaps) and np.any(np.abs(gaps) < 1e-3):
        issues.append("duplicate positions")
    if len(gaps) and np.ptp(gaps) > 0.01:
        issues.append(f"uneven slice step ({gaps.min():.2f} to {gaps.max():.2f} mm)")
    if len(gaps) and np.any(gaps > 1.5 * step):
        issues.append("missing slices")
    if not np.isnan(thickness) and step > 0 and abs(thickness - step) > 0.01:
        issues.append("overlapping" if thickness > step else "gapped reconstruction")
    if abs(abs(normal[2]) - 1.0) > 1e-3 or float(first.get("GantryDetectorTilt", 0) or 0) != 0:
        issues.append("not axial or gantry tilt")
    if "RescaleSlope" not in first or "RescaleIntercept" not in first:
        issues.append("no rescale (HU unknown)")
    if row["photometric"] == "MONOCHROME1":
        issues.append("MONOCHROME1 (inverted display)")
    if str(first.get("BurnedInAnnotation", "NO")).upper() == "YES":
        issues.append("burned-in annotation")
    row["issues"] = "; ".join(issues) if issues else "none"
    return row


def main():
    parser = argparse.ArgumentParser(description="Audit DICOM CT series headers")
    parser.add_argument("data_dir")
    parser.add_argument("--out", default="results/audit.csv")
    args = parser.parse_args()

    series = group_series(args.data_dir)
    df = pd.DataFrame([audit_series(uid, items) for uid, items in series.items()])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()

"""
Convert each CT series to NIfTI with SimpleITK, then check the result against
an independent pydicom reader (own slice ordering and rescale).

    python src/convert.py DATA_DIR OUT_DIR
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import SimpleITK as sitk

from series import group_series, order_slices, slice_positions, stack_hu


def convert_series(items, out_path):
    ordered = order_slices(items)
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames([str(p) for p, _ in ordered])
    img = reader.Execute()
    sitk.WriteImage(img, str(out_path), True)

    ref = stack_hu(items)  # (z, y, x)
    arr = sitk.GetArrayFromImage(img).astype(np.float32)
    step = float(np.median(np.diff(slice_positions(ordered))))
    return {
        "file": out_path.name,
        "size": "x".join(map(str, img.GetSize())),
        "spacing_mm": "x".join(f"{s:.3f}" for s in img.GetSpacing()),
        "z_spacing_matches_positions": bool(abs(img.GetSpacing()[2] - step) < 1e-3),
        "max_abs_diff_hu": float(np.abs(arr - ref).max()) if arr.shape == ref.shape else np.nan,
        "hu_min": float(arr.min()),
        "hu_max": float(arr.max()),
        "air_like_fraction": round(float((arr < -900).mean()), 3),
    }


def main():
    parser = argparse.ArgumentParser(description="DICOM series to NIfTI with a cross-check")
    parser.add_argument("data_dir")
    parser.add_argument("out_dir")
    parser.add_argument("--report", default="results/conversion.csv")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (uid, items) in enumerate(sorted(group_series(args.data_dir).items()), 1):
        row = convert_series(items, out_dir / f"series_{i:02d}.nii.gz")
        rows.append(row)
        print(row)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.report, index=False)


if __name__ == "__main__":
    main()

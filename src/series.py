"""Reading DICOM series: grouping files, ordering slices, and stacking pixels in HU."""

from collections import defaultdict
from pathlib import Path

import numpy as np
import pydicom


def iter_dicom(root):
    """Yield (path, dataset without pixels) for every readable DICOM file under root."""
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=True)
        except Exception:
            continue
        if "SOPInstanceUID" in ds:
            yield p, ds


def group_series(root):
    """SeriesInstanceUID -> list of (path, header)."""
    series = defaultdict(list)
    for p, ds in iter_dicom(root):
        series[ds.SeriesInstanceUID].append((p, ds))
    return dict(series)


def slice_normal(ds):
    o = np.array(ds.ImageOrientationPatient, dtype=float)
    return np.cross(o[:3], o[3:])


def order_slices(items):
    """Sort (path, header) by position along the slice normal, not by file name or InstanceNumber."""
    n = slice_normal(items[0][1])
    return sorted(items, key=lambda it: float(np.dot(n, np.array(it[1].ImagePositionPatient, dtype=float))))


def slice_positions(items):
    n = slice_normal(items[0][1])
    return np.array([np.dot(n, np.array(ds.ImagePositionPatient, dtype=float)) for _, ds in items])


def to_hu(ds):
    """Apply the modality LUT (rescale slope and intercept)."""
    arr = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    intercept = float(getattr(ds, "RescaleIntercept", 0.0))
    return arr * slope + intercept


def stack_hu(items):
    """Ordered volume (z, y, x) in HU, read independently of SimpleITK."""
    ordered = order_slices(items)
    return np.stack([to_hu(pydicom.dcmread(p)) for p, _ in ordered])

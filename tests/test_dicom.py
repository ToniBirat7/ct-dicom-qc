"""Tests on a synthetic CT series written with pydicom."""

import numpy as np
import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from src.anonymise import Anonymiser
from src.audit import audit_series
from src.convert import convert_series
from src.series import group_series, order_slices
from src.verify import verify


def make_series(folder, n=6, step=2.5, shuffle=True, patient_id="MRN123"):
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    order = np.random.default_rng(0).permutation(n) if shuffle else range(n)
    for k, i in enumerate(order):
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(folder / f"f{k}.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = CTImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.Modality, ds.Manufacturer = "CT", "TEST"
        ds.PatientName, ds.PatientID, ds.PatientBirthDate = "Doe^Jane", patient_id, "19500101"
        ds.StudyDate, ds.InstitutionName, ds.AccessionNumber = "20200315", "General Hospital", "ACC9"
        ds.add_new(0x00091001, "LO", "private value")
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0.0, 0.0, float(i) * step]
        ds.PixelSpacing, ds.SliceThickness = [0.8, 0.8], step
        ds.Rows = ds.Columns = 8
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
        ds.RescaleSlope, ds.RescaleIntercept = 1, -1024
        ds.PixelData = (np.full((8, 8), 1024 + 10 * i, dtype=np.uint16)).tobytes()
        ds.InstanceNumber = k + 1  # deliberately unrelated to position
        ds.save_as(folder / f"f{k}.dcm", enforce_file_format=True)


@pytest.fixture
def series_dir(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    make_series(d)
    return d


def test_slices_are_ordered_by_position(series_dir):
    items = next(iter(group_series(series_dir).values()))
    z = [float(ds.ImagePositionPatient[2]) for _, ds in order_slices(items)]
    assert z == sorted(z)


def test_audit_finds_identifiers_and_no_geometry_issue(series_dir):
    uid, items = next(iter(group_series(series_dir).items()))
    row = audit_series(uid, items)
    assert row["identifying_tags_filled"] >= 3 and row["private_tags"] == 1
    assert row["issues"] == "none" and row["slice_step_mm"] == 2.5


def test_audit_flags_missing_slice(tmp_path):
    d = tmp_path / "gap"
    d.mkdir()
    make_series(d, n=6)
    victim = next(p for p in d.iterdir() if float(pydicom.dcmread(p).ImagePositionPatient[2]) == 5.0)
    victim.unlink()
    uid, items = next(iter(group_series(d).items()))
    assert "missing slices" in audit_series(uid, items)["issues"]


def test_conversion_matches_independent_reader(series_dir, tmp_path):
    items = next(iter(group_series(series_dir).values()))
    row = convert_series(items, tmp_path / "out.nii.gz")
    assert row["max_abs_diff_hu"] == 0.0 and row["z_spacing_matches_positions"]
    assert row["hu_min"] == 0.0 and row["hu_max"] == 50.0


def test_anonymise_and_verify(series_dir, tmp_path):
    anon = Anonymiser("test-salt")
    out = tmp_path / "anon"
    for p in series_dir.iterdir():
        ds = anon.apply(pydicom.dcmread(p))
        target = out / ds.SeriesInstanceUID[-8:] / p.name
        target.parent.mkdir(parents=True, exist_ok=True)
        ds.save_as(target, enforce_file_format=True)
    checks, problems = verify(series_dir, out)
    assert not problems and checks["pixels_identical"] and checks["series_sizes_match"]

    ds = pydicom.dcmread(next(out.rglob("*.dcm")))
    assert ds.PatientID.startswith("SUBJ-") and "InstitutionName" not in ds
    assert ds.StudyDate < "20200315" and ds.AccessionNumber == ""


def test_uid_and_date_mapping_is_consistent():
    a = Anonymiser("salt")
    assert a.new_uid("1.2.3") == a.new_uid("1.2.3") != a.new_uid("1.2.4")
    assert a.date_shift("p1") == a.date_shift("p1") < 0
    assert Anonymiser("other").new_uid("1.2.3") != a.new_uid("1.2.3")

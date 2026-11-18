"""
De-identification following the DICOM Basic Application Level Confidentiality
Profile (PS3.15 Annex E), with two options:
- Retain Longitudinal Temporal Information with Modified Dates (dates shifted per patient)
- Retain Patient Characteristics (age, sex, size, weight kept)

UIDs are replaced with deterministic 2.25 UIDs derived from a secret salt, so
references between studies, series and instances stay consistent. The mapping
from original to pseudonymous patient IDs is written to a separate file that
must never be shared with the data.

This covers the header. Pixel data is copied unchanged; burned-in text must be
checked separately (CT axial images rarely carry it, radiographs often do).

    python src/anonymise.py IN_DIR OUT_DIR --salt-file salt.txt --map private/map.csv
"""

import argparse
import csv
import datetime as dt
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid

# action "X": remove
REMOVE = [
    "OtherPatientIDs", "OtherPatientIDsSequence", "OtherPatientNames", "PatientAddress",
    "PatientTelephoneNumbers", "PatientMotherBirthName", "PatientBirthName", "MilitaryRank",
    "BranchOfService", "MedicalRecordLocator", "Occupation", "AdditionalPatientHistory",
    "PatientComments", "PatientInsurancePlanCodeSequence", "PatientReligiousPreference",
    "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "ReferringPhysicianAddress", "ReferringPhysicianTelephoneNumbers",
    "PhysiciansOfRecord", "PerformingPhysicianName", "NameOfPhysiciansReadingStudy",
    "OperatorsName", "RequestingPhysician", "StationName", "DeviceSerialNumber",
    "ImageComments", "StudyComments", "RequestAttributesSequence", "AdmittingDiagnosesDescription",
    "IssuerOfPatientID", "PatientState", "CurrentPatientLocation", "ProtocolName",
]
# action "Z": keep the element, empty it
EMPTY = ["ReferringPhysicianName", "AccessionNumber", "StudyID"]
# date and time elements that are shifted (Modified Dates option)
DATES = ["StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate", "PatientBirthDate",
         "InstanceCreationDate"]
UID_TAGS = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "FrameOfReferenceUID",
            "ReferencedSOPInstanceUID", "MediaStorageSOPInstanceUID"]


class Anonymiser:
    def __init__(self, salt: str, max_shift_days: int = 365):
        self.salt = salt
        self.max_shift = max_shift_days
        self.patients = {}

    def _hash(self, text):
        return hashlib.sha256(f"{self.salt}|{text}".encode()).hexdigest()

    def pseudonym(self, patient_id):
        if patient_id not in self.patients:
            self.patients[patient_id] = "SUBJ-" + self._hash(patient_id)[:10].upper()
        return self.patients[patient_id]

    def date_shift(self, patient_id):
        """Same negative offset for every date of one patient, so intervals are kept."""
        return -(int(self._hash("shift" + patient_id)[:8], 16) % self.max_shift + 1)

    def new_uid(self, uid):
        return generate_uid(entropy_srcs=[self.salt, str(uid)])

    def _remap_uids(self, ds: Dataset):
        for el in ds.iterall():
            if el.VR == "UI" and el.keyword in UID_TAGS and el.value:
                el.value = self.new_uid(el.value)

    def apply(self, ds: Dataset) -> Dataset:
        original_id = str(ds.get("PatientID", ""))
        shift = dt.timedelta(days=self.date_shift(original_id))

        for kw in REMOVE:
            if kw in ds:
                delattr(ds, kw)
        for kw in EMPTY:
            if kw in ds:
                ds.data_element(kw).value = ""
        for kw in DATES:
            if kw in ds and ds.data_element(kw).value:
                d = dt.datetime.strptime(str(ds.data_element(kw).value)[:8], "%Y%m%d").date()
                ds.data_element(kw).value = (d + shift).strftime("%Y%m%d")

        ds.PatientName = self.pseudonym(original_id)
        ds.PatientID = self.pseudonym(original_id)
        ds.remove_private_tags()
        for group in range(0x6000, 0x6020, 2):  # overlays and curves
            for el in [e for e in ds if e.tag.group == group]:
                del ds[el.tag]
        self._remap_uids(ds)
        if hasattr(ds, "file_meta") and "MediaStorageSOPInstanceUID" in ds.file_meta:
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

        ds.PatientIdentityRemoved = "YES"
        ds.DeidentificationMethod = "PS3.15 E Basic Profile; dates shifted; characteristics kept"
        codes = []
        for value, meaning in [("113100", "Basic Application Confidentiality Profile"),
                               ("113107", "Retain Longitudinal Temporal Information Modified Dates Option"),
                               ("113108", "Retain Patient Characteristics Option")]:
            c = Dataset()
            c.CodeValue, c.CodingSchemeDesignator, c.CodeMeaning = value, "DCM", meaning
            codes.append(c)
        ds.DeidentificationMethodCodeSequence = Sequence(codes)
        return ds


def main():
    parser = argparse.ArgumentParser(description="De-identify a folder of DICOM files")
    parser.add_argument("in_dir")
    parser.add_argument("out_dir")
    parser.add_argument("--salt-file", required=True, help="file holding a secret salt; keep it private")
    parser.add_argument("--map", required=True, help="CSV for the patient ID mapping; keep it private")
    args = parser.parse_args()

    anon = Anonymiser(Path(args.salt_file).read_text().strip())
    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    n = 0
    for p in sorted(in_dir.rglob("*")):
        if not p.is_file():
            continue
        try:
            ds = pydicom.dcmread(p)
        except Exception:
            continue
        ds = anon.apply(ds)
        out = out_dir / ds.PatientID / ds.SeriesInstanceUID[-16:] / f"{ds.SOPInstanceUID[-16:]}.dcm"
        out.parent.mkdir(parents=True, exist_ok=True)
        ds.save_as(out, enforce_file_format=True)
        n += 1

    Path(args.map).parent.mkdir(parents=True, exist_ok=True)
    with open(args.map, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["original_patient_id", "pseudonym"])
        w.writerows(sorted(anon.patients.items()))
    print(f"de-identified {n} files for {len(anon.patients)} patients into {out_dir}")


if __name__ == "__main__":
    main()

# ct-dicom-qc

Audit, convert and de-identify CT DICOM series, with checks that each step did what it claims.

Tested on six lower-limb CT series (1,690 files) from the public TCIA Soft-tissue-Sarcoma collection.
Design choices and what the data showed: [docs/NOTES.md](docs/NOTES.md).

## What it does

| Step | Script | Check |
|---|---|---|
| Header audit | `src/audit.py` | One row per series: geometry, rescale, photometric interpretation, identifying and private tags (counted, never printed), and issues such as missing slices, uneven or overlapping slices, gantry tilt, missing rescale, MONOCHROME1, burned-in annotation. |
| Conversion | `src/convert.py` | DICOM series to NIfTI with SimpleITK, compared voxel by voxel with an independent pydicom reader that orders slices along the slice normal and applies the modality LUT itself. |
| De-identification | `src/anonymise.py` | DICOM PS3.15 Annex E Basic Application Level Confidentiality Profile, with the Modified Dates and Retain Patient Characteristics options. |
| Verification | `src/verify.py` | Compares the de-identified folder with its source. |

### De-identification details

- Removes the profile's "X" elements (addresses, physicians, institution, device serial number, comments, and others) and empties the "Z" elements (accession number, study ID, referring physician).
- Replaces patient name and ID with a pseudonym derived from a secret salt; the mapping is written to a separate file that must not travel with the data.
- Shifts all dates of one patient by the same random number of days, so intervals between studies are kept.
- Replaces study, series, instance and frame-of-reference UIDs with deterministic `2.25` UIDs, including references inside sequences, so links between files survive.
- Removes private tags and overlay groups; sets `PatientIdentityRemoved` and the de-identification method code sequence.
- Pixel data is copied unchanged. Burned-in text is not handled: it is rare on axial CT and common on radiographs and screenshots, where it needs a separate check.

## Results on the TCIA series

Header audit (`results/audit.csv`):
- All six series are axial, 512 x 512, 0.977 mm pixels, from one manufacturer at 140 kVp.
- Slice thickness 3.75 mm at a 3.27 mm step: every series is an overlapping reconstruction, which matters for resampling and for any slice-thickness assumption.
- Three series store HU directly (intercept 0); three use an intercept of -1024. Reading raw pixel arrays without the modality LUT would shift half of this data by 1024 HU.
- Two series saturate at 3071 HU, the top of the 12-bit range, so very dense bone or metal is clipped.
- The data is already de-identified by TCIA, but 2 to 3 identifying elements per series are filled with TCIA pseudonyms and each file carries 4 private tags.

Conversion (`results/conversion.csv`): for all six series the SimpleITK volume and the independent pydicom stack agree exactly (maximum difference 0 HU), and the z spacing equals the step between slice positions.

De-identification: 1,690 files, 6 patients.

```
files: (1690, 1690)
series_sizes_match: True
pixels_identical: True
header_problems: 0
PASS
```

## Usage

```bash
pip install -e ".[dev]"
pytest                                       # synthetic series, no data needed

python src/audit.py DATA_DIR --out results/audit.csv
python src/convert.py DATA_DIR OUT_DIR --report results/conversion.csv
python -c "import secrets; print(secrets.token_hex(32))" > private/salt.txt
python src/anonymise.py DATA_DIR ANON_DIR --salt-file private/salt.txt --map private/map.csv
python src/verify.py DATA_DIR ANON_DIR

# Or run the synthetic test suite inside Docker
docker build -t ct-dicom-qc . && docker run --rm ct-dicom-qc
```

Tests build a small CT series with pydicom (shuffled file order, unrelated instance numbers, identifying and private tags) and check slice ordering, gap detection, the conversion cross-check, and the de-identification round trip.

## Getting the data

The series came from the TCIA REST API, which needs no account for public collections:

```bash
curl -o series.zip "https://services.cancerimagingarchive.net/nbia-api/services/v1/getImage?SeriesInstanceUID=<UID>"
```

Series used (patient IDs as published by TCIA): STS_001, STS_006, STS_008, STS_010, STS_013, STS_043.
See the collection page for its licence and the required citation (Vallieres et al., Physics in Medicine and Biology, 2015).
No images or derived volumes are stored in this repository.

## Limitations

- Header-level de-identification only; no OCR for burned-in text.
- The profile subset covers the elements found in CT; other modalities and structured reports carry more.
- Tested on one manufacturer.

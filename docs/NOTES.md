# Notes

Why the tool works the way it does, and what the six TCIA series showed.
Results and usage are in the [README](../README.md).

## Why

Before CT data can train a model or leave a hospital, three things have to be true: the slices are read in the right order and in the right units, the volume written to disk matches the DICOM, and no identifying header survives.
Each step here has its own check, so a failure shows up as a number rather than a silent error.

## Decisions

- **Slice order from geometry, not file names.** Slices are sorted by `ImagePositionPatient` projected on the slice normal. File names and `InstanceNumber` are often out of order in exports, and the tests shuffle both on purpose.
- **Two independent readers.** SimpleITK writes the NIfTI; a separate pydicom reader rebuilds the same volume from the raw tags. If they disagree by even 1 HU, the conversion is wrong.
- **Basic profile with two options.** PS3.15 Annex E removes or empties the listed elements. Dates are shifted per patient instead of removed, so follow-up intervals survive; age, sex, height and weight are kept because they matter for bone studies.
- **Deterministic pseudonyms.** Patient IDs and UIDs are derived from a secret salt, so the same patient gets the same pseudonym across runs and references between series still resolve. The salt and the ID map live outside the repository.
- **Verification as a separate step.** `verify.py` compares the output with the input instead of trusting the anonymiser: file counts, series sizes, pixel hashes and any identifying element left.

## What the data showed

- All six series are overlapping reconstructions (3.75 mm slices at a 3.27 mm step). Code that assumes slice thickness equals spacing would resample them wrongly.
- Three series store HU directly and three use an intercept of -1024. Reading the pixel array without the rescale tags would shift half the data by 1024 HU.
- Two series clip at 3071 HU, the top of the 12-bit range, so dense cortical bone or metal can saturate.
- Even data already de-identified by TCIA still carried filled identifying elements (TCIA pseudonyms) and four private tags per file.

## Limits and next steps

- Burned-in text in pixels is not handled. It is rare on axial CT but common on radiographs and screen captures, which need an OCR check.
- Only CT from one manufacturer was tested; MRI and radiographs carry other identifying elements.
- A next step is to run the same audit on the knee MRI and lower-limb radiograph collections.

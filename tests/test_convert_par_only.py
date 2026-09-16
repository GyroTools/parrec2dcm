from pathlib import Path

import pydicom
import pytest

from parrec2dcm import convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "single_slice"


def test_classic_matches_reference_geometry(tmp_path):
    written = convert(FIXTURE_DIR / "scan.par", tmp_path, output_format="classic")
    assert len(written) == 1
    assert written[0].parent == tmp_path  # no nested "DICOM" subfolder

    ds = pydicom.dcmread(written[0])
    ref = pydicom.dcmread(FIXTURE_DIR / "reference.dcm")

    assert ds.SOPClassUID == "1.2.840.10008.5.1.4.1.1.4"
    assert ds.Rows == ref.Rows
    assert ds.Columns == ref.Columns
    assert list(ds.PixelSpacing) == pytest.approx([float(x) for x in ref.PixelSpacing], abs=1e-6)
    assert list(ds.ImageOrientationPatient) == pytest.approx(
        [float(x) for x in ref.ImageOrientationPatient], abs=1e-4
    )
    assert list(ds.ImagePositionPatient) == pytest.approx(
        [float(x) for x in ref.ImagePositionPatient], abs=1e-2
    )


def test_classic_and_enhanced_pixel_data_match(tmp_path):
    classic_written = convert(
        FIXTURE_DIR / "scan.par", tmp_path / "classic", output_format="classic"
    )
    enhanced_written = convert(
        FIXTURE_DIR / "scan.par", tmp_path / "enhanced", output_format="enhanced"
    )

    classic = pydicom.dcmread(classic_written[0])
    enhanced = pydicom.dcmread(enhanced_written[0])

    # Legacy Converted Enhanced MR Image Storage -- the SOP Class highdicom's
    # legacy-conversion route actually produces (PS3.3 Annex A.71), distinct
    # from "native" Enhanced MR Image Storage (...4.1).
    assert enhanced.SOPClassUID == "1.2.840.10008.5.1.4.1.1.4.4"
    assert enhanced.NumberOfFrames == 1
    assert (enhanced.pixel_array == classic.pixel_array).all()


def test_output_round_trips_through_pydicom(tmp_path):
    written = convert(FIXTURE_DIR / "scan.par", tmp_path, output_format="classic")
    ds = pydicom.dcmread(written[0])
    assert ds.pixel_array.shape == (ds.Rows, ds.Columns)

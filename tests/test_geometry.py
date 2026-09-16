import math

import pytest

from parrec2dcm.geometry import _image_type, image_orientation_patient, image_position_patient

TRANSVERSAL = 1
SAGITTAL = 2
CORONAL = 3


def test_image_type_distinguishes_dixon_water_and_fat():
    # Regression test for a real-world bug: image_type_mr codes beyond the
    # commonly-known 0-3 (M/R/I/P) range -- including Dixon water (34) and
    # fat (37) -- used to collapse to the same default "M" label, making
    # water and fat images at the same slice indistinguishable downstream
    # (confirmed against a real Dixon dataset: alternating slices from two
    # different contrasts were treated as duplicates and half the data was
    # dropped).
    water_letter, water_type = _image_type(34, "T1TFE")
    fat_letter, fat_type = _image_type(37, "T1TFE")
    assert water_letter == "W"
    assert fat_letter == "F"
    assert water_type != fat_type


def test_image_type_unknown_code_gets_distinct_label_not_default_m():
    letter, _ = _image_type(9999, "T1TFE")
    assert letter == "T9999"


def test_zero_angulation_transversal_is_identity():
    iop = image_orientation_patient((0.0, 0.0, 0.0), TRANSVERSAL)
    assert iop == pytest.approx([1, 0, 0, 0, 1, 0], abs=1e-9)


def test_matches_reference_dicom_orientation():
    # Real values from tests/fixtures/single_slice/scan.par, cross-checked
    # against tests/fixtures/single_slice/reference.dcm's actual
    # ImageOrientationPatient/ImagePositionPatient during development.
    angulation_ap_fh_rl = (0.0, 1.48, 0.55)
    iop = image_orientation_patient(angulation_ap_fh_rl, CORONAL)
    expected = [
        0.9996664015514872,
        0.025826810511652778,
        0.0002479271985712826,
        0.0,
        0.009599163462400142,
        -0.999953926969049,
    ]
    assert iop == pytest.approx(expected, abs=1e-9)

    ipp = image_position_patient(
        angulation_ap_fh_rl,
        CORONAL,
        offcentre_ap_fh_rl=(-28.593, 17.369, -3.678),
        pixel_spacing_xy=(0.625, 0.625),
        recon_resolution_xy=(512, 512),
    )
    expected_ipp = [-163.62462424823795, -34.26115583584847, 177.3219599632764]
    assert ipp == pytest.approx(expected_ipp, abs=1e-6)


def test_direction_cosines_are_unit_vectors():
    iop = image_orientation_patient((5.0, -10.0, 15.0), SAGITTAL)
    row = iop[:3]
    col = iop[3:]
    row_norm = math.sqrt(sum(c * c for c in row))
    col_norm = math.sqrt(sum(c * c for c in col))
    assert row_norm == pytest.approx(1.0, abs=1e-9)
    assert col_norm == pytest.approx(1.0, abs=1e-9)

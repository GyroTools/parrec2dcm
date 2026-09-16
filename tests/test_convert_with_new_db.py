import warnings
from pathlib import Path

import pydicom

from parrec2dcm import convert

PAR_FIXTURE = Path(__file__).parent / "fixtures" / "single_slice" / "scan.par"
DB_R11 = Path(__file__).parent / "fixtures" / "database" / "db_r11.json"
DB_R5 = Path(__file__).parent / "fixtures" / "database" / "db_r5.json"


def test_new_format_db_overrides_identifiers_without_warnings(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        written = convert(
            PAR_FIXTURE, tmp_path, output_format="classic", params=[DB_R11]
        )

    ds = pydicom.dcmread(written[0])
    # DB-sourced PatientID/PatientBirthDate/PatientSex should win over the
    # PAR-only defaults ("20000101"/"O"/synthesized ID).
    assert ds.PatientID == "DIDC-503-T01"
    assert ds.PatientBirthDate != "20000101"
    assert ds.PatientSex in ("F", "M", "O")


def test_new_format_db_does_not_clobber_per_image_geometry(tmp_path):
    written_plain = convert(PAR_FIXTURE, tmp_path / "plain", output_format="classic")
    written_db = convert(
        PAR_FIXTURE, tmp_path / "with_db", output_format="classic", params=[DB_R11]
    )

    ds_plain = pydicom.dcmread(written_plain[0])
    ds_db = pydicom.dcmread(written_db[0])

    # Per-image dynamic tags come only from PAR and must be identical
    # regardless of whether a DB export was supplied.
    assert list(ds_plain.ImagePositionPatient) == list(ds_db.ImagePositionPatient)
    assert list(ds_plain.ImageOrientationPatient) == list(ds_db.ImageOrientationPatient)
    assert ds_plain.Rows == ds_db.Rows
    assert ds_plain.Columns == ds_db.Columns


def test_enhanced_mode_with_new_format_db(tmp_path):
    written = convert(PAR_FIXTURE, tmp_path, output_format="enhanced", params=[DB_R11])
    ds = pydicom.dcmread(written[0])
    assert ds.SOPClassUID == "1.2.840.10008.5.1.4.1.1.4.4"
    assert ds.PatientID == "DIDC-503-T01"


def test_old_format_db_overrides_identifiers_without_warnings(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        written = convert(PAR_FIXTURE, tmp_path, output_format="classic", params=[DB_R5])

    ds = pydicom.dcmread(written[0])
    # DB-sourced values should win over the PAR-only defaults
    # ("20000101"/synthesized ID) -- see tests/fixtures/database/db_r5.json.
    assert ds.PatientID == "mb11111"
    assert ds.PatientBirthDate == "20010101"
    assert ds.Manufacturer == "Philips Medical Systems"
    assert ds.InstitutionName == "Universitaetsspital Zuerich"


def test_old_format_db_does_not_clobber_per_image_geometry(tmp_path):
    written_plain = convert(PAR_FIXTURE, tmp_path / "plain", output_format="classic")
    written_db = convert(
        PAR_FIXTURE, tmp_path / "with_db", output_format="classic", params=[DB_R5]
    )

    ds_plain = pydicom.dcmread(written_plain[0])
    ds_db = pydicom.dcmread(written_db[0])

    assert list(ds_plain.ImagePositionPatient) == list(ds_db.ImagePositionPatient)
    assert list(ds_plain.ImageOrientationPatient) == list(ds_db.ImageOrientationPatient)
    assert ds_plain.Rows == ds_db.Rows
    assert ds_plain.Columns == ds_db.Columns


def test_enhanced_mode_with_old_format_db(tmp_path):
    written = convert(PAR_FIXTURE, tmp_path, output_format="enhanced", params=[DB_R5])
    ds = pydicom.dcmread(written[0])
    assert ds.SOPClassUID == "1.2.840.10008.5.1.4.1.1.4.4"
    assert ds.PatientID == "mb11111"

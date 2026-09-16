from pathlib import Path

from parrec2dcm.database.new_format import extract_tag, new_format_tags
from parrec2dcm.database.records import ParameterPool, load_parameter_pool

FIXTURE = Path(__file__).parent / "fixtures" / "database" / "db_r11.json"


def test_extract_tag_simple():
    assert extract_tag("RFR_SERIES_tag_00180091") == (0x0018, 0x0091)


def test_extract_tag_vendor_prefixed():
    assert extract_tag("RFR_STUDY_tag_Philips_Imaging_DD_002_200100b6") == (0x2001, 0x00B6)
    assert extract_tag("RFR_SERIES_tag_ELSCINT1_00e10007") == (0x00E1, 0x0007)


def test_extract_tag_rejects_bookkeeping_names():
    assert extract_tag("RFR_PATIENT_objOid") is None
    assert extract_tag("RFR_STUDY_uid") is None
    assert extract_tag("not_a_tag_name_at_all") is None


def test_new_format_tags_against_real_fixture():
    pool = load_parameter_pool([FIXTURE])
    resolved = new_format_tags(pool)

    # High resolution rate: most tag-shaped records should resolve (a
    # couple are deliberately excluded -- SOPClassUID/SOPInstanceUID --
    # and a handful of others get dropped by best-effort VR/value
    # validation; see new_format.py's module docstring).
    tag_shaped = sum(1 for n in pool.names() if "tag_" in n)
    assert len(resolved) / tag_shaped > 0.85

    by_address = {(t.group, t.element): t for t in resolved}

    # File-identity tags must never come from the DB overlay.
    assert (0x0008, 0x0016) not in by_address  # SOPClassUID
    assert (0x0008, 0x0018) not in by_address  # SOPInstanceUID

    # A real standard tag resolves with a sensible VR and value.
    patient_id = by_address.get((0x0010, 0x0020))
    assert patient_id is not None
    assert patient_id.vr == "LO"
    assert patient_id.value

    # A DA-VR tag ends up in proper DICOM DA format (8 digits), not the
    # source export's own "YYYY/MM/DD"-style formatting.
    birth_date = by_address.get((0x0010, 0x0030))
    assert birth_date is not None
    assert birth_date.vr == "DA"
    assert len(birth_date.value) == 8
    assert birth_date.value.isdigit()


def test_number_of_temporal_positions_excluded_from_overlay():
    # Real-world regression: a DB export's own NumberOfTemporalPositions
    # can itself be wrong (e.g. a cardiac-cine series reporting "1"
    # despite 20 real temporal positions) -- this tag must stay whatever
    # parrec2dcm itself computes to match the per-image
    # TemporalPositionIdentifier values it assigns, never a DB snapshot.
    pool = ParameterPool(
        [{"Name": "RFR_IMAGE_tag_00200105", "Value": "1", "Properties": {"Type": "String"}}]
    )
    resolved = new_format_tags(pool)
    assert (0x0020, 0x0105) not in {(t.group, t.element) for t in resolved}

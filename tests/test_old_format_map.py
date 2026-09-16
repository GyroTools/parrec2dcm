from pathlib import Path

from parrec2dcm.database.old_format_map import _OLD_FORMAT_ENTRIES, old_format_tags
from parrec2dcm.database.records import ParameterPool, load_parameter_pool

FIXTURE = Path(__file__).parent / "fixtures" / "database" / "db_r5.json"


def test_old_format_entries_table_size():
    # Loose sanity bound on the extracted table itself -- catches a badly
    # broken extraction (e.g. an empty or truncated table) without being
    # brittle to the exact count. A handful of exact-duplicate entries
    # (same address, same single db_name) are expected: the source file
    # itself sets e.g. PatientWeight/SliceThickness/SAR from the same DB
    # parameter twice, verbatim -- harmless redundancy in the original,
    # not an extraction bug (see module docstring for the real fidelity
    # checks: a grep-count cross-check and a 20-entry hand spot-check).
    assert 450 <= len(_OLD_FORMAT_ENTRIES) <= 500


def test_old_format_tags_against_real_fixture():
    pool = load_parameter_pool([FIXTURE])
    resolved = old_format_tags(pool)

    # A real, sizeable chunk of the table resolves against a genuine
    # REL5-era export (the rest are legitimately absent -- goal
    # parameters like RC_slice_thickness/AC_act_SAR aren't part of a
    # database-only export -- or blank/NULL in this particular dataset).
    assert len(resolved) > 200

    by_address = {(t.group, t.element): t for t in resolved}

    patient_id = by_address.get((0x0010, 0x0020))
    assert patient_id is not None
    assert patient_id.value == "mb11111"

    manufacturer = by_address.get((0x0008, 0x0070))
    assert manufacturer is not None
    assert manufacturer.value == "Philips Medical Systems"

    # File-identity tags must never come from the DB overlay (excluded
    # via ALWAYS_EXCLUDED_TAGS, same as new_format.py).
    assert (0x0008, 0x0016) not in by_address  # SOPClassUID
    assert (0x0008, 0x0018) not in by_address  # SOPInstanceUID
    assert (0x0020, 0x0105) not in by_address  # NumberOfTemporalPositions


def test_multi_name_entry_combines_into_one_multivalue():
    # ChemicalShiftReference0/1 -> (0018,9053), a 2-component DS value --
    # mirrors MATLAB's D.get_db_value({'A','B'}) cell-array combination.
    pool = ParameterPool(
        [
            {
                "Name": "RFR_SERIES_DICOM_CHEMICAL_SHIFT_REFERENCE0",
                "Value": "4.68",
                "Properties": {"Type": "Float"},
            },
            {
                "Name": "RFR_SERIES_DICOM_CHEMICAL_SHIFT_REFERENCE1",
                "Value": "4.68",
                "Properties": {"Type": "Float"},
            },
        ]
    )
    resolved = old_format_tags(pool)
    tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9053))
    assert list(tag.value) == [4.68, 4.68]


def test_missing_source_name_skips_entry_without_partial_value():
    # A multi-name entry with only ONE of its two names present must not
    # produce a partial/malformed multi-value -- matches MATLAB's own
    # try/catch-to-NaN behavior when GetParameter fails on a missing name.
    pool = ParameterPool(
        [
            {
                "Name": "RFR_SERIES_DICOM_CHEMICAL_SHIFT_REFERENCE0",
                "Value": "4.68",
                "Properties": {"Type": "Float"},
            }
        ]
    )
    resolved = old_format_tags(pool)
    assert (0x0018, 0x9053) not in {(t.group, t.element) for t in resolved}


def test_inversion_recovery_yes_no():
    pool_n = ParameterPool(
        [{"Name": "RFR_SERIES_PIIM_MR_SERIES_SEL_PART_INVERSION_RECOVERY", "Value": "N"}]
    )
    pool_y = ParameterPool(
        [{"Name": "RFR_SERIES_PIIM_MR_SERIES_SEL_PART_INVERSION_RECOVERY", "Value": "Y"}]
    )
    tag_n = next(t for t in old_format_tags(pool_n) if (t.group, t.element) == (0x0018, 0x9009))
    tag_y = next(t for t in old_format_tags(pool_y) if (t.group, t.element) == (0x0018, 0x9009))
    assert tag_n.value == "NO"
    assert tag_y.value == "YES"


def test_spatial_presaturation_none_slab():
    pool_n = ParameterPool([{"Name": "RFR_SERIES_PIIM_MR_SPATIAL_PRESATURATION", "Value": "N"}])
    pool_y = ParameterPool([{"Name": "RFR_SERIES_PIIM_MR_SPATIAL_PRESATURATION", "Value": "Y"}])
    tag_n = next(t for t in old_format_tags(pool_n) if (t.group, t.element) == (0x0018, 0x9027))
    tag_y = next(t for t in old_format_tags(pool_y) if (t.group, t.element) == (0x0018, 0x9027))
    assert tag_n.value == "NONE"
    assert tag_y.value == "SLAB"

from pathlib import Path

from parrec2dcm.database.goal_params import goal_derived_tags
from parrec2dcm.database.records import ParameterPool, load_parameter_pool

DB_R5 = Path(__file__).parent / "fixtures" / "database" / "db_r5.json"
GOAL_R11 = Path(__file__).parent / "fixtures" / "database" / "goal_r11.json"
GOAL_R5 = Path(__file__).parent / "fixtures" / "database" / "goal_r5.json"


def test_goal_derived_tags_noop_without_gate_parameter():
    # EX_ACQ_imaging_sequence absent -- must return nothing, matching
    # dicom_get_static_values53's own IsParameter gate.
    pool = ParameterPool([{"Name": "VAL01_FFE_contrast_enh", "Value": 1}])
    assert goal_derived_tags(pool) == []


def test_goal_derived_tags_against_real_fixture():
    pool = load_parameter_pool([DB_R5, GOAL_R11])
    resolved = goal_derived_tags(pool)
    assert len(resolved) > 30

    by_address = {(t.group, t.element): t for t in resolved}

    steady_state = by_address.get((0x0018, 0x9017))
    assert steady_state is not None
    assert steady_state.value in {"NONE", "LONGITUDINAL", "TIME_REVERSE", "FREE_PRECESSION"}

    field_strength = by_address.get((0x0018, 0x0087))
    assert field_strength is not None
    assert field_strength.vr == "DS"

    # AcquisitionContrast/PS_volume_geom_types/PS_slab_orientations are
    # deliberately not portable (see module docstring) -- must never be
    # written from this module.
    assert (0x0008, 0x9209) not in by_address  # AcquisitionContrast
    assert (0x2005, 0x105D) not in by_address  # PS_volume_geom_types
    assert (0x2005, 0x105E) not in by_address  # PS_slab_orientations


def test_steady_state_pulse_sequence_enum_decode():
    base = {"Name": "EX_ACQ_imaging_sequence", "Value": 1}
    cases = [(0, "NONE"), (1, "LONGITUDINAL"), (2, "TIME_REVERSE"), (3, "FREE_PRECESSION")]
    for code, expected in cases:
        pool = ParameterPool([base, {"Name": "VAL01_FFE_contrast_enh", "Value": code}])
        resolved = goal_derived_tags(pool)
        tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9017))
        assert tag.value == expected


def test_tagging_reads_dimension_only_when_ctagging_active():
    base = {"Name": "EX_ACQ_imaging_sequence", "Value": 1}

    inactive = ParameterPool([base, {"Name": "VAL01_TAG_ctagging", "Value": 0}])
    resolved = goal_derived_tags(inactive)
    tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9028))
    assert tag.value == "NONE"

    active = ParameterPool(
        [
            base,
            {"Name": "VAL01_TAG_ctagging", "Value": 1},
            {"Name": "VAL01_TAG_dimension", "Value": 1},
        ]
    )
    resolved = goal_derived_tags(active)
    tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9028))
    assert tag.value == "GRID"


def test_parallel_acquisition_technique_multiband_only_when_present():
    base = [
        {"Name": "EX_ACQ_imaging_sequence", "Value": 1},
        {"Name": "VAL01_GEO_sense_enable", "Value": 1},
    ]

    without_mb = ParameterPool(base)
    resolved = goal_derived_tags(without_mb)
    tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9078))
    assert tag.value == "SENSE"

    with_mb = ParameterPool([*base, {"Name": "VAL01_ACQ_MB", "Value": 1}])
    resolved = goal_derived_tags(with_mb)
    tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9078))
    assert tag.value == "MULTIBAND"


def test_receive_coil_type_only_resolves_numeric_cases():
    base = {"Name": "EX_ACQ_imaging_sequence", "Value": 1}

    multicoil = ParameterPool([base, {"Name": "RC_receive_coil_types", "Value": [3, 0]}])
    resolved = goal_derived_tags(multicoil)
    tag = next(t for t in resolved if (t.group, t.element) == (0x0018, 0x9043))
    assert tag.value == "MULTICOIL"

    unresolvable = ParameterPool([base, {"Name": "RC_receive_coil_types", "Value": [7, 0]}])
    resolved = goal_derived_tags(unresolvable)
    assert (0x0018, 0x9043) not in {(t.group, t.element) for t in resolved}


def test_goal_derived_tags_work_against_r5_fixture_too():
    pool = load_parameter_pool([DB_R5, GOAL_R5])
    resolved = goal_derived_tags(pool)
    assert len(resolved) > 30

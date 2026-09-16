from parrec2dcm.database.format_detect import (
    DatabaseTier,
    detect_database_tier,
    goal_parameters_available,
)
from parrec2dcm.database.records import ParameterPool


def _pool(*names):
    return ParameterPool({"Name": n, "Value": "x"} for n in names)


def test_no_params_means_none_tier():
    assert detect_database_tier(_pool()) is DatabaseTier.NONE


def test_new_tier_detected():
    assert detect_database_tier(_pool("RFR_SERIES_objOid")) is DatabaseTier.NEW


def test_old_tier_detected():
    assert detect_database_tier(_pool("RFR_EXAM_OBJECT_OID")) is DatabaseTier.OLD


def test_new_tier_takes_precedence_if_both_markers_present():
    assert (
        detect_database_tier(_pool("RFR_SERIES_objOid", "RFR_EXAM_OBJECT_OID"))
        is DatabaseTier.NEW
    )


def test_goal_parameters_detection():
    assert not goal_parameters_available(_pool())
    assert goal_parameters_available(_pool("EX_ACQ_imaging_sequence"))

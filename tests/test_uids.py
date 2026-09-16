from pathlib import Path

from parrec2dcm.source.parfile import ParFile
from parrec2dcm.uids import build_identifiers


def _stub_parfile() -> ParFile:
    return ParFile(
        path=Path("stub.par"),
        general={
            "PatientName": "Te",
            "ProtocolName": "TestProtocol",
            "ExaminationName": "TestExam",
            "ExaminationDateTime": "2020.01.02  /  03:04:5",
            "AcquisitionNr": 1,
            "ReconstructionNr": 1,
        },
        images=[{"SliceOrientation": 1}],
    )


def test_deterministic_by_default():
    par = _stub_parfile()
    a = build_identifiers(par, randomize=False)
    b = build_identifiers(par, randomize=False)
    assert a.study_uid == b.study_uid
    assert a.series_uid == b.series_uid
    assert a.frame_of_reference_uid == b.frame_of_reference_uid
    assert a.patient_id == b.patient_id
    assert a.sop_instance_uid(0) == b.sop_instance_uid(0)


def test_different_content_gives_different_uids():
    par_a = _stub_parfile()
    par_b = _stub_parfile()
    par_b.general["ProtocolName"] = "OtherProtocol"

    a = build_identifiers(par_a, randomize=False)
    b = build_identifiers(par_b, randomize=False)
    assert a.study_uid != b.study_uid
    assert a.patient_id != b.patient_id


def test_randomize_gives_fresh_uids_each_call():
    par = _stub_parfile()
    a = build_identifiers(par, randomize=True)
    b = build_identifiers(par, randomize=True)
    assert a.study_uid != b.study_uid
    assert a.series_uid != b.series_uid
    assert a.sop_instance_uid(0) != b.sop_instance_uid(0)

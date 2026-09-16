from pathlib import Path

from parrec2dcm.source.parfile import ParFile
from parrec2dcm.static_values import static_tags_from_parfile


def _par(**general_overrides):
    general = {
        "PatientName": "Te",
        "ProtocolName": "TestProtocol",
        "AcquisitionNr": 1,
        "ReconstructionNr": 1,
        "MaxNumberOfDynamics": 1,
        "MaxNumberOfCardiacPhases": 1,
    }
    general.update(general_overrides)
    return ParFile(path=Path("stub.par"), general=general, images=[{"SliceOrientation": 1}])


def test_plain_dynamic_scan_uses_dynamics_count():
    par = _par(MaxNumberOfDynamics=5, MaxNumberOfCardiacPhases=1)
    tags = static_tags_from_parfile(par)
    assert tags["NumberOfTemporalPositions"] == 5


def test_cardiac_cine_multiplies_dynamics_by_phases():
    # Matches the real-world bug fixed alongside geometry.py's
    # TemporalPositionIdentifier: NumberOfTemporalPositions must reflect
    # the actual number of distinct temporal positions we assign per
    # image (dynamics x cardiac phases), not just the dynamics count.
    par = _par(MaxNumberOfDynamics=1, MaxNumberOfCardiacPhases=20)
    tags = static_tags_from_parfile(par)
    assert tags["NumberOfTemporalPositions"] == 20


def test_cardiac_gated_dynamic_scan_combines_both():
    par = _par(MaxNumberOfDynamics=3, MaxNumberOfCardiacPhases=4)
    tags = static_tags_from_parfile(par)
    assert tags["NumberOfTemporalPositions"] == 12

from parrec2dcm.geometry import dynamic_tags_from_parfile

TRANSVERSAL = 1


def _image(dynamic_scan_number=1, cardiac_phase_number=1, **overrides):
    base = {
        "SliceNumber": 1,
        "EchoNumber": 1,
        "DynamicScanNumber": dynamic_scan_number,
        "CardiacPhaseNumber": cardiac_phase_number,
        "ImageTypeMr": 0,
        "ScanningSequence": 0,
        "IndexInRecFile": 0,
        "ImagePixelSize": 16,
        "ScanPercentage": 100,
        "ReconResolution": [64, 64],
        "RescaleIntercept": 0.0,
        "RescaleSlope": 1.0,
        "WindowCenter": 128,
        "WindowWidth": 256,
        "ImageAngulation": [0.0, 0.0, 0.0],
        "ImageOffcentre": [0.0, 0.0, 0.0],
        "SliceOrientation": TRANSVERSAL,
        "SliceThickness": 8.0,
        "SliceGap": 0.0,
        "FmriStatusIndication": 0,
        "PixelSpacing": [1.0, 1.0],
        "EchoTime": 5.0,
        "DynScanBeginTime": 0.0,
        "TriggerTime": 0.0,
        "NumberOfAverages": 1,
        "ImageFlipAngle": 60.0,
        "TurboFactor": 0,
        "InversionDelay": 0.0,
        "CardiacFrequency": 0,
        "MinRrInterval": 0,
        "MaxRrInterval": 0,
    }
    base.update(overrides)
    return base


def _temporal_position(image, first_image=None, max_cardiac_phases=1):
    tags = dynamic_tags_from_parfile(
        image, first_image or image, "TestTechnique", False, None, max_cardiac_phases
    )
    return tags["TemporalPositionIdentifier"]


def test_no_cardiac_gating_uses_dynamic_scan_number():
    # max_cardiac_phases == 1: plain dynamic-scan case, unchanged behavior.
    for dyn in (1, 2, 5):
        assert _temporal_position(_image(dynamic_scan_number=dyn), max_cardiac_phases=1) == dyn


def test_cardiac_cine_uses_cardiac_phase_number():
    # Single dynamic (dynamic_scan_number stays 1), 20 cardiac phases --
    # this is exactly the real-world bug: TemporalPositionIdentifier must
    # track the phase, not stay constant at 1 for every frame.
    for phase in range(1, 21):
        image = _image(dynamic_scan_number=1, cardiac_phase_number=phase)
        assert _temporal_position(image, max_cardiac_phases=20) == phase


def test_cardiac_gated_dynamic_scan_combines_both():
    # Both dimensions vary: one monotonic index across the full acquisition.
    max_phases = 4
    image = _image(dynamic_scan_number=2, cardiac_phase_number=3)
    # (dyn=2 - 1) * 4 phases + phase=3 -> 7th overall temporal position.
    assert _temporal_position(image, max_cardiac_phases=max_phases) == 7

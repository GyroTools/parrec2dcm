import copy

import pydicom
from highdicom.spatial import get_normal_vector

from parrec2dcm.pipeline import convert
from parrec2dcm.writer_enhanced import write_enhanced


def test_write_enhanced_allows_repeated_slice_positions(tmp_path):
    """Cardiac cine / multi-dynamic / multi-echo PAR/REC acquisitions repeat
    the same slice position across phases/dynamics/echoes -- not a single
    geometric volume. Regression test for the real-world failure this
    triggered (see git history): highdicom's require_volume=True rejects
    this outright, so write_enhanced must use require_volume=False.
    """
    # Build one real classic dataset from the fixture, then duplicate it
    # (same ImagePositionPatient, different SOPInstanceUID/InstanceNumber)
    # to simulate a second cardiac phase at the same slice location.
    convert(
        "tests/fixtures/single_slice/scan.par", tmp_path, output_format="classic"
    )
    classic_path = next(tmp_path.glob("IM_*"))
    ds1 = pydicom.dcmread(classic_path)
    ds2 = copy.deepcopy(ds1)
    ds2.InstanceNumber = 2
    ds2.SOPInstanceUID = pydicom.uid.generate_uid()
    ds2.file_meta.MediaStorageSOPInstanceUID = ds2.SOPInstanceUID

    assert ds1.ImagePositionPatient == ds2.ImagePositionPatient

    written = write_enhanced([[ds1, ds2]], tmp_path / "enhanced")
    assert len(written) == 1

    enhanced = pydicom.dcmread(written[0])
    assert enhanced.NumberOfFrames == 2


def test_write_enhanced_simple_volume_uses_in_stack_position_pointer(tmp_path):
    """Regression test for a real-world bug: a simple, regularly-spaced,
    single-contrast 3D volume (no repeated positions, so highdicom takes
    its own spatial-volume dimension-index branch, not the InstanceNumber
    fallback this package's other fixes target) still needs its declared
    DimensionIndexSequence pointer retargeted from ImagePositionPatient to
    InStackPositionNumber -- see dimension_index.fix_volume_stack_pointer
    and its module docstring for why. Confirmed against a real 311-slice
    3D scan: left unfixed, a real downstream reader reported 311 separate
    one-slice "stacks" instead of one 311-slice volume.
    """
    convert("tests/fixtures/single_slice/scan.par", tmp_path, output_format="classic")
    classic_path = next(tmp_path.glob("IM_*"))
    base = pydicom.dcmread(classic_path)
    nx, ny, nz = get_normal_vector(base.ImageOrientationPatient)

    def at_slice(instance_number, offset):
        moved = copy.deepcopy(base)
        moved.InstanceNumber = instance_number
        moved.SOPInstanceUID = pydicom.uid.generate_uid()
        moved.file_meta.MediaStorageSOPInstanceUID = moved.SOPInstanceUID
        moved.ImagePositionPatient = [
            moved.ImagePositionPatient[0] + nx * offset,
            moved.ImagePositionPatient[1] + ny * offset,
            moved.ImagePositionPatient[2] + nz * offset,
        ]
        return moved

    datasets = [at_slice(i, (i - 1) * 5) for i in range(1, 6)]

    written = write_enhanced([datasets], tmp_path / "enhanced")
    enhanced = pydicom.dcmread(written[0])
    assert enhanced.NumberOfFrames == 5

    pointers = {int(item.DimensionIndexPointer) for item in enhanced.DimensionIndexSequence}
    assert pointers == {0x0020_9057}  # InStackPositionNumber, not ImagePositionPatient
    assert not hasattr(enhanced, "DimensionOrganizationType")

    stack_positions = set()
    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        fc = pffg.FrameContentSequence[0]
        stack_positions.add(fc.InStackPositionNumber)
    assert stack_positions == {1, 2, 3, 4, 5}


def _classic_dataset(tmp_path):
    convert("tests/fixtures/single_slice/scan.par", tmp_path, output_format="classic")
    return pydicom.dcmread(next(tmp_path.glob("IM_*")))


def _phase(
    ds, instance_number, temporal_position_identifier, cardiac_phase_number=None, trigger_time=None
):
    copied = copy.deepcopy(ds)
    copied.InstanceNumber = instance_number
    copied.SOPInstanceUID = pydicom.uid.generate_uid()
    copied.file_meta.MediaStorageSOPInstanceUID = copied.SOPInstanceUID
    copied.TemporalPositionIdentifier = temporal_position_identifier
    if cardiac_phase_number is not None:
        # MRImagePhaseNumber -- see dictionary/private_tags.py -- the signal
        # dimension_index.py's _is_cardiac_gated reads.
        block = copied.private_block(0x2001, "Philips Imaging DD 001", create=True)
        block.add_new(0x08, "IS", cardiac_phase_number)
    if trigger_time is not None:
        copied.TriggerTime = trigger_time
    return copied


def test_write_enhanced_single_slice_multi_phase_gets_real_temporal_index(tmp_path):
    """Regression test for the real-world cardiac-cine bug: highdicom's own
    dimension-index detection falls back to a meaningless InstanceNumber
    dimension for repeated-position series, so this package must build a
    real TemporalPositionIndex-based one itself (dimension_index.py).
    """
    base = _classic_dataset(tmp_path)
    n_phases = 5
    datasets = [_phase(base, i, i) for i in range(1, n_phases + 1)]

    written = write_enhanced([datasets], tmp_path / "enhanced")
    enhanced = pydicom.dcmread(written[0])
    assert enhanced.NumberOfFrames == n_phases

    temporal_indices = []
    stack_positions = set()
    dim_values = set()
    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        fc = pffg.FrameContentSequence[0]
        temporal_indices.append(fc.TemporalPositionIndex)
        stack_positions.add(fc.InStackPositionNumber)
        dim_values.add(tuple(fc.DimensionIndexValues))

    assert sorted(temporal_indices) == list(range(1, n_phases + 1))
    assert stack_positions == {1}  # single slice location
    assert len(dim_values) == n_phases  # every frame uniquely identified

    pointers = {int(item.DimensionIndexPointer) for item in enhanced.DimensionIndexSequence}
    assert pointers == {0x0020_9057, 0x0020_9128}  # InStackPositionNumber, TemporalPositionIndex


def test_write_enhanced_cardiac_gated_adds_cardiac_synchronization(tmp_path):
    """Regression test: NominalCardiacTriggerDelayTime must be set from a
    real float TriggerTime value, not a DataElement -- pydicom's
    Dataset.get("TriggerTime") (keyword lookup) returns the raw value
    directly, unlike Dataset.get(tag_tuple), which returns a DataElement;
    conflating the two crashed this in real-world testing.
    """
    base = _classic_dataset(tmp_path)
    n_phases = 4
    datasets = [
        _phase(base, i, i, cardiac_phase_number=i, trigger_time=(i - 1) * 62.5)
        for i in range(1, n_phases + 1)
    ]

    written = write_enhanced([datasets], tmp_path / "enhanced")
    enhanced = pydicom.dcmread(written[0])

    delays = []
    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        assert hasattr(pffg, "CardiacSynchronizationSequence")
        delays.append(pffg.CardiacSynchronizationSequence[0].NominalCardiacTriggerDelayTime)

    assert sorted(delays) == [0.0, 62.5, 125.0, 187.5]


def test_write_enhanced_plain_dynamic_scan_skips_cardiac_synchronization(tmp_path):
    """A non-cardiac-gated series (constant/absent cardiac phase number)
    must NOT get a fabricated CardiacSynchronizationSequence -- TriggerTime
    means something different (elapsed dynamic-scan time) there.
    """
    base = _classic_dataset(tmp_path)
    datasets = [_phase(base, i, i, trigger_time=float(i)) for i in range(1, 4)]

    written = write_enhanced([datasets], tmp_path / "enhanced")
    enhanced = pydicom.dcmread(written[0])

    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        assert not hasattr(pffg, "CardiacSynchronizationSequence")


def _contrast(ds, instance_number, image_type):
    copied = copy.deepcopy(ds)
    copied.InstanceNumber = instance_number
    copied.SOPInstanceUID = pydicom.uid.generate_uid()
    copied.file_meta.MediaStorageSOPInstanceUID = copied.SOPInstanceUID
    copied.ImageType = image_type
    return copied


def test_write_enhanced_multi_contrast_same_slice_splits_into_separate_stacks(tmp_path):
    """Regression test for the real-world Dixon water/fat bug: two contrasts,
    each covering multiple slice positions, with no temporal dimension to
    disambiguate frames within a contrast (single dynamic/cardiac-phase).
    Water and fat frames at the *same* slice position must not collide --
    and must land in physically contiguous per-contrast runs, not
    interleaved, since downstream tools (file-info) group frames into
    stacks by contiguous *runs* of identical StackID, not by value
    (confirmed against its real source -- mirrors the real C++
    scanner-side stacking behaviour).
    """
    base = _classic_dataset(tmp_path)
    water_type = ["ORIGINAL", "PRIMARY", "W_T1TFE", "W", "T1TFE"]
    fat_type = ["ORIGINAL", "PRIMARY", "F_T1TFE", "F", "T1TFE"]
    nx, ny, nz = get_normal_vector(base.ImageOrientationPatient)

    def at_slice(ds, offset):
        moved = copy.deepcopy(ds)
        moved.ImagePositionPatient = [
            moved.ImagePositionPatient[0] + nx * offset,
            moved.ImagePositionPatient[1] + ny * offset,
            moved.ImagePositionPatient[2] + nz * offset,
        ]
        return moved

    # Interleaved input order, as PAR/REC rows naturally are: at each of 3
    # slice positions, a water frame immediately followed by a fat frame.
    datasets = []
    instance_number = 1
    for slice_offset in (0, 10, 20):
        slice_ds = at_slice(base, slice_offset)
        datasets.append(_contrast(slice_ds, instance_number, water_type))
        instance_number += 1
        datasets.append(_contrast(slice_ds, instance_number, fat_type))
        instance_number += 1

    written = write_enhanced([datasets], tmp_path / "enhanced")
    enhanced = pydicom.dcmread(written[0])
    assert enhanced.NumberOfFrames == 6

    stack_ids = []
    image_types_by_stack: dict[str, set[str]] = {}
    dim_values = set()
    combined = set()
    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        fc = pffg.FrameContentSequence[0]
        stack_ids.append(fc.StackID)
        dim_values.add(tuple(fc.DimensionIndexValues))
        combined.add((fc.StackID, tuple(fc.DimensionIndexValues)))
        source_sop_instance_uid = str(
            pffg.ConversionSourceAttributesSequence[0].ReferencedSOPInstanceUID
        )
        source = next(ds for ds in datasets if str(ds.SOPInstanceUID) == source_sop_instance_uid)
        image_types_by_stack.setdefault(fc.StackID, set()).add(str(source.ImageType[2]))

    assert set(stack_ids) == {"1", "2"}
    assert len(combined) == 6  # every frame uniquely identified once StackID is included

    # Contiguous runs, not interleaved: exactly one run per StackID value.
    runs = 1 + sum(1 for a, b in zip(stack_ids, stack_ids[1:]) if a != b)
    assert runs == 2

    # Stack "1" is water (appears first in the input/PAR order), not fat --
    # regression guard for sorting contrasts alphabetically by their key
    # string ("F..." < "W..."), which put fat first despite water being
    # the first contrast to actually appear in the data.
    assert image_types_by_stack["1"] == {"W_T1TFE"}
    assert image_types_by_stack["2"] == {"F_T1TFE"}


def test_write_enhanced_multi_slice_multi_phase_ranks_both_dimensions(tmp_path):
    base = _classic_dataset(tmp_path)
    # Offset along the slice normal, not a row/column direction -- that's the
    # axis InStackPositionNumber actually ranks along.
    nx, ny, nz = get_normal_vector(base.ImageOrientationPatient)

    def at_slice(ds, offset):
        moved = copy.deepcopy(ds)
        moved.ImagePositionPatient = [
            moved.ImagePositionPatient[0] + nx * offset,
            moved.ImagePositionPatient[1] + ny * offset,
            moved.ImagePositionPatient[2] + nz * offset,
        ]
        return moved

    slice_a = base
    slice_b = at_slice(base, 10)

    datasets = []
    instance_number = 1
    for phase in (1, 2, 3):
        for slice_ds in (slice_a, slice_b):
            datasets.append(_phase(slice_ds, instance_number, phase))
            instance_number += 1

    written = write_enhanced([datasets], tmp_path / "enhanced")
    enhanced = pydicom.dcmread(written[0])
    assert enhanced.NumberOfFrames == 6

    stack_positions = set()
    temporal_indices = set()
    dim_values = set()
    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        fc = pffg.FrameContentSequence[0]
        stack_positions.add(fc.InStackPositionNumber)
        temporal_indices.add(fc.TemporalPositionIndex)
        dim_values.add(tuple(fc.DimensionIndexValues))

    assert stack_positions == {1, 2}
    assert temporal_indices == {1, 2, 3}
    assert len(dim_values) == 6

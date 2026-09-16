import copy

import pydicom
from highdicom.spatial import get_normal_vector

from parrec2dcm.dimension_index import (
    _group_stack_ids,
    _map_frames_to_source,
    _stack_positions,
    contrast_keys,
    fix_volume_stack_pointer,
    needs_stack_pointer_fix,
    needs_temporal_dimension_index,
)
from parrec2dcm.pipeline import convert


def _classic_dataset(tmp_path):
    convert("tests/fixtures/single_slice/scan.par", tmp_path, output_format="classic")
    return pydicom.dcmread(next(tmp_path.glob("IM_*")))


def _duplicate_with_new_identity(ds, instance_number, temporal_position_identifier=None):
    copied = copy.deepcopy(ds)
    copied.InstanceNumber = instance_number
    copied.SOPInstanceUID = pydicom.uid.generate_uid()
    copied.file_meta.MediaStorageSOPInstanceUID = copied.SOPInstanceUID
    if temporal_position_identifier is not None:
        copied.TemporalPositionIdentifier = temporal_position_identifier
    return copied


def test_needs_temporal_dimension_index_true_for_instance_number_fallback():
    enhanced = pydicom.Dataset()
    item = pydicom.Dataset()
    item.DimensionIndexPointer = 0x0020_0013
    enhanced.DimensionIndexSequence = [item]
    assert needs_temporal_dimension_index(enhanced)


def test_needs_temporal_dimension_index_false_for_spatial_volume():
    enhanced = pydicom.Dataset()
    item = pydicom.Dataset()
    item.DimensionIndexPointer = 0x0020_0032  # ImagePositionPatient
    enhanced.DimensionIndexSequence = [item]
    assert not needs_temporal_dimension_index(enhanced)


def test_needs_temporal_dimension_index_false_when_absent():
    enhanced = pydicom.Dataset()
    assert not needs_temporal_dimension_index(enhanced)


def test_needs_stack_pointer_fix_true_for_image_position_patient_volume():
    enhanced = pydicom.Dataset()
    item = pydicom.Dataset()
    item.DimensionIndexPointer = 0x0020_0032
    enhanced.DimensionIndexSequence = [item]
    assert needs_stack_pointer_fix(enhanced)
    assert not needs_temporal_dimension_index(enhanced)


def test_needs_stack_pointer_fix_false_for_instance_number_fallback():
    enhanced = pydicom.Dataset()
    item = pydicom.Dataset()
    item.DimensionIndexPointer = 0x0020_0013
    enhanced.DimensionIndexSequence = [item]
    assert not needs_stack_pointer_fix(enhanced)


def test_fix_volume_stack_pointer_retargets_to_in_stack_position_number():
    """Regression test for a real-world bug: highdicom's own spatial-volume
    dimension index declares ImagePositionPatient as its pointer -- a real,
    DICOM-standard-valid choice, but not what real Philips scanners write
    (InStackPositionNumber) and not what at least one real downstream
    reader's Philips-specific parser recognizes as a spatial dimension at
    all. Confirmed against a real 311-slice single-contrast 3D scan: left
    unfixed, every frame was reported as its own single-slice "stack" (311
    of them) instead of one 311-slice volume.
    """
    enhanced = pydicom.Dataset()
    item = pydicom.Dataset()
    item.DimensionIndexPointer = 0x0020_0032
    item.FunctionalGroupPointer = 0x0020_9113
    item.DimensionDescriptionLabel = "Image Position Patient"
    item.DimensionOrganizationUID = "1.2.3"
    enhanced.DimensionIndexSequence = [item]
    enhanced.DimensionOrganizationType = "3D"

    fix_volume_stack_pointer(enhanced)

    assert len(enhanced.DimensionIndexSequence) == 1
    fixed = enhanced.DimensionIndexSequence[0]
    assert int(fixed.DimensionIndexPointer) == 0x0020_9057
    assert int(fixed.FunctionalGroupPointer) == 0x0020_9111
    assert not hasattr(enhanced, "DimensionOrganizationType")


def test_fix_volume_stack_pointer_noop_when_not_needed():
    enhanced = pydicom.Dataset()
    item = pydicom.Dataset()
    item.DimensionIndexPointer = 0x0020_0013
    enhanced.DimensionIndexSequence = [item]

    fix_volume_stack_pointer(enhanced)

    assert int(enhanced.DimensionIndexSequence[0].DimensionIndexPointer) == 0x0020_0013


def test_stack_positions_single_slice_all_rank_one(tmp_path):
    base = _classic_dataset(tmp_path)
    frames = [_duplicate_with_new_identity(base, i) for i in range(1, 4)]
    assert _stack_positions(frames) == [1, 1, 1]


def test_stack_positions_two_slices_rank_by_position(tmp_path):
    base = _classic_dataset(tmp_path)
    near = _duplicate_with_new_identity(base, 1)
    far = _duplicate_with_new_identity(base, 2)
    # Push "far" along the slice normal -- the axis _stack_positions actually
    # ranks along -- not a row/column direction, which wouldn't move it out
    # of-plane at all.
    nx, ny, nz = get_normal_vector(far.ImageOrientationPatient)
    far.ImagePositionPatient = [
        far.ImagePositionPatient[0] + nx * 10,
        far.ImagePositionPatient[1] + ny * 10,
        far.ImagePositionPatient[2] + nz * 10,
    ]
    ranks = _stack_positions([near, far])
    assert ranks == [1, 2]

    # Order-independence: reversing the input reverses which rank each gets,
    # not the underlying spatial ordering.
    ranks_reversed = _stack_positions([far, near])
    assert ranks_reversed == [2, 1]


def test_contrast_keys_distinguishes_image_type(tmp_path):
    base = _classic_dataset(tmp_path)
    water = copy.deepcopy(base)
    water.ImageType = ["ORIGINAL", "PRIMARY", "W_T1TFE", "W", "T1TFE"]
    fat = copy.deepcopy(base)
    fat.ImageType = ["ORIGINAL", "PRIMARY", "F_T1TFE", "F", "T1TFE"]

    keys = contrast_keys([water, fat, water])
    assert keys[0] == keys[2]
    assert keys[0] != keys[1]


def test_group_stack_ids_first_seen_order():
    assert _group_stack_ids(["W", "F", "W", "F"]) == ["1", "2", "1", "2"]
    assert _group_stack_ids(["W", "W", "W"]) == ["1", "1", "1"]


def test_stack_positions_ranks_within_each_stack_id_group(tmp_path):
    base = _classic_dataset(tmp_path)
    near = _duplicate_with_new_identity(base, 1)
    far = _duplicate_with_new_identity(base, 2)
    nx, ny, nz = get_normal_vector(far.ImageOrientationPatient)
    far.ImagePositionPatient = [
        far.ImagePositionPatient[0] + nx * 10,
        far.ImagePositionPatient[1] + ny * 10,
        far.ImagePositionPatient[2] + nz * 10,
    ]
    # Two contrasts (stack "1"/"2"), each covering the same two slice
    # positions -- both stacks must independently rank 1, 2.
    frames = [near, far, near, far]
    stack_ids = ["1", "1", "2", "2"]
    assert _stack_positions(frames, stack_ids) == [1, 2, 1, 2]


def test_map_frames_to_source_is_order_independent(tmp_path):
    base = _classic_dataset(tmp_path)
    source_datasets = [_duplicate_with_new_identity(base, i) for i in range(1, 4)]

    enhanced = pydicom.Dataset()
    enhanced.PerFrameFunctionalGroupsSequence = []
    # Deliberately shuffled order relative to source_datasets.
    for ds in [source_datasets[2], source_datasets[0], source_datasets[1]]:
        pffg = pydicom.Dataset()
        csa_item = pydicom.Dataset()
        csa_item.ReferencedSOPInstanceUID = ds.SOPInstanceUID
        pffg.ConversionSourceAttributesSequence = [csa_item]
        enhanced.PerFrameFunctionalGroupsSequence.append(pffg)

    mapped = _map_frames_to_source(enhanced, source_datasets)
    assert [ds.SOPInstanceUID for ds in mapped] == [
        source_datasets[2].SOPInstanceUID,
        source_datasets[0].SOPInstanceUID,
        source_datasets[1].SOPInstanceUID,
    ]

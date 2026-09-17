"""Post-processes highdicom's Enhanced MR output to add a real dimension index.

``highdicom.legacy.sop.LegacyConvertedEnhancedMRImage`` only ever builds one
of two dimension indices (confirmed by reading its source,
``highdicom/legacy/sop.py:982-1132``, ``_find_dimension_index``):

- a spatial-volume one (``ImagePositionPatient``-based), when the input
  datasets form a regularly-spaced, non-repeating volume; or
- a generic ``InstanceNumber``-based fallback otherwise.

There is no code path that builds a ``TemporalPositionIndex``/cardiac-phase
dimension from the input, regardless of what standard tags the source
classic datasets carry -- confirmed that ``TemporalPositionIndex`` is only
ever copied from a source attribute of the exact same name, and this
package's classic datasets set ``TemporalPositionIdentifier`` (a different,
unrelated tag), so highdicom has no way to pick it up. A cardiac-cine/
multi-dynamic/diffusion series (which legitimately repeats slice positions
across phases/dynamics/directions) therefore always falls into the generic
``InstanceNumber`` fallback, and downstream tools relying on the real
``TemporalPositionIndex``/``InStackPositionNumber`` semantics see a
meaningless single "instance number" dimension instead of a real temporal
one -- confirmed against a real 20-cardiac-phase dataset, where the
resulting file reported 1 timeframe instead of 20.

This module replaces that fallback with a proper ``InStackPositionNumber``
(spatial rank) x ``TemporalPositionIndex`` (temporal rank) dimension index,
by editing the ``pydicom.Dataset`` highdicom already built -- not by
modifying highdicom itself.

The spatial-volume branch's per-frame ``InStackPositionNumber`` values are
already correct as written by highdicom (see highdicom's own
``_add_dimension_index_values``) and a genuine regularly-spaced volume has
no time dimension to add -- but its *declared* ``DimensionIndexSequence``
pointer (``ImagePositionPatient``, 0020,0032) still needs fixing
(``fix_volume_stack_pointer``): confirmed against a real 311-slice
single-contrast 3D scan that at least one real downstream reader's
Philips-specific dimension-index parser only ever recognizes
``InStackPositionNumber`` (0020,9057) as a spatial/stack pointer -- exactly
what real Philips scanners always declare -- and never
``ImagePositionPatient``, even though that's an equally DICOM-standard-valid
choice for a volume-organized dimension index (PS3.3 C.7.6.17.3, "3D"
``DimensionOrganizationType``). Since the declared pointer matched none of
that reader's recognized cases, it fell back to treating every frame as its
own singleton stack -- 311 one-slice "stacks" instead of one 311-slice
volume. A repeating-position series is never classified as a volume by
highdicom's own detection in the first place (it requires non-duplicate
positions), so the InstanceNumber-fallback path and this pointer-retarget
path are naturally disjoint -- a file only ever needs one of the two fixes.

Frames are also split into separate ``StackID`` groups by contrast/image
type (``_contrast_keys``/``_group_stack_ids``) before stack position is
ranked. This matters whenever more than one contrast/image-type shares the
same spatial position with no temporal dimension to disambiguate it --
confirmed against a real Dixon water/fat dataset (64 slices x 2 contrasts,
single dynamic/cardiac-phase): without this, water and fat frames at the
same slice both rank as stack position 1 with a constant temporal index of
1, so 128 frames collapse to only 64 distinct ``DimensionIndexValues`` --
every water frame becomes indistinguishable from its fat counterpart at the
same slice. Splitting into separate stacks per contrast (the real Philips
scanner convention, and the same grouping downstream tools like file-info
already expect: they bucket frames by StackID first, before comparing
dimension values within a stack) removes the collision, since each stack
then only contains one contrast's own, internally-unique set of
(stack position, temporal index) pairs.

Diffusion direction/b-value combined with cardiac/dynamic gating, or any
other PAR export where frames sharing one slice, stack, and (nominal)
temporal position turn out not to be genuinely distinguishable by
``TemporalPositionIdentifier`` at all (see ``_disambiguate_temporal_positions``
-- confirmed against a real multi-image T1-mapping export where it wasn't),
would still end up with identical ``DimensionIndexValues`` within their
shared stack purely *semantically* (no real per-frame time value to
declare) -- but ``_disambiguate_temporal_positions`` guarantees they at
least get distinct index *values*, so every frame stays individually
addressable via the dimension index even when it doesn't carry a
meaningful time value.
"""

from __future__ import annotations

import numpy as np
from highdicom.spatial import get_normal_vector
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid

_INSTANCE_NUMBER_POINTER = 0x0020_0013
_IMAGE_POSITION_PATIENT_POINTER = 0x0020_0032
_IN_STACK_POSITION_POINTER = 0x0020_9057
_TEMPORAL_POSITION_INDEX_POINTER = 0x0020_9128
_NOMINAL_CARDIAC_TRIGGER_DELAY_TIME_POINTER = 0x0020_9153
_FRAME_CONTENT_SEQUENCE_POINTER = 0x0020_9111
_CARDIAC_SYNCHRONIZATION_SEQUENCE_POINTER = 0x0018_9118

_POSITION_ROUND_NDIGITS = 3

# MRImagePhaseNumber -- see dictionary/private_tags.py. Used only as a
# signal for whether cardiac gating is active (more than one distinct
# phase across the group), not written from here.
_CARDIAC_PHASE_NUMBER_TAG = (0x2001, 0x1008)


def needs_temporal_dimension_index(enhanced: Dataset) -> bool:
    """Whether ``enhanced`` used highdicom's generic InstanceNumber fallback.

    True exactly when highdicom's ``DimensionIndexSequence`` has a single
    entry pointing at InstanceNumber (0020,0013) -- its signature for "no
    real dimension could be determined, sorted by instance number instead".
    """
    dim_seq = getattr(enhanced, "DimensionIndexSequence", None)
    if not dim_seq or len(dim_seq) != 1:
        return False
    return int(dim_seq[0].DimensionIndexPointer) == _INSTANCE_NUMBER_POINTER


def needs_stack_pointer_fix(enhanced: Dataset) -> bool:
    """Whether ``enhanced`` used highdicom's spatial-volume dimension index.

    True exactly when highdicom's ``DimensionIndexSequence`` has a single
    entry pointing at ImagePositionPatient (0020,0032) -- its signature for
    a genuine, regularly-spaced volume. See module docstring for why this
    still needs fixing even though it's a real, DICOM-standard-valid
    dimension index (real Philips scanners, and at least one real
    downstream reader's Philips-specific parser, only recognize
    InStackPositionNumber as the spatial pointer).
    """
    dim_seq = getattr(enhanced, "DimensionIndexSequence", None)
    if not dim_seq or len(dim_seq) != 1:
        return False
    return int(dim_seq[0].DimensionIndexPointer) == _IMAGE_POSITION_PATIENT_POINTER


def fix_volume_stack_pointer(enhanced: Dataset) -> None:
    """Retarget highdicom's spatial-volume dimension pointer to InStackPositionNumber.

    No-ops unless ``needs_stack_pointer_fix`` -- see there and the module
    docstring for why. Only the ``DimensionIndexSequence`` *declaration*
    changes; the per-frame ``InStackPositionNumber``/``DimensionIndexValues``
    highdicom already wrote in this branch are numerically correct as-is
    and are left untouched.

    Also clears ``DimensionOrganizationType`` ("3D", per DICOM PS3.3
    C.7.6.17.3, specifically implies an ImagePositionPatient-based
    dimension index): since the fix retargets the pointer without
    reordering frames, leaving "3D" declared would misrepresent what's
    actually indexed now.
    """
    if not needs_stack_pointer_fix(enhanced):
        return

    dimension_organization_uid = str(enhanced.DimensionIndexSequence[0].DimensionOrganizationUID)
    enhanced.DimensionIndexSequence = [
        _dimension_index_sequence_item(
            _IN_STACK_POSITION_POINTER,
            _FRAME_CONTENT_SEQUENCE_POINTER,
            "In-Stack Position Number",
            dimension_organization_uid,
        )
    ]
    if hasattr(enhanced, "DimensionOrganizationType"):
        del enhanced.DimensionOrganizationType


def _map_frames_to_source(enhanced: Dataset, source_datasets: list[Dataset]) -> list[Dataset]:
    """Align each output frame with the source classic Dataset it came from.

    Robust to any internal reordering highdicom performs: each frame's
    ``ConversionSourceAttributesSequence`` always carries the source
    dataset's own SOPInstanceUID verbatim.
    """
    by_sop_instance_uid = {str(ds.SOPInstanceUID): ds for ds in source_datasets}
    frames_source = []
    for pffg in enhanced.PerFrameFunctionalGroupsSequence:
        source_sop_instance_uid = str(
            pffg.ConversionSourceAttributesSequence[0].ReferencedSOPInstanceUID
        )
        frames_source.append(by_sop_instance_uid[source_sop_instance_uid])
    return frames_source


def contrast_keys(frames_source: list[Dataset]) -> list[str]:
    """A stable per-frame contrast/image-type identifier.

    Used to split frames into separate ``StackID`` groups (see module
    docstring) so that different contrasts sharing a spatial position don't
    collide in ``DimensionIndexValues`` when there's no temporal dimension
    to tell them apart either. ``ImageType`` (already correctly distinct per
    contrast -- see geometry.py's ``_image_type``) is the primary signal;
    ``EchoNumbers`` is folded in too since multi-echo data can also vary
    independently of ImageType.

    Exposed (not underscore-prefixed) since ``writer_enhanced.py`` also
    needs it, to physically reorder frames into contiguous per-contrast
    runs before handing them to highdicom -- see that module.
    """
    keys = []
    for ds in frames_source:
        image_type = "\\".join(str(v) for v in ds.get("ImageType", []))
        echo_numbers = ds.get("EchoNumbers")
        keys.append(f"{image_type}|{echo_numbers}")
    return keys


def _group_stack_ids(contrast_keys: list[str]) -> list[str]:
    """Assign a stable, small per-distinct-contrast StackID, first-seen order.

    A single distinct contrast (the common case) assigns every frame the
    same StackID ("1"), as before.
    """
    ids_by_key: dict[str, str] = {}
    for key in contrast_keys:
        if key not in ids_by_key:
            ids_by_key[key] = str(len(ids_by_key) + 1)
    return [ids_by_key[key] for key in contrast_keys]


def _stack_positions(frames_source: list[Dataset], stack_ids: list[str] | None = None) -> list[int]:
    """Rank each frame's slice position along the plane normal, 1-based.

    Ranked independently within each ``StackID`` group when given (each
    contrast's own spatial coverage) so that, e.g., a water and a fat frame
    at the same physical slice both rank 1 within their own stack -- in
    practice this comes out numerically identical to a global ranking
    whenever every stack shares the same set of positions (the common
    case), but stays correct even if some stack's coverage differs.
    Defaults to one global group (all frames) when ``stack_ids`` is omitted,
    matching the single-contrast case exactly.

    A single unique position (the common case -- one slice, multiple
    temporal positions) ranks every frame as 1.
    """
    if stack_ids is None:
        stack_ids = ["1"] * len(frames_source)

    normal = get_normal_vector(frames_source[0].ImageOrientationPatient)

    def projection(ds: Dataset) -> float:
        return round(float(np.dot(normal, ds.ImagePositionPatient)), _POSITION_ROUND_NDIGITS)

    ranks = [0] * len(frames_source)
    for stack_id in set(stack_ids):
        indices = [i for i, sid in enumerate(stack_ids) if sid == stack_id]
        unique_positions = sorted({projection(frames_source[i]) for i in indices})
        rank = {position: r + 1 for r, position in enumerate(unique_positions)}
        for i in indices:
            ranks[i] = rank[projection(frames_source[i])]
    return ranks


def _disambiguate_temporal_positions(
    temporal_positions: list[int],
    stack_ids: list[str],
    stack_positions: list[int],
    frames_source: list[Dataset],
) -> list[int]:
    """Break ties when several frames at one stack position share one raw temporal value.

    ``TemporalPositionIdentifier`` is derived from ``DynamicScanNumber``/
    ``CardiacPhaseNumber`` (see geometry.py), but not every PAR/REC export
    varies either of those between frames that are nonetheless genuinely
    distinct images: confirmed against a real multi-image T1-mapping export
    (several magnitude "source" images per slice, feeding a T1 fit), where
    all 8 magnitude images at a given slice report ``DynamicScanNumber=1``,
    ``CardiacPhaseNumber=1`` -- every PAR column that could plausibly
    distinguish them is constant. Left as-is, they'd all collapse onto the
    same ``DimensionIndexValues`` within their stack (same failure mode
    ``_group_stack_ids`` exists to prevent across contrasts, just along the
    temporal axis instead here) -- confirmed 7 of 8 magnitude frames per
    slice become unaddressable via the dimension index this way, even
    though all 8 are still physically present in the file.

    Only groups with an actual collision are touched (so a real dynamic/
    cardiac series with genuinely-varying values is untouched); within a
    colliding group, frames are re-ranked 1..N by their original PAR
    acquisition order (``InstanceNumber``, i.e. ``IndexInRecFile + 1`` --
    stable regardless of any internal reordering highdicom or
    ``_order_for_contiguous_stacks`` performed), which guarantees
    uniqueness while preserving relative order. Also incidentally covers
    the diffusion-direction/b-value-combined-with-gating gap noted in this
    module's docstring, since that's the same collision shape.
    """
    groups: dict[tuple[str, int], list[int]] = {}
    for i, key in enumerate(zip(stack_ids, stack_positions)):
        groups.setdefault(key, []).append(i)

    result = list(temporal_positions)
    for indices in groups.values():
        values = [temporal_positions[i] for i in indices]
        if len(set(values)) == len(values):
            continue  # already unique within this stack position
        ordered = sorted(indices, key=lambda i: int(frames_source[i].InstanceNumber))
        for rank, i in enumerate(ordered, start=1):
            result[i] = rank
    return result


def _is_cardiac_gated(frames_source: list[Dataset]) -> bool:
    """Whether more than one distinct cardiac phase appears in this group.

    Read directly off the private MRImagePhaseNumber tag each classic
    dataset already carries (geometry.py), rather than threading
    ``max_cardiac_phases`` all the way through from the PAR header --
    self-contained and exactly equivalent, since that tag only varies
    when ``max_cardiac_phases > 1`` in the first place.
    """
    phases = set()
    for ds in frames_source:
        element = ds.get(_CARDIAC_PHASE_NUMBER_TAG)
        if element is not None:
            phases.add(int(element.value))
    return len(phases) > 1


def _add_cardiac_synchronization(enhanced: Dataset, frames_source: list[Dataset]) -> None:
    """Add a standard CardiacSynchronizationSequence per frame, from TriggerTime.

    Only called when cardiac gating is confirmed active (see
    ``_is_cardiac_gated``): ``TriggerTime`` on this package's classic
    datasets is dual-purposed (plain elapsed dynamic-scan time for a
    non-cardiac dynamic scan vs. a real cardiac trigger delay for a
    cardiac-gated one -- see geometry.py), so writing this unconditionally
    would fabricate a false cardiac-gating signal.
    """
    for pffg, source_ds in zip(
        enhanced.PerFrameFunctionalGroupsSequence, frames_source, strict=True
    ):
        trigger_time = source_ds.get("TriggerTime")  # keyword lookup: raw value, not a DataElement
        if trigger_time is None:
            continue
        cardiac_sync_item = Dataset()
        cardiac_sync_item.NominalCardiacTriggerDelayTime = float(trigger_time)
        pffg.CardiacSynchronizationSequence = [cardiac_sync_item]


def _dimension_index_sequence_item(
    dimension_index_pointer: int,
    functional_group_pointer: int,
    dimension_description_label: str,
    dimension_organization_uid: str,
) -> Dataset:
    item = Dataset()
    item.DimensionIndexPointer = dimension_index_pointer
    item.FunctionalGroupPointer = functional_group_pointer
    item.DimensionDescriptionLabel = dimension_description_label
    item.DimensionOrganizationUID = dimension_organization_uid
    return item


def add_temporal_dimension_index(enhanced: Dataset, source_datasets: list[Dataset]) -> None:
    """Replace highdicom's InstanceNumber-fallback dimension index, if present.

    No-ops when highdicom already built a real (spatial-volume) dimension
    index -- see ``needs_temporal_dimension_index``.

    The second (temporal) dimension is declared as ``NominalCardiacTriggerDelayTime``
    (in ``CardiacSynchronizationSequence``) rather than ``TemporalPositionIndex``
    when cardiac gating is active, matching the convention real Philips
    scanners use for cardiac-gated Enhanced MR series -- this isn't just a
    style choice: at least one real downstream Enhanced MR reader picks
    which attribute to read a frame's actual time value from based on
    which one is declared as the dimension pointer, falling back to an
    unrelated (and, for legacy-converted data, meaningless) attribute
    otherwise. ``TemporalPositionIndex`` is still written onto
    ``FrameContentSequence`` regardless, for any reader that looks for it
    directly rather than via the dimension index.
    """
    if not needs_temporal_dimension_index(enhanced):
        return

    frames_source = _map_frames_to_source(enhanced, source_datasets)
    stack_ids = _group_stack_ids(contrast_keys(frames_source))
    stack_positions = _stack_positions(frames_source, stack_ids)
    temporal_positions = [int(ds.TemporalPositionIdentifier) for ds in frames_source]
    temporal_positions = _disambiguate_temporal_positions(
        temporal_positions, stack_ids, stack_positions, frames_source
    )
    cardiac_gated = _is_cardiac_gated(frames_source)

    dimension_organization_uid = generate_uid()
    enhanced.DimensionOrganizationSequence = [Dataset()]
    enhanced.DimensionOrganizationSequence[0].DimensionOrganizationUID = dimension_organization_uid

    if cardiac_gated:
        temporal_dimension_item = _dimension_index_sequence_item(
            _NOMINAL_CARDIAC_TRIGGER_DELAY_TIME_POINTER,
            _CARDIAC_SYNCHRONIZATION_SEQUENCE_POINTER,
            "Nominal Cardiac Trigger Delay Time",
            dimension_organization_uid,
        )
    else:
        temporal_dimension_item = _dimension_index_sequence_item(
            _TEMPORAL_POSITION_INDEX_POINTER,
            _FRAME_CONTENT_SEQUENCE_POINTER,
            "Temporal Position Index",
            dimension_organization_uid,
        )
    enhanced.DimensionIndexSequence = [
        _dimension_index_sequence_item(
            _IN_STACK_POSITION_POINTER,
            _FRAME_CONTENT_SEQUENCE_POINTER,
            "In-Stack Position Number",
            dimension_organization_uid,
        ),
        temporal_dimension_item,
    ]

    for pffg, stack_id, stack_index, temporal_index in zip(
        enhanced.PerFrameFunctionalGroupsSequence,
        stack_ids,
        stack_positions,
        temporal_positions,
        strict=True,
    ):
        frame_content = pffg.FrameContentSequence[0]
        frame_content.StackID = stack_id
        frame_content.InStackPositionNumber = stack_index
        frame_content.TemporalPositionIndex = temporal_index
        frame_content.DimensionIndexValues = [stack_index, temporal_index]

    if cardiac_gated:
        _add_cardiac_synchronization(enhanced, frames_source)

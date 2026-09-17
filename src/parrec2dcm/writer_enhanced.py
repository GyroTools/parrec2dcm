"""Enhanced MR multiframe writing via highdicom's legacy-conversion API.

Wraps ``highdicom.legacy.sop.LegacyConvertedEnhancedMRImage``, which takes
a list of classic single-frame Datasets sharing one series and assembles
them into a single valid multiframe file using SOP Class
``1.2.840.10008.5.1.4.1.1.4.4`` ("Legacy Converted Enhanced MR Image
Storage" -- distinct from "native" Enhanced MR Image Storage,
``...4.1``), per DICOM PS3.3 Annex A.71 ("Legacy Converted Enhanced MR
Image IOD"). Confirmed by inspecting real output during development. One
file is written per homogeneous group from ``grouping.py``.
"""

from __future__ import annotations

import copy
from pathlib import Path

from highdicom.legacy.sop import LegacyConvertedEnhancedMRImage
from pydicom.dataset import Dataset

from parrec2dcm.dimension_index import (
    add_temporal_dimension_index,
    contrast_keys,
    fix_volume_stack_pointer,
)
from parrec2dcm.uids import deterministic_uid


def _order_for_contiguous_stacks(datasets: list[Dataset]) -> list[Dataset]:
    """Stable-sort by contrast (first-seen order) and renumber InstanceNumber to match.

    highdicom's own InstanceNumber-fallback dimension-index path
    (``_find_dimension_index`` in ``highdicom/legacy/sop.py``) re-sorts its
    input by ``InstanceNumber`` before assigning output frames -- it
    ignores input list order entirely. So getting one contrast's frames
    contiguous in the output (needed both for ``dimension_index.py``'s
    per-contrast StackID split to mean anything, and because downstream
    tools group frames into stacks by contiguous *runs* of identical
    StackID, not by value -- confirmed against a real Dixon water/fat
    dataset, where leaving frames interleaved produced 128 one-frame
    stacks instead of 2) means renumbering ``InstanceNumber`` here, not
    just reordering the list.

    Contrasts are ordered by first appearance in ``datasets`` (i.e. PAR
    file row order), not alphabetically by their contrast key -- sorting
    alphabetically put a real Dixon dataset's fat images (key starting
    "F...") before its water images (key starting "W..."), even though
    water appears first in the PAR file. First-seen order also matches
    ``_group_stack_ids`` in dimension_index.py, which already assigns
    StackID "1" to whichever contrast it encounters first in frame order --
    this keeps both functions' notion of "first" consistent.

    Returns deep copies, so the caller's own dataset objects (and their
    ``InstanceNumber``, used elsewhere e.g. by classic-mode output) are
    untouched.
    """
    keys = contrast_keys(datasets)
    first_seen_rank: dict[str, int] = {}
    for key in keys:
        first_seen_rank.setdefault(key, len(first_seen_rank))
    order = sorted(range(len(datasets)), key=lambda i: first_seen_rank[keys[i]])
    reordered = [copy.deepcopy(datasets[i]) for i in order]
    for instance_number, ds in enumerate(reordered, start=1):
        ds.InstanceNumber = instance_number
    return reordered


def write_enhanced(groups: list[list[Dataset]], out_dir: Path) -> list[Path]:
    """Write one Enhanced MR multiframe file per homogeneous group.

    Each group's ``SeriesInstanceUID`` is read from its own datasets
    (already assigned per-group by the pipeline); only the multiframe
    instance's own SOPInstanceUID is derived here.

    ``require_volume=False``: many real PAR/REC acquisitions (cardiac
    cine, multi-dynamic, multi-echo, diffusion with multiple b-values/
    directions) are not a single geometric volume -- the same slice
    position repeats across cardiac phases/dynamics/echoes/diffusion
    directions, so frame positions aren't monotonically spaced along one
    axis. highdicom's Enhanced MR dimension-index mechanism handles this
    fine; only the ``require_volume=True`` *validation* (which was this
    module's original default, before hitting exactly this case against
    real data) rejects it outright.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for group_index, datasets in enumerate(groups, start=1):
        series_instance_uid = str(datasets[0].SeriesInstanceUID)
        sop_instance_uid = deterministic_uid(series_instance_uid, "enhanced-sop")

        enhanced = LegacyConvertedEnhancedMRImage(
            legacy_datasets=_order_for_contiguous_stacks(datasets),
            series_instance_uid=series_instance_uid,
            series_number=group_index,
            sop_instance_uid=sop_instance_uid,
            instance_number=1,
            require_volume=False,
            # Passing this explicitly stops highdicom's
            # _add_series_description() from appending its own
            # " (enhanced conversion)" suffix (it only does so when
            # SeriesDescription isn't already set on the destination).
            series_description=datasets[0].get("SeriesDescription"),
        )
        add_temporal_dimension_index(enhanced, datasets)
        fix_volume_stack_pointer(enhanced)

        path = out_dir / f"MF_{group_index:04d}.dcm"
        enhanced.save_as(path, enforce_file_format=True, little_endian=True, implicit_vr=False)
        written.append(path)

    return written

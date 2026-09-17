"""Groups per-image classic Datasets into pixel-format/geometry-homogeneous subsets.

highdicom's Enhanced MR legacy-conversion requires every input Dataset fed
into one multiframe object to share identical pixel-format attributes.
Classic per-file output has no such constraint, but grouping consistently
for both formats keeps one code path — and one output file/series — per
homogeneous subset, generalizing the boundary the legacy MATLAB exporter
drew between separate REC-file outputs (magnitude/phase/velocity) to work
from the datasets' own pixel-format attributes rather than requiring
separate input files per group. In practice a single PAR/REC file almost
always yields exactly one group.

Also split by ``ImageOrientationPatient``: a PAR file can hold more than
one genuinely distinct geometry group -- confirmed against a real 3-plane
survey/scout scan (PAR "slice orientation" column: 30 TRA + 20 SAG + 20 COR
rows, i.e. file-info's own PAR-side reader already reports 3 separate
``DataSets`` for it), where all three planes share an identical pixel
format. Without this, all 70 images across three unrelated orientations
were merged into one Enhanced MR object: ``_stack_positions``
(dimension_index.py) projects every frame's position onto a *single*
normal vector taken from the very first frame, which is meaningless for
frames whose orientation actually differs, so most frames project to
distinct values and the resulting "stack" balloons into dozens of bogus
spatial/temporal index combinations instead of the three coherent series
this should have been.
"""

from __future__ import annotations

from pydicom.dataset import Dataset

_GROUP_KEYS = (
    "Rows",
    "Columns",
    "BitsAllocated",
    "BitsStored",
    "HighBit",
    "PixelRepresentation",
    "PhotometricInterpretation",
    "SamplesPerPixel",
)

# Matches dimension_index.py's _POSITION_ROUND_NDIGITS: floating-point
# insurance against spuriously splitting one true stack into several, not
# a real tolerance -- direction cosines for images within one real stack
# are computed from the same angulation input and come out identical.
_ORIENTATION_ROUND_NDIGITS = 5


def _group_key(ds: Dataset) -> tuple:
    orientation = getattr(ds, "ImageOrientationPatient", None)
    orientation_key = (
        tuple(round(float(v), _ORIENTATION_ROUND_NDIGITS) for v in orientation)
        if orientation is not None
        else None
    )
    return (*(getattr(ds, key, None) for key in _GROUP_KEYS), orientation_key)


def group_datasets(datasets: list[Dataset]) -> list[list[Dataset]]:
    """Split ``datasets`` into homogeneous groups, preserving relative order."""
    groups: dict[tuple, list[Dataset]] = {}
    order: list[tuple] = []
    for ds in datasets:
        key = _group_key(ds)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(ds)
    return [groups[key] for key in order]

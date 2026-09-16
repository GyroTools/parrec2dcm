"""Groups per-image classic Datasets into pixel-format-homogeneous subsets.

highdicom's Enhanced MR legacy-conversion requires every input Dataset fed
into one multiframe object to share identical pixel-format attributes.
Classic per-file output has no such constraint, but grouping consistently
for both formats keeps one code path — and one output file/series — per
homogeneous subset, generalizing the boundary the legacy MATLAB exporter
drew between separate REC-file outputs (magnitude/phase/velocity) to work
from the datasets' own pixel-format attributes rather than requiring
separate input files per group. In practice a single PAR/REC file almost
always yields exactly one group.
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


def _group_key(ds: Dataset) -> tuple:
    return tuple(getattr(ds, key, None) for key in _GROUP_KEYS)


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

"""Assembles one classic single-frame pydicom Dataset per PAR image row.

This is the shared intermediate representation for both output formats:
``writer_classic.py`` writes these directly; ``writer_enhanced.py`` feeds a
homogeneous group of them into highdicom's legacy-conversion API to build
one Enhanced MR multiframe file per group.
"""

from __future__ import annotations

import datetime as dt
import warnings
from typing import Any

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import UID, ExplicitVRLittleEndian, MRImageStorage, generate_uid

from parrec2dcm.database.new_format import ResolvedTag
from parrec2dcm.dictionary.private_tags import set_private_tag
from parrec2dcm.uids import SeriesUids

# Stable per-process implementation identity, not per-dataset.
IMPLEMENTATION_CLASS_UID = generate_uid(entropy_srcs=["parrec2dcm"])


def _apply_tags(ds: Dataset, tags: dict[str, Any]) -> None:
    for key, value in tags.items():
        if value is None:
            continue
        if key.startswith("private:"):
            set_private_tag(ds, key[len("private:") :], value)
        else:
            setattr(ds, key, value)


def _apply_resolved_tags(ds: Dataset, tags: list[ResolvedTag]) -> None:
    for t in tags:
        if t.value is None:
            continue
        try:
            ds.add_new((t.group, t.element), t.vr, t.value)
        except (TypeError, ValueError) as exc:
            # Best-effort: a database export's flat value can't always be
            # coerced into the resolved VR (e.g. a scalar for an SQ tag).
            # Skip it rather than fail the whole conversion, mirroring the
            # legacy exporter's own silent-drop-on-failure behavior.
            warnings.warn(
                f"Skipping database tag ({t.group:04X},{t.element:04X}) VR={t.vr}: {exc}",
                stacklevel=2,
            )


def build_classic_dataset(
    image_index: int,
    static_tags: dict[str, Any],
    dynamic_tags: dict[str, Any],
    identifiers: SeriesUids,
    pixel_slice: np.ndarray,
    db_tags: list[ResolvedTag] | None = None,
) -> Dataset:
    """Build one classic MR Image Storage Dataset for PAR image row ``image_index`` (0-based).

    Precedence, applied in order: PAR-derived static tags, then ``db_tags``
    (a database export overlay -- outranks PAR since it comes from the
    scanner's real database, not a text-header re-derivation), then
    PAR-derived per-image dynamic tags (geometry/diffusion/instance
    indices) applied last so they always win -- a database export has no
    per-image granularity, so it must never clobber a correct per-slice
    value with one static snapshot value repeated across every image.
    """
    sop_instance_uid = UID(identifiers.sop_instance_uid(image_index))

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = MRImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = IMPLEMENTATION_CLASS_UID

    ds = Dataset()
    ds.file_meta = file_meta

    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = sop_instance_uid
    ds.StudyInstanceUID = UID(identifiers.study_uid)
    ds.SeriesInstanceUID = UID(identifiers.series_uid)
    ds.FrameOfReferenceUID = UID(identifiers.frame_of_reference_uid)
    ds.PatientID = identifiers.patient_id
    ds.StudyID = identifiers.study_uid[-16:]

    now = dt.datetime.now()
    ds.InstanceCreationDate = now.strftime("%Y%m%d")
    ds.InstanceCreationTime = now.strftime("%H%M%S.%f")

    _apply_tags(ds, static_tags)
    if db_tags:
        _apply_resolved_tags(ds, db_tags)
    _apply_tags(ds, dynamic_tags)

    rows = dynamic_tags["Rows"]
    columns = dynamic_tags["Columns"]
    if pixel_slice.shape != (rows, columns):
        raise ValueError(
            f"pixel slice shape {pixel_slice.shape} does not match Rows/Columns ({rows}, {columns})"
        )

    ds.PixelData = np.ascontiguousarray(pixel_slice, dtype="<u2").tobytes()

    return ds

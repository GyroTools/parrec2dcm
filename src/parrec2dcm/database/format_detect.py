"""Detects which Philips database/goal parameter tier is available.

Mirrors the release-detection logic in the legacy MATLAB exporter's
``Export()`` (DICOMExporter.m:72-83), run against a single merged
``ParameterPool`` rather than two separate objects -- see the project
plan's "Agora deployment compatibility" section for why that's equivalent.

REL3 (lowercase-name old DB format) and the legacy ``UGN0_``/``UGN1_``/
``UGN5_`` goal-parameter naming are both out of scope (per the approved
plan) and are not detected here.
"""

from __future__ import annotations

from enum import Enum

from parrec2dcm.database.records import ParameterPool


class DatabaseTier(str, Enum):
    NONE = "none"
    OLD = "old"  # REL5/REL53 -- symbolic PIIM/DICOM-style names
    NEW = "new"  # REL11 -- RFR_<LEVEL>_tag_<hex8> names


def detect_database_tier(pool: ParameterPool) -> DatabaseTier:
    if pool.has("RFR_SERIES_objOid"):
        return DatabaseTier.NEW
    if pool.has("RFR_EXAM_OBJECT_OID"):
        return DatabaseTier.OLD
    return DatabaseTier.NONE


def goal_parameters_available(pool: ParameterPool) -> bool:
    """Whether goal (pulse-sequence) parameters are present.

    Gated the same way the legacy exporter gates its goal-derived tag
    block (``EX_ACQ_imaging_sequence`` presence).
    """
    return pool.has("EX_ACQ_imaging_sequence")

"""Exception hierarchy for parrec2dcm."""

from __future__ import annotations


class ParRec2DcmError(Exception):
    """Base class for all parrec2dcm errors."""


class UnsupportedBitDepthError(ParRec2DcmError):
    """Raised when a PAR file declares a pixel bit depth the REC reader can't handle."""


class InconsistentDataError(ParRec2DcmError):
    """Raised when PAR/REC data is internally inconsistent (e.g. image count mismatch)."""


class GroupingError(ParRec2DcmError):
    """Raised when per-image datasets can't be grouped into a valid homogeneous series."""

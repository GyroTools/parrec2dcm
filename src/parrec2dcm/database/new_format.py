"""Generic extraction of DICOM tags from "new" (REL11) format parameter names.

Mirrors the legacy exporter's ``extract_tag`` (DICOMExporter.m:2858-2878):
strips a known per-level name prefix and requires the remainder to
contain ``tag_``, then reads the trailing 8 hex characters as a
GGGGEEEE DICOM tag. Handles vendor-prefixed private tags (e.g.
``RFR_STUDY_tag_Philips_Imaging_DD_002_200100b6``) the same way -- only
the trailing 8 hex chars matter, the vendor name in between is ignored.

Each extracted tag also needs a VR to be written. Resolution order:
1. Public (even-group) tags: pydicom's built-in dictionary.
2. Private tags: this package's own curated dictionary
   (``dictionary/private_tags.py``, ~514 entries), indexed here by
   address.
3. Best-effort fallback: the record's own declared ``Properties.Type``
   (e.g. "String"/"Int64"/"Bool") maps to a plausible VR.
Tags that resolve to no VR at all are skipped -- matching the legacy
exporter's own "unknown tag = no-op" behavior (``set_par``,
DICOMExporter.m:2497-2556).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from pydicom.datadict import dictionary_VR
from pydicom.tag import Tag
from pydicom.valuerep import format_number_as_ds

from parrec2dcm.database.records import ParameterPool
from parrec2dcm.dictionary.private_tags import PRIVATE_TAGS

_LEVEL_PREFIXES = ("RFR_PATIENT_", "RFR_STUDY_", "RFR_SERIES_", "RFR_IMAGE_")
_TAG_HEX_RE = re.compile(r"tag_(?:.*_)?([0-9a-fA-F]{8})$")

_PRIVATE_VR_BY_ADDRESS: dict[tuple[int, int], str] = {
    (t.group, t.element): t.vr for t in PRIVATE_TAGS.values()
}

_TYPE_HINT_VR = {
    "String": "LO",
    "Int64": "IS",
    "Bool": "CS",
    "Float": "DS",
}

# VRs whose values pydicom stores as genuine binary numbers (packed with
# struct at write time) rather than as strings -- a JSON-sourced value like
# the string "1" is accepted at DataElement-construction time but fails
# later, at write time, unless coerced to a real int/float first. Each
# also has a fixed binary width, so an out-of-range value (real DB exports
# do contain these -- e.g. a GUID-sized number under a nominally 16-bit
# VR) must be range-checked too, not just type-coerced. AT (Attribute Tag)
# is deliberately excluded: it names another DICOM tag, not a plain
# integer, so generic int coercion would be meaningless for it.
_INT_VR_RANGES = {
    "US": (0, 0xFFFF),
    "SS": (-0x8000, 0x7FFF),
    "UL": (0, 0xFFFFFFFF),
    "SL": (-0x80000000, 0x7FFFFFFF),
    "UV": (0, 0xFFFFFFFFFFFFFFFF),
    "SV": (-0x8000000000000000, 0x7FFFFFFFFFFFFFFF),
}
_FLOAT_VRS = {"FL", "FD"}

# Can't represent a flat JSON scalar as a DICOM sequence.
_UNWRITABLE_VRS = {"SQ"}

# Real-world exports store dates/times in whatever format their own
# database used internally (locale-formatted, full datetimes reused for a
# plain date/time field, ...), not the separator-free DICOM DA/TM/DT
# formats. Try each candidate pattern in turn rather than assume one.
_DA_PATTERNS = ("%Y/%m/%d", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d")
_TM_PATTERNS = (
    "%H:%M:%S.%f",
    "%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%H%M%S.%f",
    "%H%M%S",
)
_DT_PATTERNS = (
    "%b %d %Y %I:%M%p",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y%m%d%H%M%S.%f",
    "%Y%m%d%H%M%S",
)

# Conservative max lengths (DICOM PS3.5 table 6.2-1) for common short
# string VRs -- an oversized value gets dropped (never truncated, which
# could silently corrupt a UID or code value) rather than written invalid.
_MAX_LENGTH = {"AE": 16, "CS": 16, "SH": 16, "UI": 64, "LO": 64, "ST": 1024, "LT": 10240}

_CS_ALLOWED = re.compile(r"[^A-Z0-9 _]")
_UI_SHAPE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


def _parse_datetime(value: str, patterns: tuple[str, ...]) -> dt.datetime | None:
    value = value.strip()
    for pattern in patterns:
        try:
            return dt.datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def _format_da(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = _parse_datetime(value, _DA_PATTERNS)
    return None if parsed is None else f"{parsed.year:04d}{parsed.month:02d}{parsed.day:02d}"


def _format_tm(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = _parse_datetime(value, _TM_PATTERNS)
    if parsed is None:
        return None
    return f"{parsed.hour:02d}{parsed.minute:02d}{parsed.second:02d}.{parsed.microsecond:06d}"


def _format_dt(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = _parse_datetime(value, _DT_PATTERNS)
    if parsed is None:
        return None
    return (
        f"{parsed.year:04d}{parsed.month:02d}{parsed.day:02d}"
        f"{parsed.hour:02d}{parsed.minute:02d}{parsed.second:02d}.{parsed.microsecond:06d}"
    )


def _sanitize_cs(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _CS_ALLOWED.sub("", value.strip().upper())
    if not cleaned or len(cleaned) > _MAX_LENGTH["CS"]:
        return None
    return cleaned


_BRACKETED_LIST_RE = re.compile(r"^\[(.*)\]$")


def _coerce_scalar(vr: str, value: Any) -> Any | None:
    if vr in _UNWRITABLE_VRS:
        return None
    if vr in _INT_VR_RANGES:
        if not isinstance(value, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                try:
                    value = int(float(value))
                except (TypeError, ValueError):
                    return None
        low, high = _INT_VR_RANGES[vr]
        return value if low <= value <= high else None
    if vr in _FLOAT_VRS and not isinstance(value, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if vr == "DA":
        return _format_da(value)
    if vr == "TM":
        return _format_tm(value)
    if vr == "DT":
        return _format_dt(value)
    if vr == "CS":
        return _sanitize_cs(value)
    if vr == "DS":
        try:
            return format_number_as_ds(float(value))
        except (TypeError, ValueError):
            return None
    if vr == "IS":
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            try:
                int_value = int(float(value))
            except (TypeError, ValueError):
                return None
        return int_value if -1 * 10**11 < int_value < 10**12 else None
    if vr == "UI":
        if not isinstance(value, str) or not _UI_SHAPE.match(value) or len(value) > 64:
            return None
        return value
    max_length = _MAX_LENGTH.get(vr)
    if max_length is not None and isinstance(value, str) and len(value) > max_length:
        return None
    return value


# VRs whose values are naturally multi-valued and might arrive as a
# bracketed, whitespace-separated list string, e.g.
# "[0.98 0.98]" for a 2-component PixelSpacing-shaped DS field.
_MULTIVALUE_NUMERIC_VRS = _INT_VR_RANGES.keys() | _FLOAT_VRS | {"DS", "IS"}


def _coerce_value(vr: str, value: Any) -> Any | None:
    """Coerce a JSON-sourced value to what its VR needs for valid DICOM writing.

    Returns ``None`` (meaning: drop this tag) if coercion, range, or
    format validation fails -- never writes a value known to violate its
    VR's format, and never truncates an oversized value (which could
    silently corrupt e.g. a UID). Handles bracketed multi-value list
    strings for numeric VRs by coercing each component individually.
    """
    if vr in _MULTIVALUE_NUMERIC_VRS and isinstance(value, str):
        match = _BRACKETED_LIST_RE.match(value.strip())
        if match:
            tokens = match.group(1).split()
            if not tokens:
                return None
            coerced = [_coerce_scalar(vr, token) for token in tokens]
            return None if any(c is None for c in coerced) else coerced
    return _coerce_scalar(vr, value)


def extract_tag(name: str) -> tuple[int, int] | None:
    """Extract a (group, element) tag from a new-format parameter name, or None."""
    remainder = None
    for prefix in _LEVEL_PREFIXES:
        if name.startswith(prefix):
            remainder = name[len(prefix) :]
            break
    if remainder is None:
        return None

    match = _TAG_HEX_RE.search(remainder)
    if match is None:
        return None
    hex_tag = match.group(1)
    return int(hex_tag[:4], 16), int(hex_tag[4:], 16)


def resolve_vr(group: int, element: int, record: dict[str, Any]) -> str | None:
    """Best-effort VR resolution for an arbitrary (group, element) tag."""
    if group % 2 == 0:
        try:
            return dictionary_VR(Tag(group, element))
        except KeyError:
            pass

    vr = _PRIVATE_VR_BY_ADDRESS.get((group, element))
    if vr is not None:
        return vr

    type_hint = (record.get("Properties") or {}).get("Type")
    if not isinstance(type_hint, str):
        return None
    return _TYPE_HINT_VR.get(type_hint)


@dataclass(frozen=True)
class ResolvedTag:
    group: int
    element: int
    vr: str
    value: Any


# SOPClassUID/SOPInstanceUID decide classic-vs-Enhanced output shape and
# per-instance identity -- entirely parrec2dcm's own call, never a raw DB
# snapshot (a DB export's own SOP Class reflects whatever format *it* was
# originally exported as, irrelevant to what *we're* producing now).
# Note: StudyInstanceUID/SeriesInstanceUID/FrameOfReferenceUID/PatientID
# are deliberately NOT excluded here even though they're also identity
# tags -- pipeline.py's ``_apply_db_identifier_overrides`` needs to see
# them in this function's output so it can apply them once per series
# (with correct UID-randomization semantics) and then strip them from the
# per-image overlay itself, rather than this module doing it twice.
#
# NumberOfTemporalPositions must stay internally consistent with the
# per-image TemporalPositionIdentifier values static_values.py/geometry.py
# actually assign -- confirmed against real data that a DB export's own
# value for this tag can itself be wrong (e.g. a cardiac-cine series
# reporting "1" despite 20 real cardiac-phase temporal positions, which
# is exactly the kind of DB-side data-quality gap this tag is meant to
# describe, not something we should defer to over our own computed count).
_ALWAYS_EXCLUDED_TAGS = {
    (0x0008, 0x0016),  # SOPClassUID
    (0x0008, 0x0018),  # SOPInstanceUID
    (0x0020, 0x0105),  # NumberOfTemporalPositions
}


def new_format_tags(pool: ParameterPool) -> list[ResolvedTag]:
    """Resolve every new-format tag-shaped record in the pool.

    Records without a `tag_<hex8>`-shaped name (e.g. bookkeeping fields
    like ``RFR_STUDY_uid``) are skipped, as are tags with no resolvable VR.
    Group 0x0002 (File Meta Information) and ``_ALWAYS_EXCLUDED_TAGS`` are
    also skipped -- see their own comments for why.
    """
    resolved: list[ResolvedTag] = []
    for record in pool.records():
        name = record.get("Name")
        if not isinstance(name, str):
            continue
        tag = extract_tag(name)
        if tag is None:
            continue
        group, element = tag
        if group == 0x0002 or tag in _ALWAYS_EXCLUDED_TAGS:
            continue
        vr = resolve_vr(group, element, record)
        if vr is None:
            continue
        value = _coerce_value(vr, record.get("Value"))
        if value is None:
            continue
        resolved.append(ResolvedTag(group, element, vr, value))
    return resolved

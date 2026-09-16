"""Wraps parrec.parread.Parread with a normalized, typed view of PAR header data."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parrec.parread import Parread


def format_da(date: dt.date) -> str:
    """Format a date as a DICOM DA value (YYYYMMDD)."""
    return f"{date.year:04d}{date.month:02d}{date.day:02d}"


def format_tm(time: dt.time) -> str:
    """Format a time as a DICOM TM value (HHMMSS.FFFFFF)."""
    return f"{time.hour:02d}{time.minute:02d}{time.second:02d}.{time.microsecond:06d}"


@dataclass
class ParFile:
    """Normalized view of a parsed Philips PAR header.

    ``general`` holds the flat general-info fields (keys are whatever
    parrec-reader-py's generic parser produced from the file's own ``.``
    lines). ``images`` holds one dict per per-slice row of the image
    information table, again with keys derived generically from the file's
    own column definitions. Both dynamically adapt to whatever fields the
    source PAR file actually declares (PAR V4.1/V4.2), rather than assuming
    a fixed schema.
    """

    path: Path
    general: dict[str, Any]
    images: list[dict[str, Any]]

    @classmethod
    def load(cls, par_path: str | Path) -> ParFile:
        par_path = Path(par_path)
        raw = Parread(str(par_path)).read()
        images = raw.pop("ImageInformation", [])
        return cls(path=par_path, general=raw, images=images)

    @property
    def n_images(self) -> int:
        return len(self.images)

    def image(self, index: int) -> dict[str, Any]:
        """0-based per-image row access (PAR files are 1-indexed internally)."""
        return self.images[index]

    def get(self, key: str, default: Any = None) -> Any:
        return self.general.get(key, default)

    @property
    def exam_datetime(self) -> tuple[dt.date | None, dt.time | None]:
        """Parse the PAR ``ExaminationDateTime`` field.

        The field looks like ``"2012.10.12  /  13:35:4"`` (YYYY.MM.DD /
        H:M:S — components are not necessarily zero-padded, unlike the
        legacy MATLAB exporter's date_time_vec assembly, which reassembles
        the parts in DD-MM-YYYY order without zero-padding, producing an
        invalid DICOM DA/TM value; this parses to real date/time objects
        instead so callers can format valid DICOM DA/TM strings via
        ``format_da``/``format_tm``). Returns ``(None, None)`` for either
        component that can't be parsed.
        """
        raw = self.general.get("ExaminationDateTime")
        if not isinstance(raw, str) or "/" not in raw:
            return None, None

        date_part, _, time_part = raw.partition("/")
        date_out: dt.date | None = None
        time_out: dt.time | None = None

        date_bits = date_part.strip().split(".")
        if len(date_bits) == 3:
            try:
                year, month, day = (int(b.strip()) for b in date_bits)
                date_out = dt.date(year, month, day)
            except ValueError:
                date_out = None

        time_bits = time_part.strip().split(":")
        if len(time_bits) == 3:
            try:
                hour, minute = int(time_bits[0].strip()), int(time_bits[1].strip())
                second_f = float(time_bits[2].strip())
                whole_second = min(int(second_f), 59)
                microsecond = round((second_f - int(second_f)) * 1_000_000)
                time_out = dt.time(hour, minute, whole_second, microsecond)
            except ValueError:
                time_out = None

        return date_out, time_out

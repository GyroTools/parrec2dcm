"""Public conversion entry point."""

from __future__ import annotations

from pathlib import Path

from parrec2dcm.pipeline import OutputFormat
from parrec2dcm.pipeline import convert as _convert


def convert(
    par_file: str | Path,
    output_dir: str | Path,
    output_format: OutputFormat = "enhanced",
    randomize_uids: bool = False,
    params: list[str | Path] | None = None,
) -> list[Path]:
    """Convert a Philips PAR/REC file pair into DICOM.

    Parameters
    ----------
    par_file:
        Path to the ``.par`` (or ``.PAR``) header file. The matching
        ``.rec``/``.REC`` file is expected to sit next to it.
    output_dir:
        Directory the generated DICOM files are written to directly.
    output_format:
        ``"enhanced"`` (default) writes one Enhanced MR multiframe file per
        homogeneous pixel-format group. ``"classic"`` writes one classic
        single-frame MR Image Storage file per image.
    randomize_uids:
        If ``True``, generate fresh UIDs on every call (matching the
        legacy MATLAB exporter's behavior, useful when repeatedly
        re-exporting the same source into the same PACS). Default
        ``False`` derives deterministic UIDs from the PAR content, so the
        same input always produces the same output.
    params:
        Optional JSON parameter-export file path(s) -- Philips "database"
        and/or "goal" exports (either as separate files or a single
        combined export, e.g. from a live Agora fetch; see
        ``database/records.py``). Currently only the "new" (REL11)
        database format is used to enrich the output; older formats and
        goal-parameter enrichment are not yet implemented.

    Returns
    -------
    list[Path]
        Paths to the DICOM files that were written.
    """
    return _convert(
        par_file,
        output_dir,
        output_format=output_format,
        randomize_uids=randomize_uids,
        params=params,
    )

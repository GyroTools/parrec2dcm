"""Top-level conversion pipeline.

Ties together source parsing, database/goal parameter loading,
static/dynamic tag population, dataset assembly, grouping, and output
writing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from parrec2dcm.database.format_detect import DatabaseTier, detect_database_tier
from parrec2dcm.database.new_format import ResolvedTag, new_format_tags
from parrec2dcm.database.old_format_map import old_format_tags
from parrec2dcm.database.records import ParameterPool, load_parameter_pool
from parrec2dcm.dataset_builder import build_classic_dataset
from parrec2dcm.diffusion import diffusion_tags
from parrec2dcm.geometry import dynamic_tags_from_parfile
from parrec2dcm.grouping import group_datasets
from parrec2dcm.source.parfile import ParFile
from parrec2dcm.source.recfile import RecFile
from parrec2dcm.static_values import static_tags_from_parfile
from parrec2dcm.uids import SeriesUids, build_identifiers, deterministic_uid, randomize_uid
from parrec2dcm.writer_classic import write_classic
from parrec2dcm.writer_enhanced import write_enhanced

OutputFormat = Literal["enhanced", "classic"]

# DICOM tags that identify a dataset/patient rather than describe its
# content -- when the database supplies these, they should replace (not
# just overlay onto) parrec2dcm's own PAR-derived identifiers, since
# dataset_builder.py sets those explicitly before any tag overlay runs.
_IDENTIFIER_OVERRIDE_TAGS: dict[tuple[int, int], str] = {
    (0x0020, 0x000D): "study_uid",
    (0x0020, 0x000E): "series_uid",
    (0x0020, 0x0052): "frame_of_reference_uid",
    (0x0010, 0x0020): "patient_id",
}


def _apply_db_identifier_overrides(
    identifiers: SeriesUids, db_tags: list[ResolvedTag], randomize_uids: bool
) -> list[ResolvedTag]:
    """Override PAR-derived identifiers with database-supplied ones, where present.

    Returns the remaining tags (with any consumed identifier tags removed,
    so they aren't redundantly written a second time via the generic
    per-image overlay).
    """
    remaining: list[ResolvedTag] = []
    for tag in db_tags:
        attr = _IDENTIFIER_OVERRIDE_TAGS.get((tag.group, tag.element))
        if attr is None or not tag.value:
            remaining.append(tag)
            continue
        value = str(tag.value)
        if randomize_uids and attr != "patient_id":
            value = randomize_uid(value)
        setattr(identifiers, attr, value)
    return remaining


def _load_pool(params: list[str | Path] | None) -> ParameterPool:
    if not params:
        return ParameterPool()
    return load_parameter_pool(params)


def convert(
    par_file: str | Path,
    output_dir: str | Path,
    output_format: OutputFormat = "enhanced",
    randomize_uids: bool = False,
    params: list[str | Path] | None = None,
) -> list[Path]:
    """Convert one PAR/REC pair to DICOM.

    ``output_format="enhanced"`` (the default) writes one Enhanced MR
    multiframe file per homogeneous pixel-format group; ``"classic"``
    writes one classic single-frame MR Image Storage file per image,
    matching the legacy MATLAB exporter's output shape.

    ``params`` is an optional list of JSON parameter-export file paths
    (Philips "database" and/or "goal" exports, or a single combined list
    as fetched live from Agora -- see ``database/records.py``). Database
    tags outrank PAR-derived static tags but never override per-image
    dynamic tags (geometry/diffusion/instance indices), which only ever
    come from PAR.
    """
    par = ParFile.load(par_file)
    rec = RecFile(par)
    volume = rec.read_volume()  # (n_images, rows, columns)

    pool = _load_pool(params)
    tier = detect_database_tier(pool)

    db_tags: list[ResolvedTag] = []
    identifiers = build_identifiers(par, randomize=randomize_uids)
    if tier is DatabaseTier.NEW:
        db_tags = new_format_tags(pool)
        db_tags = _apply_db_identifier_overrides(identifiers, db_tags, randomize_uids)
    elif tier is DatabaseTier.OLD:
        db_tags = old_format_tags(pool)
        db_tags = _apply_db_identifier_overrides(identifiers, db_tags, randomize_uids)

    static_tags = static_tags_from_parfile(par)
    diffusion_enabled = bool(par.get("Diffusion"))
    technique = str(par.get("Technique", ""))
    dynamic_scan = bool(par.get("DynamicScan"))
    max_cardiac_phases = par.get("MaxNumberOfCardiacPhases", 1) or 1
    _, exam_time = par.exam_datetime
    first_image = par.image(0)

    datasets = []
    for i in range(par.n_images):
        image = par.image(i)
        dyn_tags = dynamic_tags_from_parfile(
            image, first_image, technique, dynamic_scan, exam_time, max_cardiac_phases
        )
        dyn_tags.update(diffusion_tags(image, diffusion_enabled))
        ds = build_classic_dataset(
            i, static_tags, dyn_tags, identifiers, volume[i], db_tags=db_tags
        )
        datasets.append(ds)

    groups = group_datasets(datasets)
    for group_index, group in enumerate(groups):
        if group_index == 0:
            continue
        # Each additional homogeneous group is a distinct DICOM series and
        # needs its own SeriesInstanceUID -- derived from, not equal to,
        # the primary one built above.
        new_series_uid = (
            randomize_uid(identifiers.series_uid)
            if randomize_uids
            else deterministic_uid(identifiers.series_uid, "group", group_index)
        )
        for ds in group:
            ds.SeriesInstanceUID = new_series_uid

    output_dir = Path(output_dir)

    # Files are written directly into output_dir, not a nested "DICOM"
    # subfolder (unlike the legacy exporter). That nesting exists to support
    # the PS3.10 media-interchange layout (a DICOMDIR index at the root
    # pointing into a DICOM/ folder) -- reintroduce it (likely as an
    # opt-in) when DICOMDIR generation is implemented; see the plan's
    # "DICOMDIR generation is out of scope for v1" note.
    if output_format == "classic":
        return write_classic(datasets, output_dir)
    return write_enhanced(groups, output_dir)

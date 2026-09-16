"""DICOM UID and PatientID generation.

Ported from the legacy MATLAB exporter's ``get_uid`` (DICOMExporter.m:
2912-2933), with a deliberate behavioral change confirmed with the package
owner: UIDs are **deterministic by default** (the same PAR content always
produces the same UIDs, which the legacy tool never did — even its
DB-sourced UIDs got a freshly randomized terminal suffix on every export).
Passing ``randomize=True`` restores the legacy "always mutate" behavior, for
callers who need PACS-collision safety when repeatedly re-exporting the same
source data into the same archive.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

from pydicom.uid import generate_uid

from parrec2dcm.source.parfile import ParFile


def deterministic_uid(*parts: object) -> str:
    """A stable DICOM UID derived from ``parts`` (order-sensitive)."""
    key = "|".join(str(p) for p in parts)
    return generate_uid(entropy_srcs=[key])


def randomize_uid(base_uid: str) -> str:
    """Splice a fresh random suffix onto ``base_uid``'s prefix.

    Mirrors the legacy exporter's ``get_uid``: keep everything up to and
    including the last '.', replace the tail with a fresh UID's tail, then
    pad/truncate to the original string's length.
    """
    fresh = str(generate_uid())
    base_dot = base_uid.rfind(".")
    fresh_dot = fresh.rfind(".")
    new_uid: str
    if base_dot == -1 or fresh_dot == -1:
        new_uid = fresh
    else:
        new_uid = base_uid[: base_dot + 1] + fresh[fresh_dot + 1 :]

    if len(new_uid) > len(base_uid):
        new_uid = new_uid[: len(base_uid)]
    elif len(new_uid) < len(base_uid):
        new_uid = new_uid + "0" * (len(base_uid) - len(new_uid))
    return new_uid


def deterministic_patient_id(patient_name: str, *stable_fields: object) -> str:
    name_prefix = (patient_name or "").strip()[:2].upper() or "NA"
    digest = hashlib.sha1("|".join(str(f) for f in stable_fields).encode("utf-8")).hexdigest()[:12]
    return f"{name_prefix}_{digest}"


def randomize_patient_id(patient_name: str) -> str:
    """Matches the legacy exporter's PatientID: name prefix + wall-clock time."""
    name_prefix = (patient_name or "").strip()[:2].upper() or "NA"
    now = dt.datetime.now()
    return f"{name_prefix}_{now:%H%M%S}.{now.microsecond // 1000:03d}"


@dataclass
class SeriesUids:
    study_uid: str
    series_uid: str
    frame_of_reference_uid: str
    patient_id: str
    randomize: bool = False

    def sop_instance_uid(self, instance_index: int) -> str:
        if self.randomize:
            return generate_uid()
        return deterministic_uid(self.series_uid, "SOP", instance_index)


def build_identifiers(par: ParFile, randomize: bool = False) -> SeriesUids:
    """Derive Study/Series/FrameOfReference UIDs and a PatientID for one PAR file.

    The deterministic key intentionally excludes the file path, so the same
    scan content yields the same UIDs even if the source file is renamed or
    moved — only fields that identify the underlying scan are used.
    """
    patient_name = par.get("PatientName", "") or ""
    exam_date, exam_time = par.exam_datetime
    stable_key = (
        patient_name,
        par.get("ProtocolName", ""),
        par.get("ExaminationName", ""),
        str(exam_date),
        str(exam_time),
        par.get("AcquisitionNr"),
        par.get("ReconstructionNr"),
    )

    if randomize:
        return SeriesUids(
            study_uid=generate_uid(),
            series_uid=generate_uid(),
            frame_of_reference_uid=generate_uid(),
            patient_id=randomize_patient_id(patient_name),
            randomize=True,
        )

    return SeriesUids(
        study_uid=deterministic_uid(*stable_key, "Study"),
        series_uid=deterministic_uid(*stable_key, "Series"),
        frame_of_reference_uid=deterministic_uid(*stable_key, "FrameOfReference"),
        patient_id=deterministic_patient_id(patient_name, *stable_key),
        randomize=False,
    )

"""Tier-1 (PAR-only) static, per-series DICOM tag population.

Ported from the legacy MATLAB exporter's ``dicom_get_static_values_from_parfile``
(DICOMExporter.m:1213-1365). UIDs, PatientID and dataset-level identity are
handled separately by ``uids.py``/``dataset_builder.py``.

Two deliberate deviations from the legacy source, both because MATLAB
unconditionally overwrites an earlier, meaningful value with a second
``set_par`` call later in the same function — dead code rather than
intentional behavior:

- ``(0x2001,0x101d)`` (MRSeriesReconstructionNumber) is set from the real
  ``Parfile.ReconstructionNr`` and then immediately overwritten to ``-1``
  by a later "still empty" block. This port keeps the real value.
- The venc (``(0x2001,0x101a)``, MRSeriesPCVelocity) orientation/prep-
  direction switch in MATLAB has no ``else`` branch, so an unrecognized
  combination leaves the variable undefined and the original code would
  error. This port simply omits the tag for that case instead.
"""

from __future__ import annotations

from typing import Any

from parrec2dcm.source.parfile import ParFile, format_da, format_tm

_ORIENTATION_TRANSVERSAL = 1
_ORIENTATION_SAGITTAL = 2
_ORIENTATION_CORONAL = 3


def _venc(general: dict[str, Any], first_image: dict[str, Any]) -> list[float] | None:
    orientation = first_image.get("SliceOrientation")
    prep = str(general.get("PreparationDirection") or "").strip().upper()
    v = general.get("PhaseEncodingVelocity") or [0.0, 0.0, 0.0]
    v1, v2, v3 = v[0], v[1], v[2]

    if orientation == _ORIENTATION_TRANSVERSAL and prep == "RL":
        return [v1, v2, v3]
    if orientation == _ORIENTATION_TRANSVERSAL and prep == "AP":
        return [v2, v1, v3]
    if orientation == _ORIENTATION_SAGITTAL and prep == "AP":
        return [v1, v2, v3]
    if orientation == _ORIENTATION_SAGITTAL and prep == "FH":
        return [v2, v1, v3]
    if orientation == _ORIENTATION_CORONAL and prep == "FH":
        return [v2, v1, v3]
    if orientation == _ORIENTATION_CORONAL and prep == "RL":
        return [v1, v2, v3]
    return None


def static_tags_from_parfile(par: ParFile) -> dict[str, Any]:
    """Per-series DICOM tags derivable purely from the PAR header.

    Returns a dict keyed by pydicom keyword (standard tags) or
    ``"private:<Name>"`` (see ``dictionary/private_tags.py``).
    """
    general = par.general
    first_image = par.image(0)
    exam_date, exam_time = par.exam_datetime

    tags: dict[str, Any] = {}

    if exam_date is not None:
        da = format_da(exam_date)
        for keyword in ("StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate"):
            tags[keyword] = da
        tags["AcquisitionDateTime"] = da + (format_tm(exam_time) if exam_time is not None else "")
    if exam_time is not None:
        tm = format_tm(exam_time)
        for keyword in ("StudyTime", "AcquisitionTime", "ContentTime"):
            tags[keyword] = tm

    technique = str(general.get("Technique", "")).strip()
    scan_resolution = general.get("ScanResolution") or [0, 0]
    fov = general.get("Fov") or [0.0, 0.0, 0.0]
    angulation_midslice = general.get("AngulationMidslice") or [0.0, 0.0, 0.0]
    offcentre_midslice = general.get("OffCentreMidslice") or [0.0, 0.0, 0.0]

    tags.update(
        {
            "Modality": "MR",
            "ProtocolName": general.get("ProtocolName", ""),
            "AcquisitionNumber": general.get("AcquisitionNr"),
            "private:MRSeriesReconstructionNumber": general.get("ReconstructionNr"),
            "AcquisitionDuration": general.get("ScanDuration"),
            "private:MRSeriesNrOfPhases": general.get("MaxNumberOfCardiacPhases"),
            "private:MRSeriesNrOfEchoes": general.get("MaxNumberOfEchoes"),
            "private:MRSeriesNrOfLocations": general.get("MaxNumberOfSlicesLocations"),
            "private:MRSeriesNrOfDynamicScans": general.get("MaxNumberOfDynamics"),
            # Matches the combined TemporalPositionIdentifier formula in
            # geometry.dynamic_tags_from_parfile: the temporal dimension is
            # dynamics x cardiac phases when cardiac-gated, else just
            # dynamics.
            "NumberOfTemporalPositions": (
                general.get("MaxNumberOfDynamics", 1) * general.get("MaxNumberOfCardiacPhases", 1)
                if (general.get("MaxNumberOfCardiacPhases") or 1) > 1
                else general.get("MaxNumberOfDynamics")
            ),
            "PatientPosition": str(general.get("PatientPosition", "")).replace(".", ""),
            "private:MRStackPreparationDirection": general.get("PreparationDirection"),
            "private:MRSeriesScanningTechniqueDesc": technique,
            "PulseSequenceName": technique,
            "AcquisitionMatrix": [0, scan_resolution[0], scan_resolution[1], 0],
            "MRAcquisitionFrequencyEncodingSteps": scan_resolution[0],
            "private:MRMeasurementScanResolution": scan_resolution[0],
            "private:MRSeriesAcquisitionTypePrivate": (
                str(general.get("ScanMode", "")).strip().upper()
            ),
            "RepetitionTime": general.get("RepetitionTime"),
            "private:MRSeriesRepetitionTime": [general.get("RepetitionTime"), 0],
            "private:MRStackFovAP": fov[0],
            "private:MRStackFovFH": fov[1],
            "private:MRStackFovRL": fov[2],
            "private:MRSeriesWaterFatShift": general.get("WaterFatShift"),
            "private:MRStackAngulationAP": angulation_midslice[0],
            "private:MRStackAngulationFH": angulation_midslice[1],
            "private:MRStackAngulationRL": angulation_midslice[2],
            "private:MRStackOffcentreAP": offcentre_midslice[0],
            "private:MRStackOffcentreFH": offcentre_midslice[1],
            "private:MRStackOffcentreRL": offcentre_midslice[2],
            "private:MRFlowCompensation": "Y" if general.get("FlowCompensation") else "N",
            "SpatialPresaturation": "SLAB" if general.get("Presaturation") else "NONE",
            "MagnetizationTransfer": "ON_RESONANCE" if general.get("Mtc") else "NONE",
            "SpectrallySelectedExcitation": "WATER" if general.get("Spir") else "NONE",
            "private:MRSeriesEPIFactor": general.get("EpiFactor"),
            "private:MRSeriesDynamicSeries": "Y" if general.get("DynamicScan") else "N",
            "private:MRSeriesDiffusion": "Y" if general.get("Diffusion") else "N",
            "private:MRSeriesDiffusionEchoTime": general.get("DiffusionEchoTime"),
            "private:MRSeriesNrOfLabelTypes": general.get("NumberOfLabelTypes"),
            "SpecificCharacterSet": "ISO_IR 100",
            "SeriesNumber": general.get("AcquisitionNr"),
            "PatientBirthDate": "20000101",
            "PatientSex": "O",
            "PatientName": general.get("PatientName", ""),
            "InstitutionName": "NA",
            "InstitutionAddress": "NA",
            "PerformingPhysicianName": "NA",
            "Manufacturer": "Philips Healthcare",
            "CodingSchemeDesignator": "DCM",
            "SamplesPerPixel": 1,
            "VolumetricProperties": "VOLUME",
            "VolumeBasedCalculationTechnique": "NONE",
            "TimeDomainFiltering": "",
            "MetaboliteMapDescription": "WATER",
            "KSpaceFiltering": "HAMMING",
            "LUTLabel": "Philips",
            "private:MRSeriesDataType": "PIXEL",
            "ReferringPhysicianName": "",
            "AdditionalPatientHistory": "",
            "SequenceVariant": "",
            "ScanOptions": "",
            "MultiCoilElementName": "",
            "DecoupledNucleus": "",
            "private:SeriesTransmitted": "NO",
            "DataPointRows": 1,
            "DataPointColumns": 0,
        }
    )

    venc = _venc(general, first_image)
    if venc is not None:
        tags["private:MRSeriesPCVelocity"] = venc

    return tags

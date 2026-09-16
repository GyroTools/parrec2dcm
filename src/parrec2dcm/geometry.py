"""Per-image geometry and dynamic PAR-derived DICOM tags.

Ported from the legacy MATLAB exporter's ``get_direction_cosines``
(DICOMExporter.m:2959-3032) and ``dicom_get_dynamic_values_from_parfile``
(DICOMExporter.m:2145-2342), excluding the diffusion block (see
``diffusion.py``) and SOP/MediaStorage instance UIDs (handled by
``uids.py``/``dataset_builder.py``).

One correction versus the legacy MATLAB source: MATLAB sets ``Rows`` and
``Columns`` directly from ``ReconResolution`` (columns 1 and 2 respectively)
and writes the pixel matrix transposed (``Data(:,:,n)'``). Because MATLAB's
``dicomwrite`` derives the *actual* stored Rows/Columns from the transposed
array's real dimensions rather than trusting the metadata struct, the
tag values that end up on disk are effectively swapped relative to what the
source literally assigns — invisible in practice because in-plane pixel
spacing is almost always isotropic. This port makes that swap explicit
(``Rows``/``Columns``/``PixelSpacing`` all use the axis that matches the
transposed pixel array actually being written — see ``source/recfile.py``),
rather than reproducing an assignment that only looks correct by
coincidence. This was confirmed empirically against reference DICOM output
during development (pixel content only matches after transposing).
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from parrec2dcm.source.parfile import format_tm

SLICE_ORIENTATION_TRANSVERSAL = 1
SLICE_ORIENTATION_SAGITTAL = 2
SLICE_ORIENTATION_CORONAL = 3

_ORIENTATION_LABELS = {
    SLICE_ORIENTATION_TRANSVERSAL: "TRANSVERSAL",
    SLICE_ORIENTATION_SAGITTAL: "SAGITTAL",
    SLICE_ORIENTATION_CORONAL: "CORONAL",
}

Vec3 = tuple[float, float, float]

# Per-orientation view-matrix basis vectors (X, Y, Z), each an (RL, AP, FH)-ish
# triple in the sense used by DICOMExporter.m:2966-2983.
_VIEW_MATRICES: dict[int, tuple[Vec3, Vec3, Vec3]] = {
    SLICE_ORIENTATION_CORONAL: ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    SLICE_ORIENTATION_SAGITTAL: ((0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    SLICE_ORIENTATION_TRANSVERSAL: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}

_DEG_TO_RAD = math.pi / 180.0
_DEFAULT_VIEW_MATRIX = _VIEW_MATRICES[SLICE_ORIENTATION_TRANSVERSAL]


def direction_cosines(angulation_ap_fh_rl: Vec3, slice_orientation: int) -> tuple[Vec3, Vec3, Vec3]:
    """Return (RL, AP, FH) direction-cosine triples for one image slice.

    ``angulation_ap_fh_rl`` is the PAR ``ImageAngulation`` row, in
    (AP, FH, RL) degrees, matching the PAR column order. Uses a
    right-handed rotation convention, matching the legacy exporter.
    """
    view_x, view_y, view_z = _VIEW_MATRICES.get(slice_orientation, _DEFAULT_VIEW_MATRIX)

    ap, fh, rl = angulation_ap_fh_rl
    angle = (rl, ap, fh)  # vAngle(1)=RL, (2)=AP, (3)=FH

    s = tuple(-math.sin(a * _DEG_TO_RAD) for a in angle)  # right-handed: sign flipped
    c = tuple(math.cos(a * _DEG_TO_RAD) for a in angle)
    sx, sy, sz = s
    cx, cy, cz = c

    rot_x = (cy * cz, sz * cy, -sy)
    rot_y = (-sz * cx + sx * sy * cz, cx * cz + sx * sy * sz, sx * cy)
    rot_z = (sx * sz + sy * cx * cz, -sx * cz + sy * sz * cx, cx * cy)

    def cosines_for(rot: Vec3) -> Vec3:
        return (
            rot[0] * view_x[0] + rot[1] * view_y[0] + rot[2] * view_z[0],
            rot[0] * view_x[1] + rot[1] * view_y[1] + rot[2] * view_z[1],
            rot[0] * view_x[2] + rot[1] * view_y[2] + rot[2] * view_z[2],
        )

    return cosines_for(rot_x), cosines_for(rot_y), cosines_for(rot_z)


def image_orientation_patient(angulation_ap_fh_rl: Vec3, slice_orientation: int) -> list[float]:
    rl_cos, ap_cos, fh_cos = direction_cosines(angulation_ap_fh_rl, slice_orientation)
    return [rl_cos[0], ap_cos[0], fh_cos[0], rl_cos[1], ap_cos[1], fh_cos[1]]


def image_position_patient(
    angulation_ap_fh_rl: Vec3,
    slice_orientation: int,
    offcentre_ap_fh_rl: Vec3,
    pixel_spacing_xy: tuple[float, float],
    recon_resolution_xy: tuple[int, int],
) -> list[float]:
    """Physical (x, y, z) position of the first (upper-left) pixel.

    ``pixel_spacing_xy``/``recon_resolution_xy`` are the PAR row's own
    (x, y) axis pair — the same axes the direction cosines are computed
    against — not the (possibly swapped) DICOM Rows/Columns axes.
    """
    rl_cos, ap_cos, fh_cos = direction_cosines(angulation_ap_fh_rl, slice_orientation)
    x_axis = (rl_cos[0], ap_cos[0], fh_cos[0])
    y_axis = (rl_cos[1], ap_cos[1], fh_cos[1])

    half_x = pixel_spacing_xy[0] * recon_resolution_xy[0] / 2.0
    half_y = pixel_spacing_xy[1] * recon_resolution_xy[1] / 2.0

    corner_raf = tuple(-half_x * x_axis[i] - half_y * y_axis[i] for i in range(3))

    ap, fh, rl = offcentre_ap_fh_rl
    position_rl = rl + corner_raf[0]
    position_ap = ap + corner_raf[1]
    position_fh = fh + corner_raf[2]
    return [position_rl, position_ap, position_fh]


# Full Philips PAR "image_type_mr" enumeration (not just the commonly-known
# 0-3 M/R/I/P range). Ported from the GyroTools gtpackn-go project's own
# CDO-database-derived mapping (internal/exporter/local/par.go,
# getImageTypeMap -- inverted here from name->code to code->name), the
# authoritative source for this: values 4+ cover derived/reconstructed
# image types (parametric maps, perfusion/diffusion-derived images, and
# critically Dixon water/fat/in-phase/out-phase reconstructions, codes
# 34-37) that silently collapsing to a single default ("M") would make
# indistinguishable from each other and from true magnitude images --
# confirmed as a real bug against a real Dixon dataset (water and fat
# images at the same slice location getting an identical ImageType,
# causing downstream contrast-grouping to treat them as duplicates and
# silently drop half the data).
_IMAGE_TYPE_MR_CODES: dict[int, str] = {
    0: "M",
    1: "R",
    2: "I",
    3: "P",
    4: "CR",
    5: "T0",
    6: "T1",
    7: "T2",
    8: "RHO",
    9: "SPECTRO",
    10: "DERIVED",
    11: "ADC",
    12: "RCBV",
    13: "RCBF",
    14: "MTT",
    15: "TTP",
    16: "FA",
    17: "EADC",
    18: "B0",
    19: "DELAY",
    20: "MAXRELENH",
    21: "RELENH",
    22: "MAXENH",
    23: "WASHIN",
    24: "WASHOUT",
    25: "BREVENH",
    26: "AREACURV",
    27: "ANATOMIC",
    28: "T_TEST",
    29: "STD_DEVIATION",
    30: "PERFUSION",
    31: "T2_STAR",
    32: "R2",
    33: "R2_STAR",
    34: "W",  # Dixon water
    35: "IP",  # Dixon in-phase
    36: "OP",  # Dixon out-of-phase
    37: "F",  # Dixon fat
    38: "KTRANS",
    39: "KEP",
    40: "VE",
    41: "VP",
    42: "SPARE1",
    43: "SPARE2",
    44: "AD",
    45: "RD",
    46: "RA",
    47: "SW_M",
    48: "SW_P",
    49: "FF",
    50: "STIFF",
    51: "WAVE",
}


def _image_type(type_mr_code: int, technique: str) -> tuple[str, str]:
    # Genuinely unknown codes (beyond this table) still get a distinct,
    # valid CS-safe label instead of silently colliding with a known one.
    type_letter = _IMAGE_TYPE_MR_CODES.get(type_mr_code, f"T{type_mr_code}")
    technique = technique.strip()
    image_type = f"ORIGINAL\\PRIMARY\\{type_letter}_{technique}\\{type_letter}\\{technique}"
    image_type = image_type.upper().replace("-", "")
    return type_letter, image_type


def _acquisition_time(exam_time: dt.time | None, dyn_scan_begin_offset: float) -> str:
    base = exam_time or dt.time(12, 0, 0, 650000)
    base_dt = dt.datetime.combine(dt.date(2000, 1, 1), base)
    result = base_dt + dt.timedelta(seconds=dyn_scan_begin_offset)
    return format_tm(result.time())


def dynamic_tags_from_parfile(
    image: dict[str, Any],
    first_image: dict[str, Any],
    technique: str,
    dynamic_scan: bool,
    exam_time: dt.time | None,
    max_cardiac_phases: int = 1,
) -> dict[str, Any]:
    """Per-image DICOM tags derivable purely from one PAR ``ImageInformation`` row.

    Returns a dict keyed by pydicom keyword (standard tags) or private-tag
    name (see ``dictionary/private_tags.py``, looked up via a leading
    ``"private:"`` prefix) mapping to the value to write.

    ``max_cardiac_phases`` (the PAR general-info "Max. number of cardiac
    phases" field) drives ``TemporalPositionIdentifier``: for a
    cardiac-gated cine acquisition, the temporal ("movie") dimension is
    ``CardiacPhaseNumber``, not ``DynamicScanNumber`` (which stays 1 for a
    single cine acquisition) -- using the latter unconditionally left
    every phase reporting the same standard temporal position tag. The
    combined formula also correctly handles a cardiac-gated *dynamic* scan
    (both > 1) as one monotonic index across the full acquisition, and
    reduces to the plain dynamic-scan-number case when there's no cardiac
    gating at all (``max_cardiac_phases == 1``).
    """
    recon_resolution = image["ReconResolution"]  # (x, y)
    pixel_spacing = image["PixelSpacing"]  # (x, y)
    angulation = tuple(image["ImageAngulation"])  # (ap, fh, rl)
    offcentre = tuple(image["ImageOffcentre"])  # (ap, fh, rl)
    slice_orientation = image["SliceOrientation"]

    type_letter, image_type = _image_type(image["ImageTypeMr"], technique)

    dyn_scan_begin_time = image["DynScanBeginTime"] - first_image["DynScanBeginTime"]
    dyn_scan_time = image["DynScanBeginTime"] if dynamic_scan else 0.0

    tags: dict[str, Any] = {
        "SliceLocation": image["SliceNumber"],
        "private:ImagePlaneNumber": image["SliceNumber"],
        "EchoNumbers": image["EchoNumber"],
        "TemporalPositionIdentifier": (
            (image["DynamicScanNumber"] - 1) * max_cardiac_phases + image["CardiacPhaseNumber"]
            if max_cardiac_phases > 1
            else image["DynamicScanNumber"]
        ),
        "private:MRImagePhaseNumber": image["CardiacPhaseNumber"],
        "private:MRImageTypeMR": type_letter,
        "ImageType": image_type,
        "private:MRImageScanningSequencePrivate": "FFE" if image["ScanningSequence"] == 0 else "SE",
        "InstanceNumber": image["IndexInRecFile"] + 1,
        "BitsAllocated": image["ImagePixelSize"],
        "PercentSampling": image["ScanPercentage"],
        # Swapped vs. the raw PAR (x, y) order — see module docstring.
        "Rows": recon_resolution[1],
        "Columns": recon_resolution[0],
        "RescaleIntercept": image["RescaleIntercept"],
        "RescaleSlope": image["RescaleSlope"],
        "RescaleType": "normalized",
        "WindowCenter": image["WindowCenter"],
        "WindowWidth": image["WindowWidth"],
        "private:MRImageAngulationAP": angulation[0],
        "private:MRImageAngulationFH": angulation[1],
        "private:MRImageAngulationRL": angulation[2],
        "private:MRImageOffCentreAP": offcentre[0],
        "private:MRImageOffCentreFH": offcentre[1],
        "private:MRImageOffCentreRL": offcentre[2],
        "ImageOrientationPatient": image_orientation_patient(angulation, slice_orientation),
        "ImagePositionPatient": image_position_patient(
            angulation, slice_orientation, offcentre, tuple(pixel_spacing), tuple(recon_resolution)
        ),
        "SliceThickness": image["SliceThickness"],
        "SpacingBetweenSlices": image["SliceThickness"] + image["SliceGap"],
        "private:ImagePlaneOrientation": _ORIENTATION_LABELS.get(slice_orientation, "TRANSVERSAL"),
        "private:MRfMRIStatusIndication": image["FmriStatusIndication"],
        # Swapped to match Rows/Columns above.
        "PixelSpacing": [pixel_spacing[1], pixel_spacing[0]],
        "ImagerPixelSpacing": [pixel_spacing[1], pixel_spacing[0]],
        "EchoTime": image["EchoTime"],
        "AcquisitionTime": _acquisition_time(exam_time, dyn_scan_begin_time),
        "ContentTime": _acquisition_time(exam_time, dyn_scan_begin_time),
        "TriggerTime": (1000 * dyn_scan_time) if dynamic_scan else image["TriggerTime"],
        "private:MRImageDynamicScanBeginTime": dyn_scan_time / 1000.0,
        "NumberOfAverages": image["NumberOfAverages"],
        "FlipAngle": image["ImageFlipAngle"],
        "private:TFEFactor": image["TurboFactor"],
        "InversionTime": image["InversionDelay"],
        "PhotometricInterpretation": "MONOCHROME2",
        "BitsStored": 12,
        "HighBit": 11,
        "PixelRepresentation": 0,
        "private:MRImageEnhanced": "N",
    }

    if image["CardiacFrequency"] > 0:
        tags["HeartRate"] = image["CardiacFrequency"]
    if image["MinRrInterval"] > 0:
        tags["LowRRValue"] = image["MinRrInterval"]
    if image["MaxRrInterval"] > 0:
        tags["HighRRValue"] = image["MaxRrInterval"]

    return tags

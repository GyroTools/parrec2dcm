"""Per-image diffusion DICOM tags.

Ported from the legacy MATLAB exporter's diffusion block
(DICOMExporter.m:2263-2318).
"""

from __future__ import annotations

from typing import Any

_ORIENTATION_CORONAL = 3
_ORIENTATION_SAGITTAL = 2
_ORIENTATION_TRANSVERSAL = 1


def diffusion_tags(image: dict[str, Any], diffusion_enabled: bool) -> dict[str, Any]:
    """Per-image diffusion-related DICOM tags.

    ``diffusion_enabled`` is the PAR general-info ``Diffusion`` flag
    (0/1) — when false, all diffusion values are written as zero/empty,
    matching the legacy exporter's behavior for non-diffusion scans.
    """
    diffusion_rl = diffusion_ap = diffusion_fh = 0.0
    b_factor = 0.0
    direction = ""

    if diffusion_enabled:
        b_factor = image["DiffusionBFactor"]
        diff_ap, diff_fh, diff_rl = image["Diffusion"]

        slice_orientation = image["SliceOrientation"]
        if slice_orientation == _ORIENTATION_CORONAL:
            m, p, s = diff_fh, diff_rl, diff_ap
        elif slice_orientation == _ORIENTATION_SAGITTAL:
            m, p, s = diff_fh, diff_ap, diff_rl
        else:  # transversal (and default)
            m, p, s = diff_ap, diff_rl, diff_fh

        direction = "O"
        if m == 0 and p == 0 and abs(s) == 1:
            direction = "S"
        elif m == 0 and abs(p) == 1 and s == 0:
            direction = "P"
        elif abs(m) == 1 and p == 0 and s == 0:
            direction = "M"
        elif m == 0 and p == 0 and s == 0:
            direction = "I"

        diffusion_rl, diffusion_ap, diffusion_fh = diff_rl, diff_ap, diff_fh

    return {
        "private:MRImageDiffusionRL": diffusion_rl,
        "private:MRImageDiffusionAP": diffusion_ap,
        "private:MRImageDiffusionFH": diffusion_fh,
        "DiffusionBValue": b_factor if diffusion_enabled else 0.0,
        "DiffusionGradientOrientation": [diffusion_rl, diffusion_ap, diffusion_fh],
        "private:MRImageDiffusionBFactor": b_factor,
        "private:MRImageDiffusionDirection": direction,
    }

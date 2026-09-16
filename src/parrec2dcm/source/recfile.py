"""Wraps parrec.recread.Recread with bit-depth validation and DICOM-oriented slice access."""

from __future__ import annotations

import numpy as np
from parrec.recread import Recread

from parrec2dcm.errors import InconsistentDataError, UnsupportedBitDepthError
from parrec2dcm.source.parfile import ParFile

SUPPORTED_BITS_ALLOCATED = 16


class RecFile:
    """Reads REC pixel data for a given PAR file, validating assumptions first."""

    def __init__(self, par: ParFile):
        self.par = par
        self._reader = Recread(str(par.path))

    def read_volume(self) -> np.ndarray:
        """Read the full REC volume as ``(n_images, rows, columns)`` uint16.

        Each slice is transposed relative to parrec-reader-py's raw
        ``(xres, yres)`` layout to match DICOM's row-major pixel data
        convention — confirmed empirically against reference DICOM output
        (mirrors the legacy MATLAB exporter's ``Data(:,:,image_nr)'``).
        """
        bad_depths = {
            depth
            for img in self.par.images
            if (depth := img.get("ImagePixelSize")) != SUPPORTED_BITS_ALLOCATED
        }
        if bad_depths:
            raise UnsupportedBitDepthError(
                f"Unsupported pixel bit depth(s) {sorted(str(d) for d in bad_depths)} "
                f"in {self.par.path}; only {SUPPORTED_BITS_ALLOCATED}-bit PAR/REC data "
                "is currently supported."
            )

        data = self._reader.read()
        if data.shape[2] != self.par.n_images:
            raise InconsistentDataError(
                f"REC file for {self.par.path} contains {data.shape[2]} images, "
                f"but the PAR header describes {self.par.n_images}."
            )

        # (xres, yres, n) -> (n, rows, columns), transposing each slice.
        return np.ascontiguousarray(np.transpose(data, (2, 1, 0)))

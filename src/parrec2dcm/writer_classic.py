"""Classic per-image DICOM writing.

Mirrors the legacy MATLAB exporter's ``dicom_write_images``
(DICOMExporter.m:133-225), minus DICOMDIR generation (out of scope for v1).
"""

from __future__ import annotations

from pathlib import Path

from pydicom.dataset import Dataset

_DIR_CHUNK_SIZE = 10000


def write_classic(datasets: list[Dataset], out_dir: Path) -> list[Path]:
    """Write one ``IM_NNNN`` file per dataset, chunked into subfolders every 10000 images."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    chunked = len(datasets) >= _DIR_CHUNK_SIZE
    for i, ds in enumerate(datasets, start=1):
        chunk_dir = out_dir
        if chunked:
            chunk_dir = out_dir / f"{((i - 1) // _DIR_CHUNK_SIZE) + 1:04d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)

        filename_index = ((i - 1) % _DIR_CHUNK_SIZE) + 1
        path = chunk_dir / f"IM_{filename_index:04d}"
        ds.save_as(path, enforce_file_format=True, little_endian=True, implicit_vr=False)
        written.append(path)

    return written

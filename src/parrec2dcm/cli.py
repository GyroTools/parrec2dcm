"""Command-line interface for parrec2dcm."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from parrec2dcm import __version__
from parrec2dcm.converter import convert


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parrec2dcm",
        description="Convert Philips PAR/REC files to DICOM.",
    )
    parser.add_argument(
        "par_file",
        type=Path,
        help="Path to the input .par/.PAR file (matching .rec must be alongside it).",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory to write the generated DICOM files to (default: current directory).",
    )
    parser.add_argument(
        "--classic",
        action="store_true",
        help="Write classic single-frame MR Image Storage files (one per image) "
        "instead of the default Enhanced MR multiframe output.",
    )
    parser.add_argument(
        "--randomize-uids",
        action="store_true",
        help="Generate fresh UIDs on every run (legacy behavior), instead of the "
        "default deterministic UIDs derived from the PAR content.",
    )
    parser.add_argument(
        "--params",
        type=Path,
        nargs="+",
        metavar="PATH",
        help="One or more JSON parameter-export files (Philips 'database' and/or "
        "'goal' exports -- a single combined export or several separate ones are "
        "both accepted). Currently only the 'new' (REL11) database format is used.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        written = convert(
            args.par_file,
            args.output_dir,
            output_format="classic" if args.classic else "enhanced",
            randomize_uids=args.randomize_uids,
            params=args.params,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(written)} DICOM file(s) to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# parrec2dcm

Convert Philips PAR/REC files to DICOM.

Given only a `.par`/`.rec` pair (no Philips database or scanner export
available), produces standards-conformant DICOM with correct geometry, UIDs,
and pixel data. Two output formats are supported:

- **Enhanced MR** (default) — one multiframe DICOM file per series, built via
  [`highdicom`](https://github.com/ImagingDataCommons/highdicom)'s legacy
  conversion (SOP Class `1.2.840.10008.5.1.4.1.1.4.4`, "Legacy Converted
  Enhanced MR Image Storage").
- **Classic** (`--classic`) — one single-frame MR Image Storage file per
  image, matching how most legacy PAR/REC converters behave.

UIDs are deterministic by default (the same PAR content always produces the
same UIDs); pass `--randomize-uids` to get a fresh UID on every run instead
(useful when repeatedly re-exporting the same source into the same PACS).

If a Philips "database" parameter export is also available (a flat JSON
array of `{Name, Value, ...}` records — e.g. from a MongoDB/Agora export, or
the same list `gtagora-connector-py`'s `Dataset.get_parameters()` returns),
pass it with `--params` to enrich the output beyond what the PAR header alone
can provide. Currently only the "new" (REL11) database format — where the
DICOM tag is embedded in the parameter name, e.g. `RFR_SERIES_tag_00180091`
— is mapped; the older symbolic-name format is detected and produces a
warning with a graceful PAR-only fallback rather than an error. "Goal"
(pulse-sequence) parameter enrichment is not yet implemented. `--params`
accepts one or more files, which are merged into a single pool — pass a
combined export or several separate ones, either way.

## Installation

```bash
pip install parrec2dcm
```

## Usage

As a command-line tool:

```bash
parrec2dcm path/to/scan.par -o path/to/output_dir              # Enhanced MR (default)
parrec2dcm path/to/scan.par -o path/to/output_dir --classic    # classic single-frame
parrec2dcm path/to/scan.par -o path/to/output_dir --params db.json   # + database enrichment
```

As a library:

```python
from parrec2dcm import convert

convert("path/to/scan.par", "path/to/output_dir")
convert("path/to/scan.par", "path/to/output_dir", output_format="classic")
convert("path/to/scan.par", "path/to/output_dir", params=["db.json"])
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT

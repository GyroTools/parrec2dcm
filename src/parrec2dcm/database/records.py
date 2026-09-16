"""Loads and merges Philips "database"/"goal" parameter JSON exports.

Each source is a flat JSON array of records:
``{"ID": ..., "Name": ..., "NameText": ..., "Value": ..., "Properties": {...}}``
-- the shape of both database (old/new format) and goal parameter exports,
and also what `gtagora-connector-py`'s `Dataset.get_parameters()` returns
(a single flattened list covering everything, DB and goal alike). One or
more sources are merged into a single, name-indexed pool: DB parameter
names (``RFR_*``) and goal parameter names (``AC_*``/``EX_*``/``RC_*``/
``VAL0x_*``) occupy disjoint namespaces, so detection never actually
needs to know which file a record came from -- see the project plan's
"Agora deployment compatibility" section.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class ParameterPool:
    """A flat, name-indexed pool of parameter records merged from one or more sources."""

    def __init__(self, records: Iterable[dict[str, Any]] = ()):
        self._by_name: dict[str, dict[str, Any]] = {}
        for record in records:
            name = record.get("Name")
            if name is not None:
                self._by_name[name] = record  # later sources win on collision

    def has(self, name: str) -> bool:
        return name in self._by_name

    def get(self, name: str, default: Any = None) -> Any:
        record = self._by_name.get(name)
        return record["Value"] if record is not None else default

    def get_record(self, name: str) -> dict[str, Any] | None:
        return self._by_name.get(name)

    def records(self) -> Iterable[dict[str, Any]]:
        return self._by_name.values()

    def names(self) -> Iterable[str]:
        return self._by_name.keys()

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: object) -> bool:
        return name in self._by_name


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Load one JSON parameter-export file (a flat array of records)."""
    path = Path(path)
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of parameter records")
    return data


def load_parameter_pool(paths: Iterable[str | Path]) -> ParameterPool:
    """Load one or more JSON parameter-export files and merge them into one pool.

    Accepts either a single combined export (matching what a live Agora
    fetch's ``Dataset.get_parameters()`` produces) or several separate
    exports (matching today's `db_r11.json`/`goal_r11.json`-style
    fixtures) -- both end up as one merged pool.
    """
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(load_records(path))
    return ParameterPool(records)

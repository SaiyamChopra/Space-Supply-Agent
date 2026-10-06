"""Simple JSON persistence for the single-user local application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_DATA: dict[str, Any] = {
    "items": [],
    "supplies": [],
    "tasks": [],
    "events": [],
}


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(DEFAULT_DATA)

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read local data file: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("The local data file must contain a JSON object.")
        data = dict(DEFAULT_DATA)
        data.update(raw)
        for key in DEFAULT_DATA:
            if not isinstance(data.get(key), list):
                raise ValueError(f"The '{key}' entry in the data file must be a list.")
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temp_path.replace(self.path)

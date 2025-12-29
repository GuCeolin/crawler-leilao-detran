from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_filters_config(path: Path) -> dict[str, Any]:
    data = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(data) or {}
    return json.loads(data)

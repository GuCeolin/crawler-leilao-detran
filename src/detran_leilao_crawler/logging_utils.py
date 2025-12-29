from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def setup_logging(output_dir: Path, level: int = logging.INFO) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "crawler.log"

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
    )


def jsonl_append(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def _default(o: Any) -> Any:
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=_default) + "\n")


def safe_float(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    t = (
        text.replace("R$", "")
        .replace(" ", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(t)
    except ValueError:
        return None

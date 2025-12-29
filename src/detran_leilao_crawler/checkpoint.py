from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Set


@dataclass
class CrawlCheckpoint:
    path: Path
    pages_done: Dict[str, Set[int]] = field(default_factory=dict)

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.pages_done = {k: set(v) for k, v in data.get("pages_done", {}).items()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"pages_done": {k: sorted(list(v)) for k, v in self.pages_done.items()}}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_page_done(self, auction_id: str, page: int) -> bool:
        return page in self.pages_done.get(auction_id, set())

    def mark_page_done(self, auction_id: str, page: int) -> None:
        self.pages_done.setdefault(auction_id, set()).add(page)

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .models import Auction, Lot


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    return None


def auction_from_dict(d: dict[str, Any]) -> Auction:
    d2 = dict(d)
    d2["ends_at"] = _parse_dt(d2.get("ends_at"))
    return Auction(**d2)


def lot_from_dict(d: dict[str, Any]) -> Lot:
    d2 = dict(d)
    d2["ends_at"] = _parse_dt(d2.get("ends_at"))

    # Normalize image_urls to tuple
    imgs = d2.get("image_urls")
    if imgs is None:
        d2["image_urls"] = tuple()
    elif isinstance(imgs, list):
        d2["image_urls"] = tuple(imgs)
    elif isinstance(imgs, tuple):
        pass
    else:
        d2["image_urls"] = tuple([str(imgs)])

    # Normalize numeric types
    if d2.get("year") is not None:
        try:
            d2["year"] = int(d2["year"])
        except Exception:
            d2["year"] = None

    if d2.get("start_bid") is not None:
        try:
            d2["start_bid"] = float(d2["start_bid"])
        except Exception:
            d2["start_bid"] = None

    return Lot(**d2)

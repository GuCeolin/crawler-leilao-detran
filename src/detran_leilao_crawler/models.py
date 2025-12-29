from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence


@dataclass(frozen=True)
class Auction:
    auction_id: str
    url: str
    number: Optional[str] = None
    city: Optional[str] = None
    yard: Optional[str] = None
    organizer: Optional[str] = None
    status: Optional[str] = None
    ends_at: Optional[datetime] = None


@dataclass(frozen=True)
class LotImage:
    auction_id: str
    lot_id: str
    url: str


@dataclass(frozen=True)
class Lot:
    auction_id: str
    lot_id: str
    description_short: str

    brand_model: Optional[str] = None
    year: Optional[int] = None
    situation: Optional[str] = None
    start_bid: Optional[float] = None
    ends_at: Optional[datetime] = None

    lot_url: Optional[str] = None
    image_urls: Sequence[str] = field(default_factory=tuple)

    requires_login: bool = False

    raw_text: Optional[str] = None

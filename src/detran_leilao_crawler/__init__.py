"""DETRAN-MG auction crawler (ethical).

This package provides a Playwright-first crawler with a requests/BS4 fallback,
rate limiting, retries, checkpointing, and filtering/export.
"""

from .models import Auction, Lot, LotImage

__all__ = ["Auction", "Lot", "LotImage"]

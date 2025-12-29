from __future__ import annotations

import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import requests
from playwright.sync_api import Page, sync_playwright

from .checkpoint import CrawlCheckpoint
from .logging_utils import jsonl_append
from .models import Auction, Lot
from .api_json import (
    extract_lots_from_json,
    get_total_pages,
    paginate_payload,
    paginate_url,
    redact_headers,
)
from .parsers import (
    parse_auction_cards_from_home,
    parse_auction_details_from_html,
    parse_lot_cards_from_html,
)
from .rate_limit import RateLimiter
from .retry import RetryPolicy, retry_call
from .robots import RobotsPolicy
from .serde import lot_from_dict


logger = logging.getLogger(__name__)


BASE_URL = "https://leilao.detran.mg.gov.br/"
DEFAULT_UA = "detran-leilao-crawler/0.1 (+ethical; respects robots.txt)"


class DetranLeilaoCrawler:
    def __init__(
        self,
        output_dir: Path,
        headless: bool,
        rate_limit_per_sec: float,
        timeout_sec: float = 30.0,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self.output_dir = output_dir
        self.headless = headless
        self.timeout_sec = timeout_sec
        self.user_agent = user_agent

        self.rate_limiter = RateLimiter(rate_limit_per_sec)
        self.robots = RobotsPolicy(BASE_URL, user_agent=user_agent)
        self.checkpoint = CrawlCheckpoint(path=output_dir / ".checkpoint" / "state.json")

        self.retry_policy = RetryPolicy()
        self._session = requests.Session()

    def _respect(self, url: str) -> bool:
        ok = self.robots.can_fetch(url)
        if not ok:
            logger.warning("Blocked by robots.txt: %s", url)
        return ok

    def init(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.robots.load()
        self.checkpoint.load()

    def _requests_get(self, url: str) -> str:
        if not self._respect(url):
            raise RuntimeError(f"Blocked by robots.txt: {url}")

        def _do() -> str:
            self.rate_limiter.wait()
            r = self._session.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout_sec)
            r.raise_for_status()
            return r.text

        def _should_retry(exc: Exception) -> bool:
            # Retry transient network/server errors.
            return isinstance(exc, (requests.Timeout, requests.ConnectionError, requests.HTTPError))

        return retry_call(_do, policy=self.retry_policy, should_retry=_should_retry)

    def discover_auctions(self, max_auctions: Optional[int] = None) -> list[Auction]:
        """Discover auctions from home.

        Strategy:
        1) Playwright: render + allow dynamic content.
        2) Fallback: requests + HTML parse.
        """
        if not self._respect(BASE_URL):
            return []

        try:
            return self._discover_auctions_playwright(max_auctions=max_auctions)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playwright discover failed (%s). Falling back to requests/BS4.", exc)
            return self._discover_auctions_requests(max_auctions=max_auctions)

    def enrich_auction_metadata(self, auction: Auction) -> Auction:
        """Fetch auction details page and parse metadata defensively.

        Playwright is preferred (JS-heavy pages). Fallback to requests.
        """
        if not self._respect(auction.url):
            return auction

        try:
            return self._enrich_auction_playwright(auction)
        except Exception as exc:  # noqa: BLE001
            logger.info("Auction metadata enrichment via Playwright failed (%s). Trying requests.", exc)
            try:
                html = self._requests_get(auction.url)
                return parse_auction_details_from_html(html, auction)
            except Exception as exc2:  # noqa: BLE001
                logger.info("Auction metadata enrichment via requests failed (%s).", exc2)
                return auction

    def _enrich_auction_playwright(self, auction: Auction) -> Auction:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()

            self._attach_network_logger(page, auction_id=auction.auction_id)

            self.rate_limiter.wait()
            page.goto(auction.url, wait_until="domcontentloaded", timeout=int(self.timeout_sec * 1000))
            page.wait_for_load_state("networkidle", timeout=int(self.timeout_sec * 1000))

            enriched = parse_auction_details_from_html(page.content(), auction)

            context.close()
            browser.close()
            return enriched

    def _discover_auctions_requests(self, max_auctions: Optional[int]) -> list[Auction]:
        html = self._requests_get(BASE_URL)
        auctions = parse_auction_cards_from_home(html, base_url=BASE_URL)
        if max_auctions is not None:
            auctions = auctions[:max_auctions]
        return auctions

    def _discover_auctions_playwright(self, max_auctions: Optional[int]) -> list[Auction]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()

            network_log = self.output_dir / "network.jsonl"

            # Log only endpoint metadata (avoid storing response bodies).
            self._attach_network_logger(page)

            self.rate_limiter.wait()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=int(self.timeout_sec * 1000))
            page.wait_for_load_state("networkidle", timeout=int(self.timeout_sec * 1000))

            # Wait until at least one 'Detalhes' link appears (if present)
            try:
                page.locator("a", has_text=re.compile(r"detalhes", re.IGNORECASE)).first.wait_for(timeout=5000)
            except Exception:
                pass

            # Heuristic: click "Carregar mais" if exists (bounded), waiting for new cards.
            for _ in range(6):
                btn = page.get_by_role("button", name=re.compile(r"carregar|mais", re.IGNORECASE))
                if btn.count() == 0:
                    break
                try:
                    prev_count = page.locator("a", has_text=re.compile(r"detalhes", re.IGNORECASE)).count()
                    self.rate_limiter.wait()
                    btn.first.click(timeout=1500)
                    page.wait_for_load_state("networkidle", timeout=int(self.timeout_sec * 1000))
                    # Wait for new 'Detalhes' links to appear (best-effort)
                    page.wait_for_function(
                        "(prev) => Array.from(document.querySelectorAll('a')).filter(a => (a.innerText||'').toLowerCase().includes('detalhes')).length > prev",
                        arg=max(0, prev_count),
                        timeout=3000,
                    )
                except Exception:
                    break

            # Parse via HTML so we can extract metadata from cards.
            auctions = parse_auction_cards_from_home(page.content(), base_url=BASE_URL)

            if max_auctions is not None:
                auctions = auctions[:max_auctions]

            context.close()
            browser.close()
            return auctions

    def crawl_auction_lots(
        self,
        auction: Auction,
        max_pages: Optional[int] = None,
        dry_run: bool = False,
    ) -> list[Lot]:
        """Crawl all lots pages for one auction.

        This is Playwright-first because pagination is often client-rendered.
        Falls back to trying query-param pagination if possible.
        """
        if not self._respect(auction.url):
            return []

        out_jsonl = self.output_dir / "raw" / auction.auction_id / "lots.jsonl"
        existing = self._load_existing_lots(out_jsonl)
        lots_all: list[Lot] = list(existing.values())

        try:
            lots_all = self._crawl_auction_lots_playwright(
                auction=auction,
                out_jsonl=out_jsonl,
                max_pages=max_pages,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playwright lots crawl failed for %s (%s). Trying requests fallback.", auction.url, exc)
            lots_all = self._crawl_auction_lots_requests_fallback(
                auction=auction,
                out_jsonl=out_jsonl,
                max_pages=max_pages,
                dry_run=dry_run,
            )

        return lots_all

    def _load_existing_lots(self, out_jsonl: Path) -> dict[str, Lot]:
        """Load already collected lots from the raw JSONL file (best-effort).

        Supports resume without re-fetching already completed pages.
        """
        if not out_jsonl.exists():
            return {}

        uniq: dict[str, Lot] = {}
        try:
            with out_jsonl.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import json as _json

                        obj = _json.loads(line)
                        lot_d = obj.get("lot") if isinstance(obj, dict) else None
                        if isinstance(lot_d, dict):
                            lot = lot_from_dict(lot_d)
                            uniq[lot.lot_id] = lot
                    except Exception:
                        continue
        except Exception:
            return uniq

        return uniq

    def _crawl_auction_lots_requests_fallback(
        self,
        auction: Auction,
        out_jsonl: Path,
        max_pages: Optional[int],
        dry_run: bool,
    ) -> list[Lot]:
        # If already collected page 1, reuse existing data.
        if self.checkpoint.is_page_done(auction.auction_id, 1):
            return list(self._load_existing_lots(out_jsonl).values())

        # Minimal fallback: fetch the details page once and attempt to parse visible cards.
        # If the site is JS-heavy, this will likely return few/no lots.
        html = self._requests_get(auction.url)
        lots = parse_lot_cards_from_html(html, auction.auction_id, page_url=auction.url)
        for l in lots:
            jsonl_append(out_jsonl, {"page": 1, "lot": asdict(l)})
        self.checkpoint.mark_page_done(auction.auction_id, 1)
        self.checkpoint.save()
        return lots

    def _crawl_auction_lots_playwright(
        self,
        auction: Auction,
        out_jsonl: Path,
        max_pages: Optional[int],
        dry_run: bool,
    ) -> list[Lot]:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()

            # Collect JSON traffic for this auction for JSON-first crawling.
            json_traffic: list[dict[str, Any]] = []
            self._attach_network_logger(page, collector=json_traffic, auction_id=auction.auction_id)

            self.rate_limiter.wait()
            page.goto(auction.url, wait_until="domcontentloaded", timeout=int(self.timeout_sec * 1000))
            page.wait_for_load_state("networkidle", timeout=int(self.timeout_sec * 1000))

            # JSON-first attempt: if we observed a JSON endpoint that returns lots, paginate it.
            api_lots = self._try_crawl_lots_via_json_api(
                auction_id=auction.auction_id,
                json_traffic=json_traffic,
                context=context,
                out_jsonl=out_jsonl,
                max_pages=max_pages,
                dry_run=dry_run,
            )
            if api_lots:
                context.close()
                browser.close()
                uniq: dict[str, Lot] = {l.lot_id: l for l in api_lots}
                return list(uniq.values())

            # Start with any previously collected lots (resume).
            existing = self._load_existing_lots(out_jsonl)

            # Navigate pages using pagination controls if present.
            # Heuristic: look for pagination buttons/links with numbers.
            lots_all: list[Lot] = list(existing.values())
            current_page_num = 1

            def extract_current_page_lots() -> list[Lot]:
                html = page.content()
                return parse_lot_cards_from_html(html, auction.auction_id, page_url=page.url)

            # Always process page 1
            if not self.checkpoint.is_page_done(auction.auction_id, 1):
                lots = extract_current_page_lots()
                for l in lots:
                    jsonl_append(out_jsonl, {"page": 1, "lot": asdict(l)})
                lots_all.extend(lots)
                self.checkpoint.mark_page_done(auction.auction_id, 1)
                self.checkpoint.save()

            if dry_run:
                # dry-run: only 1-2 pages
                max_pages = min(max_pages or 2, 2)

            while True:
                if max_pages is not None and current_page_num >= max_pages:
                    break

                next_page_num = current_page_num + 1
                if self.checkpoint.is_page_done(auction.auction_id, next_page_num):
                    current_page_num = next_page_num
                    continue

                # Try click pagination control for next page number
                clicked = False
                before_url = page.url
                before_first_lot = None
                try:
                    current = extract_current_page_lots()
                    before_first_lot = current[0].lot_id if current else None
                except Exception:
                    before_first_lot = None
                try:
                    locator = page.get_by_role("link", name=str(next_page_num))
                    if locator.count() > 0:
                        self.rate_limiter.wait()
                        locator.first.click(timeout=2500)
                        clicked = True
                    else:
                        btn = page.get_by_role("button", name=str(next_page_num))
                        if btn.count() > 0:
                            self.rate_limiter.wait()
                            btn.first.click(timeout=2500)
                            clicked = True
                except Exception:
                    clicked = False

                if not clicked:
                    # Try next arrow
                    try:
                        nxt = page.get_by_role("link", name=re.compile(r"próx|next|>+", re.IGNORECASE))
                        if nxt.count() > 0:
                            self.rate_limiter.wait()
                            nxt.first.click(timeout=2500)
                            clicked = True
                    except Exception:
                        clicked = False

                if not clicked:
                    break

                # Wait for navigation/content change.
                page.wait_for_load_state("networkidle", timeout=int(self.timeout_sec * 1000))
                try:
                    if page.url != before_url:
                        pass
                    elif before_first_lot is not None:
                        page.wait_for_function(
                            "(prevLotId) => { const txt = document.body ? document.body.innerText : ''; return !txt.includes(prevLotId); }",
                            arg=str(before_first_lot),
                            timeout=5000,
                        )
                except Exception:
                    # Best-effort; continue anyway.
                    pass

                lots = extract_current_page_lots()
                for l in lots:
                    jsonl_append(out_jsonl, {"page": next_page_num, "lot": asdict(l)})
                lots_all.extend(lots)

                self.checkpoint.mark_page_done(auction.auction_id, next_page_num)
                self.checkpoint.save()

                current_page_num = next_page_num

            context.close()
            browser.close()

            # De-dup by lot_id
            uniq: dict[str, Lot] = {}
            for l in lots_all:
                uniq[l.lot_id] = l
            return list(uniq.values())

    def _attach_network_logger(
        self,
        page: Page,
        collector: Optional[list[dict[str, Any]]] = None,
        auction_id: Optional[str] = None,
    ) -> None:
        network_log = self.output_dir / "network.jsonl"
        # Per-auction audit log (metadata only).
        per_auction_log = None
        if auction_id:
            per_auction_log = self.output_dir / "raw" / auction_id / "api_endpoints.jsonl"

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "application/json" in ct:
                    req = resp.request
                    entry: dict[str, Any] = {
                        "url": resp.url,
                        "status": resp.status,
                        "content_type": ct,
                        "method": req.method,
                        "request_headers": redact_headers(req.headers),
                    }
                    try:
                        pd = req.post_data
                        if pd:
                            entry["post_data"] = "<redacted>" if len(pd) > 50_000 else pd
                    except Exception:
                        pass

                    # Only parse JSON body for in-memory collector (to avoid persisting payloads on disk).
                    body_obj = None
                    if collector is not None:
                        try:
                            body_obj = resp.json()
                            entry["json"] = body_obj
                        except Exception:
                            entry["json"] = None

                    jsonl_append(
                        network_log,
                        {
                            "url": resp.url,
                            "status": resp.status,
                            "content_type": ct,
                        },
                    )

                    if per_auction_log is not None:
                        # Strip any parsed body before writing to disk
                        entry_disk = {k: v for k, v in entry.items() if k != "json"}
                        jsonl_append(per_auction_log, entry_disk)
                    if collector is not None:
                        collector.append(entry)
            except Exception:
                return

        page.on("response", on_response)

    def _try_crawl_lots_via_json_api(
        self,
        auction_id: str,
        json_traffic: list[dict[str, Any]],
        context,
        out_jsonl: Path,
        max_pages: Optional[int],
        dry_run: bool,
    ) -> list[Lot]:
        """Try to identify a lots-listing JSON endpoint and paginate it.

        This does NOT bypass login/captcha. If the endpoint requires auth (401/403),
        we log and fall back to HTML.
        """
        if not json_traffic:
            return []

        # Select best candidate: JSON response whose body yields the most lots.
        best = None
        best_lots: list[Lot] = []
        for e in json_traffic[-200:]:
            body = e.get("json")
            if body is None:
                continue
            try:
                lots = extract_lots_from_json(body, auction_id=auction_id)
            except Exception:
                continue
            if len(lots) > len(best_lots):
                best = e
                best_lots = lots

        if best is None or not best_lots:
            return []

        # If page 1 already done, don't re-save, but still use this path for pagination.
        if not self.checkpoint.is_page_done(auction_id, 1):
            for l in best_lots:
                jsonl_append(out_jsonl, {"page": 1, "lot": asdict(l), "source": "api"})
            self.checkpoint.mark_page_done(auction_id, 1)
            self.checkpoint.save()

        total_pages = None
        try:
            total_pages = get_total_pages(best.get("json"))
        except Exception:
            total_pages = None

        # Dry-run: only 1-2 pages
        if dry_run:
            max_pages = min(max_pages or 2, 2)

        # Determine how far to go.
        if max_pages is not None:
            target_pages = max_pages
        elif total_pages is not None:
            target_pages = total_pages
        else:
            # Unknown; attempt a few pages until empty.
            target_pages = 50

        method = str(best.get("method") or "GET").upper()
        base_url = str(best.get("url"))
        headers = best.get("request_headers") or {}
        post_data = best.get("post_data")

        lots_all = list(best_lots)

        for page_num in range(2, target_pages + 1):
            if max_pages is not None and page_num > max_pages:
                break
            if self.checkpoint.is_page_done(auction_id, page_num):
                continue

            url = base_url
            body_text = None
            if method == "GET":
                url = paginate_url(base_url, page_num)
            elif method == "POST":
                body_text = paginate_payload(post_data if isinstance(post_data, str) else None, page_num)
            else:
                # Unsupported method
                break

            if not self._respect(url):
                break

            self.rate_limiter.wait()
            try:
                if method == "GET":
                    resp = context.request.get(url, headers={**headers, "User-Agent": self.user_agent}, timeout=self.timeout_sec * 1000)
                else:
                    resp = context.request.post(
                        url,
                        headers={**headers, "User-Agent": self.user_agent, "Content-Type": "application/json"},
                        data=body_text or "{}",
                        timeout=self.timeout_sec * 1000,
                    )

                if resp.status in (401, 403):
                    logger.info("API requires login for auction %s (status=%s). Falling back to HTML.", auction_id, resp.status)
                    return []

                if not resp.ok:
                    logger.info("API page fetch failed auction=%s page=%s status=%s", auction_id, page_num, resp.status)
                    break

                data = resp.json()
                lots = extract_lots_from_json(data, auction_id=auction_id)
                if not lots:
                    # If total pages unknown, stop when empty.
                    if total_pages is None:
                        break
                for l in lots:
                    jsonl_append(out_jsonl, {"page": page_num, "lot": asdict(l), "source": "api"})
                lots_all.extend(lots)

                self.checkpoint.mark_page_done(auction_id, page_num)
                self.checkpoint.save()
            except Exception as exc:  # noqa: BLE001
                logger.info("API pagination error auction=%s page=%s (%s)", auction_id, page_num, exc)
                break

        # De-dup
        uniq: dict[str, Lot] = {l.lot_id: l for l in lots_all}
        return list(uniq.values())

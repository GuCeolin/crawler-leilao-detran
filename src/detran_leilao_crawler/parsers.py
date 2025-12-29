from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .logging_utils import safe_float
from .models import Auction, Lot


_WS = re.compile(r"\s+")


def norm_text(s: str) -> str:
    return _WS.sub(" ", (s or "").strip())


def parse_year(text: str) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def parse_datetime_loose(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return dateparser.parse(text, dayfirst=True, fuzzy=True)
    except Exception:  # noqa: BLE001
        return None


def _extract_kv(text: str, keys: list[str]) -> Optional[str]:
    t = norm_text(text)
    for k in keys:
        m = re.search(rf"\b{k}\b\s*[:\-]?\s*(.+?)($|\s{2,}|\b[A-Z][a-z]+\b\s*[:\-])", t, re.IGNORECASE)
        if m:
            return norm_text(m.group(1))
    return None


def _guess_auction_number(text: str) -> Optional[str]:
    t = norm_text(text)
    m = re.search(r"\b(leil[aã]o)\s*(n[ºo]\.?|n\b|n\s*o)?\s*[:\-]?\s*([0-9]{1,10}(?:\/[0-9]{2,4})?)\b", t, re.IGNORECASE)
    if m:
        return m.group(3)
    return None


def _guess_status(text: str) -> Optional[str]:
    t = norm_text(text).lower()
    for k in ["publicado", "aberto", "encerrado", "finalizado", "em andamento"]:
        if k in t:
            return k
    return None


def parse_auction_details_from_html(html: str, auction: Auction) -> Auction:
    """Best-effort parse of auction details page.

    This function is defensive by design; the site may change markup.
    """
    soup = BeautifulSoup(html, "lxml")
    text = norm_text(soup.get_text(" "))

    number = auction.number or _guess_auction_number(text)
    city = auction.city or _extract_kv(text, ["cidade", "munic[ií]pio", "local"])  # best-effort
    yard = auction.yard or _extract_kv(text, ["p[aá]tio", "patio"])  # best-effort
    organizer = auction.organizer or _extract_kv(text, ["organizador", "leiloeiro"])  # best-effort
    status = auction.status or _guess_status(text)

    ends_at = auction.ends_at
    if ends_at is None:
        # Common labels for closing date/time
        for label in ["encerramento", "encerra", "data/hora", "data e hora", "t[ée]rmino", "termino"]:
            m = re.search(rf"\b{label}\b\s*[:\-]?\s*(.+?)($|\s{2,})", text, re.IGNORECASE)
            if m:
                ends_at = parse_datetime_loose(m.group(1))
                if ends_at:
                    break

    return Auction(
        auction_id=auction.auction_id,
        url=auction.url,
        number=number,
        city=city,
        yard=yard,
        organizer=organizer,
        status=status,
        ends_at=ends_at,
    )


def parse_auction_cards_from_home(html: str, base_url: str) -> list[Auction]:
    """Best-effort HTML parsing of auctions from home.

    This is intentionally defensive; selectors may change. Playwright is preferred.
    """
    soup = BeautifulSoup(html, "lxml")
    auctions: list[Auction] = []

    # Heuristic: links/buttons containing 'Detalhes'
    for a in soup.select("a"):
        label = norm_text(a.get_text(" "))
        if "detalhes" not in label.lower():
            continue
        href = a.get("href")
        if not href:
            continue
        url = href if href.startswith("http") else base_url.rstrip("/") + "/" + href.lstrip("/")
        auction_id = re.sub(r"\W+", "-", url).strip("-").lower()

        # Try to extract metadata from the closest container text.
        container = a
        for _ in range(4):
            if container and getattr(container, "name", None) in {"div", "article", "section", "li"}:
                break
            container = container.parent
        block_text = norm_text(container.get_text(" ")) if container else ""

        number = _guess_auction_number(block_text)
        city = _extract_kv(block_text, ["cidade", "munic[ií]pio", "local"])  # best-effort
        yard = _extract_kv(block_text, ["p[aá]tio", "patio"])  # best-effort
        organizer = _extract_kv(block_text, ["organizador", "leiloeiro"])  # best-effort
        status = _guess_status(block_text)
        ends_at = None
        m_end = re.search(r"\b(encerramento|encerra)\b\s*[:\-]?\s*(.+)$", block_text, re.IGNORECASE)
        if m_end:
            ends_at = parse_datetime_loose(m_end.group(2))

        auctions.append(
            Auction(
                auction_id=auction_id,
                url=url,
                number=number,
                city=city,
                yard=yard,
                organizer=organizer,
                status=status,
                ends_at=ends_at,
            )
        )

    # De-dup by url
    uniq: dict[str, Auction] = {}
    for x in auctions:
        uniq[x.url] = x
    return list(uniq.values())


def parse_lot_cards_from_html(html: str, auction_id: str, page_url: str) -> list[Lot]:
    """Best-effort HTML parsing of lots list page.

    Requires stable site markup to be effective; Playwright + JSON endpoints preferred.
    """
    soup = BeautifulSoup(html, "lxml")
    lots: list[Lot] = []

    # Heuristic: cards with images + some text including 'Lote'
    cards = soup.select("div, article")
    for card in cards:
        text = norm_text(card.get_text(" "))
        if not text or "lote" not in text.lower():
            continue

        requires_login = "login" in text.lower() and "obrig" in text.lower()

        soup = BeautifulSoup(html, "lxml")
        lots: list[Lot] = []

        # Prefer the known structure for this site.
        base = page_url
        site_cards = soup.select("div.card.listaLotes")
        if site_cards:
            for card in site_cards:
                card_text = norm_text(card.get_text(" "))
                card_id = (card.get("id") or "").strip()
                lot_id = card_id if card_id else None

                # Visible header: "Lote 1 - CONSERVADO"
                header_b = card.select_one("div.card-body b")
                header_text = norm_text(header_b.get_text(" ")) if header_b else None

                # Extract lot number if needed (not stored separately yet)
                m_lote_num = re.search(r"\bLote\s*([0-9]+[a-zA-Z0-9\-\.]*)\b", header_text or card_text, re.IGNORECASE)

                # Situation is usually the second span in header line.
                situation = None
                spans = card.select("div.card-body b span")
                if spans:
                    # expected: ["Lote 1", "CONSERVADO"]
                    if len(spans) >= 2:
                        situation = norm_text(spans[1].get_text(" ")) or None
                if not situation:
                    # fallback: common labels
                    t_low = card_text.lower()
                    for k in ["sem reserva", "com reserva", "sucata", "recuperável", "recuperavel", "circula", "não circula", "nao circula"]:
                        if k in t_low:
                            situation = k
                            break

                # Brand/model line is in the centered 40px row: <b>HONDA/CBX 250 TWISTER 2006</b>
                brand_model_full = None
                bm_el = None
                for candidate in card.select("div.row div.col-12.text-center b"):
                    t = norm_text(candidate.get_text(" "))
                    if not t:
                        continue
                    # Ignore the header that contains "Lote"
                    if re.search(r"\blote\b", t, re.IGNORECASE):
                        continue
                    bm_el = candidate
                    brand_model_full = t
                    break

                year = parse_year(brand_model_full or "") or parse_year(card_text)

                brand_model = None
                if brand_model_full:
                    # If year is the last token, strip it from brand_model.
                    if year is not None:
                        brand_model = re.sub(rf"\s*\b{year}\b\s*$", "", brand_model_full).strip() or brand_model_full
                    else:
                        brand_model = brand_model_full

                # Start bid: <p id="valor_atual_lote_<id>">R$ 400,00</p>
                start_bid = None
                if lot_id:
                    bid_el = card.select_one(f"#valor_atual_lote_{lot_id}")
                    if bid_el:
                        start_bid = safe_float(norm_text(bid_el.get_text(" ")))
                if start_bid is None:
                    m2 = re.search(r"R\$\s*[0-9\.,]+", card_text)
                    if m2:
                        start_bid = safe_float(m2.group(0))

                # Images
                imgs: list[str] = []
                for img in card.select("img"):
                    src = (img.get("src") or "").strip()
                    if not src:
                        continue
                    imgs.append(urllib.parse.urljoin(base, src))

                # Determine lot details URL from onclick (preferred)
                lot_url = None
                onclick = None
                clickable = card.select_one("span[onclick]")
                if clickable:
                    onclick = clickable.get("onclick")
                if onclick:
                    m = re.search(r"/lotes/detalhes/\d+", onclick)
                    if m:
                        lot_url = urllib.parse.urljoin(base, m.group(0))

                # Requires login: explicit button/link
                requires_login = False
                for a in card.select("a"):
                    label = norm_text(a.get_text(" ")).lower()
                    href = (a.get("href") or "").lower()
                    if "login obrigat" in label or "/ssc/login/login" in href:
                        requires_login = True
                        break

                # Fallback lot id using "Lote N" if card id missing
                if not lot_id and m_lote_num:
                    lot_id = m_lote_num.group(1)
                if not lot_id:
                    lot_id = re.sub(r"\W+", "-", (header_text or card_text)[:60]).strip("-").lower() or "unknown"

                description_short = header_text or (f"Lote {m_lote_num.group(1)}" if m_lote_num else None) or card_text

                lots.append(
                    Lot(
                        auction_id=auction_id,
                        lot_id=str(lot_id),
                        description_short=description_short[:180],
                        brand_model=brand_model,
                        year=year,
                        situation=situation,
                        start_bid=start_bid,
                        ends_at=None,
                        lot_url=lot_url,
                        image_urls=tuple(imgs),
                        requires_login=requires_login,
                        raw_text=card_text,
                    )
                )

            uniq: dict[str, Lot] = {l.lot_id: l for l in lots}
            return list(uniq.values())

        # Fallback: heuristic scanning if the expected structure isn't found.
        cards = soup.select("div, article")
        for card in cards:
            text = norm_text(card.get_text(" "))
            if not text or "lote" not in text.lower():
                continue

            requires_login = "login" in text.lower() and "obrig" in text.lower()

            m = re.search(r"\bLote\s*[:#-]?\s*([0-9]+[a-zA-Z0-9\-\.]*)\b", text, re.IGNORECASE)
            lot_id = m.group(1) if m else None
            if not lot_id:
                lot_id = re.sub(r"\W+", "-", text[:60]).strip("-").lower() or "unknown"

            year = parse_year(text)

            t_low = text.lower()
            situation = None
            for k in ["sem reserva", "com reserva", "sucata", "recuper[áa]vel", "circula", "n[aã]o circula"]:
                if re.search(k, t_low, re.IGNORECASE):
                    situation = k
                    break

            start_bid = None
            m2 = re.search(r"R\$\s*[0-9\.,]+", text)
            if m2:
                start_bid = safe_float(m2.group(0))

            ends_at = None
            m_end = re.search(r"\b(encerramento|encerra)\b\s*[:\-]?\s*(.+)$", text, re.IGNORECASE)
            if m_end:
                ends_at = parse_datetime_loose(m_end.group(2))

            brand_model = None
            lines = [norm_text(x) for x in card.get_text("\n").split("\n")]
            lines = [x for x in lines if x]
            for ln in lines[:6]:
                if re.search(r"\blote\b", ln, re.IGNORECASE):
                    continue
                if re.search(r"R\$\s*[0-9\.,]+", ln):
                    continue
                if re.search(r"encerr", ln, re.IGNORECASE):
                    continue
                if len(ln) >= 3:
                    brand_model = ln
                    break

            imgs = [urllib.parse.urljoin(base, img.get("src")) for img in card.select("img") if img.get("src")]

            link = None
            for a in card.select("a"):
                href = a.get("href")
                if href and ("lote" in href.lower() or "detal" in a.get_text(" ").lower()):
                    link = urllib.parse.urljoin(base, href)
                    break

            lots.append(
                Lot(
                    auction_id=auction_id,
                    lot_id=str(lot_id),
                    description_short=text[:180] if len(text) > 0 else "(sem descrição)",
                    brand_model=brand_model,
                    year=year,
                    situation=situation,
                    start_bid=start_bid,
                    ends_at=ends_at,
                    lot_url=link,
                    image_urls=tuple(imgs),
                    requires_login=requires_login,
                    raw_text=text,
                )
            )

        uniq: dict[str, Lot] = {}
        for l in lots:
            uniq[l.lot_id] = l
        return list(uniq.values())

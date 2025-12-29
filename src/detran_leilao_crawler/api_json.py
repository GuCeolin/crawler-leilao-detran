from __future__ import annotations

import json
import logging
import re
import urllib.parse
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, Optional

from dateutil import parser as dateparser

from .logging_utils import safe_float
from .models import Lot


logger = logging.getLogger(__name__)


_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for k, v in (headers or {}).items():
        if k.lower() in _SENSITIVE_HEADERS:
            redacted[k] = "<redacted>"
        else:
            redacted[k] = v
    return redacted


def _iter_candidate_item_lists(obj: Any) -> Iterable[list[Any]]:
    if isinstance(obj, list):
        yield obj
        return
    if not isinstance(obj, dict):
        return

    # Common containers
    for key in [
        "items",
        "content",
        "data",
        "result",
        "results",
        "registros",
        "lotes",
        "lots",
        "rows",
    ]:
        v = obj.get(key)
        if isinstance(v, list):
            yield v
        elif isinstance(v, dict):
            yield from _iter_candidate_item_lists(v)

    # Any list-of-dicts value
    for v in obj.values():
        if isinstance(v, list) and v and isinstance(v[0], (dict, str, int)):
            yield v


def _get_first(obj: dict[str, Any], keys: list[str]) -> Optional[Any]:
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    # also try case-insensitive
    low = {str(k).lower(): k for k in obj.keys()}
    for k in keys:
        kk = low.get(k.lower())
        if kk is not None and obj[kk] is not None:
            return obj[kk]
    return None


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Heuristic: unix epoch seconds
        try:
            if value > 10_000_000_000:
                value = value / 1000.0
            return datetime.fromtimestamp(float(value))
        except Exception:  # noqa: BLE001
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            try:
                return dateparser.parse(s, dayfirst=True, fuzzy=True)
            except Exception:  # noqa: BLE001
                return None
    return None


def get_total_pages(obj: Any) -> Optional[int]:
    if not isinstance(obj, dict):
        return None
    v = _get_first(obj, ["totalPages", "total_pages", "paginas", "qtdPaginas", "lastPage"])
    if isinstance(v, (int, float)):
        try:
            return int(v)
        except Exception:
            return None
    return None


def extract_lots_from_json(obj: Any, auction_id: str) -> list[Lot]:
    lots: list[Lot] = []

    for items in _iter_candidate_item_lists(obj):
        if not items:
            continue
        # Filter to dict-like items
        dict_items = [x for x in items if isinstance(x, dict)]
        if not dict_items:
            continue

        # Heuristic: must contain something that looks like lote id/description
        score = 0
        sample = dict_items[0]
        sample_keys = {k.lower() for k in sample.keys()}
        if any(k in sample_keys for k in ["lote", "loteid", "id", "numero", "numerolote", "codigolote"]):
            score += 1
        if any("desc" in k for k in sample_keys) or any(k in sample_keys for k in ["modelo", "marca", "marcamodelo"]):
            score += 1
        if score == 0:
            continue

        for it in dict_items:
            lot_id = _get_first(
                it,
                [
                    "lotId",
                    "loteId",
                    "id",
                    "lote",
                    "numeroLote",
                    "numLote",
                    "codigoLote",
                    "codigo",
                    "numero",
                ],
            )
            lot_id_s = str(lot_id) if lot_id is not None else "unknown"

            desc = _get_first(
                it,
                [
                    "descricaoCurta",
                    "descricao",
                    "descricaoResumida",
                    "nome",
                    "titulo",
                    "title",
                ],
            )
            desc_s = str(desc).strip() if desc is not None else "(sem descrição)"

            brand = _get_first(it, ["marcaModelo", "marca_modelo", "marca", "brand"])
            model = _get_first(it, ["modelo", "model"])
            brand_model = None
            if brand and model:
                brand_model = f"{brand} {model}".strip()
            elif brand:
                brand_model = str(brand).strip()
            elif model:
                brand_model = str(model).strip()

            year = _get_first(it, ["ano", "anoModelo", "ano_modelo", "anoFabricacao", "ano_fabricacao", "year"])
            year_i: Optional[int] = None
            try:
                if year is not None and str(year).strip():
                    m = re.search(r"(19\d{2}|20\d{2})", str(year))
                    if m:
                        year_i = int(m.group(1))
            except Exception:
                year_i = None

            situation = _get_first(it, ["situacao", "status", "tipo", "categoria"])
            situation_s = str(situation).strip() if situation is not None else None

            start_bid = _get_first(it, ["lanceInicial", "valorInicial", "valorMinimo", "precoInicial", "startBid"])
            start_bid_f = None
            if isinstance(start_bid, (int, float)):
                start_bid_f = float(start_bid)
            else:
                start_bid_f = safe_float(str(start_bid)) if start_bid is not None else None

            ends_at = _parse_dt(_get_first(it, ["dataEncerramento", "encerramento", "fim", "endsAt"]))

            lot_url = _get_first(it, ["url", "link", "detalheUrl", "detailsUrl"])
            lot_url_s = str(lot_url).strip() if lot_url is not None else None

            imgs_val = _get_first(it, ["imagens", "images", "fotos", "fotosUrl", "photos"])
            image_urls: list[str] = []
            if isinstance(imgs_val, list):
                for im in imgs_val:
                    if isinstance(im, str):
                        image_urls.append(im)
                    elif isinstance(im, dict):
                        u = _get_first(im, ["url", "src", "caminho", "path"])
                        if u:
                            image_urls.append(str(u))

            lots.append(
                Lot(
                    auction_id=auction_id,
                    lot_id=lot_id_s,
                    description_short=desc_s[:180],
                    brand_model=brand_model,
                    year=year_i,
                    situation=situation_s,
                    start_bid=start_bid_f,
                    ends_at=ends_at,
                    lot_url=lot_url_s,
                    image_urls=tuple(image_urls),
                    requires_login=False,
                    raw_text=None,
                )
            )

        # If we successfully parsed from a good list, stop at first plausible list.
        if lots:
            return lots

    return lots


def paginate_url(url: str, page_num: int) -> str:
    """Try to update common page query params in a URL."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    # Common patterns
    for key in ["page", "pagina", "pageNumber", "pageIndex", "p"]:
        if key in qs:
            qs[key] = [str(page_num)]
            new_q = urllib.parse.urlencode(qs, doseq=True)
            return urllib.parse.urlunparse(parsed._replace(query=new_q))

    # offset/limit
    if "offset" in qs and "limit" in qs:
        try:
            limit = int(qs["limit"][0])
            qs["offset"] = [str((page_num - 1) * limit)]
            new_q = urllib.parse.urlencode(qs, doseq=True)
            return urllib.parse.urlunparse(parsed._replace(query=new_q))
        except Exception:
            return url

    # If no param exists, keep as-is.
    return url


def paginate_payload(payload_text: Optional[str], page_num: int) -> Optional[str]:
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except Exception:
        return payload_text

    if isinstance(payload, dict):
        for key in ["page", "pagina", "pageNumber", "pageIndex"]:
            if key in payload:
                payload[key] = page_num
                return json.dumps(payload, ensure_ascii=False)
        if "offset" in payload and "limit" in payload:
            try:
                limit = int(payload["limit"])
                payload["offset"] = (page_num - 1) * limit
                return json.dumps(payload, ensure_ascii=False)
            except Exception:
                return json.dumps(payload, ensure_ascii=False)

    return json.dumps(payload, ensure_ascii=False)

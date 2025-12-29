from __future__ import annotations

import argparse
import logging
from pathlib import Path
import shutil

from .config import load_filters_config
from .filters import FilterEngine, filter_lots
from .logging_utils import setup_logging
from .models import LotImage
from .crawler import DetranLeilaoCrawler
from .serde import auction_from_dict, lot_from_dict
from .storage import init_sqlite, upsert_sqlite, write_csv, write_json


logger = logging.getLogger(__name__)


def _cmd_crawl(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    setup_logging(output_dir)

    crawler = DetranLeilaoCrawler(
        output_dir=output_dir,
        headless=args.headless,
        rate_limit_per_sec=args.rate_limit,
        timeout_sec=args.timeout,
    )
    crawler.init()

    auctions = crawler.discover_auctions(max_auctions=args.max_auctions)
    logger.info("Discovered %d auctions", len(auctions))

    enriched_auctions = []
    for a in auctions:
        enriched_auctions.append(crawler.enrich_auction_metadata(a))

    auctions_path = output_dir / "auctions.json"
    write_json(auctions_path, enriched_auctions)

    all_lots = []
    for a in enriched_auctions:
        lots = crawler.crawl_auction_lots(a, max_pages=args.max_pages, dry_run=args.dry_run)
        logger.info("Auction %s: %d lots", a.auction_id, len(lots))
        all_lots.extend(lots)

    write_json(output_dir / "lots.json", all_lots)
    logger.info("Total lots collected: %d", len(all_lots))


def _cmd_filter(args: argparse.Namespace) -> None:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(output_dir)

    lots = (input_dir / "lots.json").read_text(encoding="utf-8")
    import json

    lots_data = json.loads(lots)

    lots_objs = [lot_from_dict(d) for d in lots_data]

    cfg = load_filters_config(Path(args.filters))
    engine = FilterEngine.from_dict(cfg)
    kept = filter_lots(lots_objs, engine)

    write_json(output_dir / "lots.filtered.json", kept)
    # Preserve auctions metadata alongside filtered lots
    src_auctions = input_dir / "auctions.json"
    if src_auctions.exists():
        shutil.copy2(src_auctions, output_dir / "auctions.json")
    logger.info("Filtered lots: %d -> %d", len(lots_objs), len(kept))


def _cmd_export(args: argparse.Namespace) -> None:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(output_dir)

    import json

    auctions = [auction_from_dict(d) for d in json.loads((input_dir / "auctions.json").read_text(encoding="utf-8"))]

    # Prefer filtered file if present
    lots_path = input_dir / "lots.filtered.json"
    if not lots_path.exists():
        lots_path = input_dir / "lots.json"
    lots = [lot_from_dict(d) for d in json.loads(lots_path.read_text(encoding="utf-8"))]

    # Images table rows
    images = []
    for l in lots:
        for u in (l.image_urls or []):
            images.append(LotImage(auction_id=l.auction_id, lot_id=l.lot_id, url=u))

    write_csv(output_dir / "auctions.csv", auctions)
    write_csv(output_dir / "lots.csv", lots)
    write_csv(output_dir / "images.csv", images)

    write_json(output_dir / "auctions.json", auctions)
    write_json(output_dir / "lots.json", lots)
    write_json(output_dir / "images.json", images)

    if args.sqlite:
        db_path = output_dir / "data.sqlite"
        init_sqlite(db_path)
        upsert_sqlite(db_path, auctions=auctions, lots=lots, images=images)
        logger.info("SQLite exported: %s", db_path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="detran-leilao-crawler")
    sub = p.add_subparsers(dest="cmd", required=True)

    crawl = sub.add_parser("crawl", help="Collect auctions and lots")
    crawl.add_argument("--headless", action="store_true", default=False)
    crawl.add_argument("--dry-run", action="store_true", default=False)
    crawl.add_argument("--max-auctions", type=int, default=None)
    crawl.add_argument("--max-pages", type=int, default=None)
    crawl.add_argument("--rate-limit", type=float, default=0.5, help="Requests per second")
    crawl.add_argument("--timeout", type=float, default=30.0)
    crawl.add_argument("--output-dir", type=str, required=True)
    crawl.set_defaults(func=_cmd_crawl)

    flt = sub.add_parser("filter", help="Filter lots using YAML/JSON config")
    flt.add_argument("--input-dir", type=str, required=True)
    flt.add_argument("--filters", type=str, required=True)
    flt.add_argument("--output-dir", type=str, required=True)
    flt.set_defaults(func=_cmd_filter)

    exp = sub.add_parser("export", help="Export CSV/JSON and optional SQLite")
    exp.add_argument("--input-dir", type=str, required=True)
    exp.add_argument("--output-dir", type=str, required=True)
    exp.add_argument("--sqlite", action="store_true", default=False)
    exp.set_defaults(func=_cmd_export)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

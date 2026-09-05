"""CLI entrypoints used by Makefile targets."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from quantagent.shared.config import get_settings


def init_reference_data() -> None:
    """Seed minimal reference rows required after schema init."""
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO industry_taxonomy (code, name, market, levels)
                VALUES ('sw_2021', '申万行业分类 2021', 'CN', 3)
                ON CONFLICT (code) DO NOTHING
                """
            )
        )
    print("reference data initialized: industry_taxonomy.sw_2021")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


async def _ingest_prices(
    *,
    symbols: list[str],
    start: date,
    end: date,
    source: str,
    archive_root: Path | None,
) -> None:
    from quantagent.data.collectors.akshare import AksharePriceCollector
    from quantagent.data.collectors.baostock import BaostockPriceCollector
    from quantagent.data.normalizers.price import PriceNormalizer

    if source == "akshare":
        collector = AksharePriceCollector(archive_root=archive_root)
    elif source == "baostock":
        collector = BaostockPriceCollector(archive_root=archive_root)
    else:
        raise SystemExit(f"unsupported source: {source}")

    batch = await collector.collect(end, symbols=symbols, start=start, end=end)
    df = PriceNormalizer().normalize(batch)
    print(
        f"collected source={batch.source} batch_id={batch.batch_id} "
        f"rows_raw={batch.row_count} rows_norm={df.height} path={batch.raw_path}"
    )
    if df.height:
        print(df.head(3))


def _replay_normalize(raw_path: Path) -> None:
    from quantagent.data.normalizers.price import PriceNormalizer

    df = PriceNormalizer().normalize_from_archive(raw_path)
    print(f"replayed normalize path={raw_path} rows={df.height}")
    if df.height:
        print(df.head(5))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantagent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-reference-data", help="Seed taxonomy / reference rows")

    ingest = sub.add_parser("ingest", help="Collect prices and archive raw Parquet")
    ingest.add_argument("--symbols", required=False, help="Comma-separated symbols e.g. 600519.SH,000001.SZ")
    ingest.add_argument("--start", type=_parse_date, default=None)
    ingest.add_argument("--end", type=_parse_date, default=None)
    ingest.add_argument("--daily", action="store_true", help="Use today as start/end")
    ingest.add_argument(
        "--source",
        choices=("akshare", "baostock"),
        default="akshare",
        help="Primary collector (default: akshare)",
    )
    ingest.add_argument("--archive-root", type=Path, default=None)
    ingest.add_argument(
        "--from-archive",
        type=Path,
        default=None,
        help="Replay normalize from an existing raw Parquet (no fetch)",
    )
    ingest.add_argument("--universe", default=None, help="Reserved for W3+ universe ingest")

    for name, help_text in (
        ("features", "Compute features (not yet implemented)"),
        ("backtest", "Run backtest (not yet implemented)"),
        ("report", "Generate daily report (not yet implemented)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--market", default=None)
        p.add_argument("--strategy", default=None)

    args = parser.parse_args(argv)

    if args.command == "init-reference-data":
        init_reference_data()
        return 0

    if args.command == "ingest":
        if args.from_archive is not None:
            _replay_normalize(args.from_archive)
            return 0

        if not args.symbols:
            print("ingest requires --symbols or --from-archive", file=sys.stderr)
            return 2

        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.daily:
            today = date.today()
            start = end = today
        else:
            if args.start is None or args.end is None:
                print("ingest requires --start/--end or --daily", file=sys.stderr)
                return 2
            start, end = args.start, args.end

        asyncio.run(
            _ingest_prices(
                symbols=symbols,
                start=start,
                end=end,
                source=args.source,
                archive_root=args.archive_root,
            )
        )
        return 0

    print(f"command '{args.command}' is not implemented yet (P0 later / P1)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

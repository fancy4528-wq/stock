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


def _load_prices(df, *, source: str, raw_path: Path | None, target_date: date) -> None:
    from quantagent.data.loaders import PriceLoader

    result = PriceLoader().load(
        df,
        source=source,
        raw_path=raw_path,
        target_date=target_date,
    )
    print(
        f"loaded batch_id={result['batch_id']} rows={result['rows_loaded']} "
        f"status={result['status']}"
    )


def _load_financials(df, *, source: str, raw_path: Path | None, target_date: date) -> None:
    from quantagent.data.loaders import FinancialLoader

    result = FinancialLoader().load(
        df,
        source=source,
        raw_path=raw_path,
        target_date=target_date,
    )
    print(
        f"loaded financials batch_id={result['batch_id']} rows={result['rows_loaded']} "
        f"status={result['status']}"
    )


async def _ingest_prices(
    *,
    symbols: list[str],
    start: date,
    end: date,
    source: str,
    archive_root: Path | None,
    load: bool,
    kind: str,
) -> None:
    from quantagent.data.collectors.akshare import AkshareIndexCollector, AksharePriceCollector
    from quantagent.data.collectors.baostock import BaostockPriceCollector
    from quantagent.data.normalizers.price import PriceNormalizer

    if kind == "index":
        if source != "akshare":
            raise SystemExit("index ingest currently supports --source akshare only")
        collector = AkshareIndexCollector(archive_root=archive_root)
    elif source == "akshare":
        collector = AksharePriceCollector(archive_root=archive_root)
    elif source == "baostock":
        collector = BaostockPriceCollector(archive_root=archive_root)
    else:
        raise SystemExit(f"unsupported source: {source}")

    batch = await collector.collect(end, symbols=symbols, start=start, end=end)
    df = PriceNormalizer().normalize(batch)
    print(
        f"collected source={batch.source} dataset={batch.dataset} batch_id={batch.batch_id} "
        f"rows_raw={batch.row_count} rows_norm={df.height} path={batch.raw_path}"
    )
    if df.height:
        print(df.head(3))
    if load and df.height:
        _load_prices(df, source=batch.source, raw_path=batch.raw_path, target_date=end)


async def _ingest_financials(
    *,
    symbols: list[str],
    end: date,
    archive_root: Path | None,
    load: bool,
) -> None:
    from quantagent.data.collectors.akshare import AkshareFinancialCollector
    from quantagent.data.normalizers.financial import FinancialNormalizer

    collector = AkshareFinancialCollector(archive_root=archive_root)
    batch = await collector.collect(end, symbols=symbols)
    df = FinancialNormalizer().normalize(batch)
    print(
        f"collected source={batch.source} dataset={batch.dataset} batch_id={batch.batch_id} "
        f"rows_raw={batch.row_count} rows_norm={df.height} path={batch.raw_path}"
    )
    if df.height:
        preview = df.select(
            ["symbol", "period_end", "period_type", "announced_at", "net_profit"]
        )
        print(preview.head(5))
    if load and df.height:
        _load_financials(df, source=batch.source, raw_path=batch.raw_path, target_date=end)


def _replay_normalize(raw_path: Path, *, load: bool, dataset: str) -> None:
    if dataset == "financial_statement":
        from quantagent.data.normalizers.financial import FinancialNormalizer

        df = FinancialNormalizer().normalize_from_archive(raw_path)
        print(f"replayed financial normalize path={raw_path} rows={df.height}")
        if df.height:
            print(df.head(5))
        if load and df.height:
            source = str(df["source"][0]) if "source" in df.columns else "archive"
            _load_financials(df, source=source, raw_path=raw_path, target_date=date.today())
        return

    from quantagent.data.normalizers.price import PriceNormalizer

    df = PriceNormalizer().normalize_from_archive(raw_path)
    print(f"replayed normalize path={raw_path} rows={df.height}")
    if df.height:
        print(df.head(5))
    if load and df.height:
        source = str(df["source"][0]) if "source" in df.columns else "archive"
        end = df["trade_date"].max()
        _load_prices(df, source=source, raw_path=raw_path, target_date=end)


def _run_backtest(
    *,
    strategy: str,
    symbol: str,
    start: date,
    end: date,
    write_baseline: Path | None,
) -> int:
    if strategy != "buy_and_hold":
        print(f"unsupported strategy: {strategy}", file=sys.stderr)
        return 2

    from quantagent.backtest import BuyAndHoldConfig, BuyAndHoldEngine

    result = BuyAndHoldEngine().run(
        BuyAndHoldConfig(symbol=symbol, start=start, end=end)
    )
    m = result.metrics
    print(
        f"backtest strategy={result.strategy} symbol={result.symbol}\n"
        f"  window={m.start}..{m.end} n_days={m.n_days}\n"
        f"  start_px={m.start_price:.4f} end_px={m.end_price:.4f}\n"
        f"  total_return={m.total_return:.4%} cagr={m.cagr:.4%}\n"
        f"  volatility={m.volatility:.4%} max_drawdown={m.max_drawdown:.4%}\n"
        f"  sharpe={m.sharpe:.3f}"
    )
    if write_baseline is not None:
        write_baseline.parent.mkdir(parents=True, exist_ok=True)
        body = (
            f"# Baseline Results\n\n"
            f"Generated: {date.today().isoformat()}\n\n"
            f"## Buy&Hold — {result.symbol}\n\n"
            f"| Metric | Value |\n|---|---|\n"
            f"| Window | {m.start} .. {m.end} |\n"
            f"| Trading days | {m.n_days} |\n"
            f"| Start / End price | {m.start_price:.4f} / {m.end_price:.4f} |\n"
            f"| Total return | {m.total_return:.4%} |\n"
            f"| CAGR | {m.cagr:.4%} |\n"
            f"| Volatility (ann.) | {m.volatility:.4%} |\n"
            f"| Max drawdown | {m.max_drawdown:.4%} |\n"
            f"| Sharpe (rf=2%) | {m.sharpe:.3f} |\n"
        )
        write_baseline.write_text(body, encoding="utf-8")
        print(f"wrote {write_baseline}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantagent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-reference-data", help="Seed taxonomy / reference rows")

    ingest = sub.add_parser("ingest", help="Collect / normalize / optionally load data")
    ingest.add_argument(
        "--symbols",
        required=False,
        help="Comma-separated symbols e.g. 600519.SH,000001.SZ",
    )
    ingest.add_argument("--start", type=_parse_date, default=None)
    ingest.add_argument("--end", type=_parse_date, default=None)
    ingest.add_argument("--daily", action="store_true", help="Use today as start/end")
    ingest.add_argument(
        "--dataset",
        choices=("price_daily", "financial_statement", "index"),
        default="price_daily",
        help="Dataset to ingest (default: price_daily)",
    )
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
    ingest.add_argument(
        "--load",
        action="store_true",
        help="Validate and write into Postgres",
    )
    ingest.add_argument("--universe", default=None, help="Reserved for universe ingest")

    bt = sub.add_parser("backtest", help="Run backtest strategies")
    bt.add_argument("--strategy", default="buy_and_hold")
    bt.add_argument("--symbol", default="000300.SH", help="Benchmark symbol (default CSI300)")
    bt.add_argument("--start", type=_parse_date, default=date(2015, 1, 1))
    bt.add_argument("--end", type=_parse_date, default=date.today())
    bt.add_argument(
        "--write-baseline",
        type=Path,
        default=None,
        help="Write markdown summary (e.g. docs/baseline-results.md)",
    )
    bt.add_argument("--market", default=None)

    for name, help_text in (
        ("features", "Compute features (not yet implemented)"),
        ("report", "Generate daily report (not yet implemented)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--market", default=None)
        p.add_argument("--strategy", default=None)

    args = parser.parse_args(argv)

    if args.command == "init-reference-data":
        init_reference_data()
        return 0

    if args.command == "backtest":
        return _run_backtest(
            strategy=args.strategy,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            write_baseline=args.write_baseline,
        )

    if args.command == "ingest":
        if args.from_archive is not None:
            dataset = args.dataset
            if dataset == "index":
                dataset = "price_daily"
            _replay_normalize(args.from_archive, load=args.load, dataset=dataset)
            return 0

        if not args.symbols:
            print("ingest requires --symbols or --from-archive", file=sys.stderr)
            return 2

        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

        if args.dataset == "financial_statement":
            end = args.end or date.today()
            asyncio.run(
                _ingest_financials(
                    symbols=symbols,
                    end=end,
                    archive_root=args.archive_root,
                    load=args.load,
                )
            )
            return 0

        kind = "index" if args.dataset == "index" else "price"
        if args.daily:
            today = date.today()
            start = end = today
        elif kind == "index":
            start = args.start or date(2015, 1, 1)
            end = args.end or date.today()
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
                load=args.load,
                kind=kind,
            )
        )
        return 0

    print(f"command '{args.command}' is not implemented yet (P0 later / P1)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

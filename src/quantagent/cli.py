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


def _run_evaluate(
    *,
    market: str,
    panel_path: Path | None,
    factors_arg: str | None,
    synthetic: bool,
    horizon: int,
    n_quantiles: int,
    out_dir: Path,
) -> int:
    import polars as pl

    from quantagent.quant.evaluation import (
        evaluate_factors,
        synthetic_eval_panel,
        write_factor_reports,
    )

    if synthetic or panel_path is None:
        if panel_path is not None:
            print("evaluate: ignoring --panel because --synthetic was set", file=sys.stderr)
        panel = synthetic_eval_panel()
        factor_cols = ["good_factor", "noise_factor"]
        print(f"market={market} mode=synthetic rows={panel.height}")
    else:
        panel = pl.read_parquet(panel_path)
        skip = {
            "security_id",
            "symbol",
            "trade_date",
            "close",
            "open",
            "high",
            "low",
            "volume",
            "amount",
            "turnover_rate",
        }
        if factors_arg:
            factor_cols = [c.strip() for c in factors_arg.split(",") if c.strip()]
        else:
            factor_cols = [c for c in panel.columns if c not in skip and not c.startswith("fwd_")]
        if not factor_cols:
            print("evaluate: no factor columns found in panel", file=sys.stderr)
            return 2
        print(f"market={market} mode=parquet rows={panel.height} factors={factor_cols}")

    results = evaluate_factors(
        panel,
        factor_cols,
        horizon=horizon,
        n_quantiles=n_quantiles,
    )
    paths = write_factor_reports(results, out_dir)
    for code, r in results.items():
        status = "PASS" if r.admission_pass else "FAIL"
        print(
            f"  {code:24s}  ic={r.ic_mean:+.4f}  icir={r.icir:+.3f}  "
            f"t={r.ic_t_stat:+.2f}  admission={status}"
        )
    print(f"wrote {len(paths)} files under {out_dir}")
    return 0


def _load_prices(df: object, *, source: str, raw_path: Path | None, target_date: date) -> None:
    import polars as pl

    from quantagent.data.loaders import PriceLoader

    if not isinstance(df, pl.DataFrame):
        raise TypeError("df must be a polars DataFrame")
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


def _load_financials(df: object, *, source: str, raw_path: Path | None, target_date: date) -> None:
    import polars as pl

    from quantagent.data.loaders import FinancialLoader

    if not isinstance(df, pl.DataFrame):
        raise TypeError("df must be a polars DataFrame")
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


def _load_industry(df: object, *, source: str, raw_path: Path | None, target_date: date) -> None:
    import polars as pl

    from quantagent.data.loaders import IndustryLoader

    if not isinstance(df, pl.DataFrame):
        raise TypeError("df must be a polars DataFrame")
    result = IndustryLoader().load(
        df,
        source=source,
        raw_path=raw_path,
        target_date=target_date,
        snapshot_date=target_date,
    )
    print(
        f"loaded industry batch_id={result['batch_id']} rows={result['rows_loaded']} "
        f"industries={result['industries_upserted']} "
        f"memberships={result['memberships_applied']} status={result['status']}"
    )


def _load_calendar(df: object, *, source: str, raw_path: Path | None, target_date: date) -> None:
    import polars as pl

    from quantagent.core.calendar import load_trading_calendar
    from quantagent.data.loaders import CalendarLoader

    if not isinstance(df, pl.DataFrame):
        raise TypeError("df must be a polars DataFrame")
    result = CalendarLoader().load(
        df,
        source=source,
        raw_path=raw_path,
        target_date=target_date,
    )
    load_trading_calendar.cache_clear()
    n_open = int(df.filter(pl.col("is_open")).height) if "is_open" in df.columns else 0
    print(
        f"loaded calendar batch_id={result['batch_id']} rows={result['rows_loaded']} "
        f"open_days={n_open} status={result['status']}"
    )


async def _ingest_calendar(
    *,
    start: date | None,
    end: date,
    source: str,
    archive_root: Path | None,
    load: bool,
    dual_check: bool,
) -> None:
    import polars as pl

    from quantagent.data.collectors.base import Collector
    from quantagent.data.normalizers.calendar import CalendarNormalizer, open_dates

    collector: Collector
    if source == "akshare":
        from quantagent.data.collectors.akshare import AkshareCalendarCollector

        collector = AkshareCalendarCollector(archive_root=archive_root)
        batch = await collector.collect(end, start=start, end=end)
    elif source == "baostock":
        from quantagent.data.collectors.baostock import BaostockCalendarCollector

        collector = BaostockCalendarCollector(archive_root=archive_root)
        batch = await collector.collect(end, start=start or date(end.year - 10, 1, 1), end=end)
    else:
        raise SystemExit(f"trading_calendar ingest unsupported source={source!r}")

    df = CalendarNormalizer().normalize(batch, start=start, end=end)
    n_open = int(df.filter(pl.col("is_open")).height) if df.height else 0
    print(
        f"collected source={batch.source} dataset={batch.dataset} batch_id={batch.batch_id} "
        f"rows_raw={batch.row_count} dense={df.height} open_days={n_open} path={batch.raw_path}"
    )
    if df.height:
        print(
            df.filter(pl.col("is_open"))
            .select(["trade_date", "is_open", "prev_trade_date", "next_trade_date"])
            .tail(5)
        )

    if dual_check and source == "akshare":
        from quantagent.data.collectors.baostock import BaostockCalendarCollector

        other = BaostockCalendarCollector(archive_root=archive_root)
        # Compare overlapping window (default last ~2y if start omitted)
        chk_start = start or date(end.year - 2, 1, 1)
        other_batch = await other.collect(end, start=chk_start, end=end)
        other_df = CalendarNormalizer().normalize(other_batch, start=chk_start, end=end)
        a = open_dates(df.filter(pl.col("trade_date") >= chk_start))
        b = open_dates(other_df)
        only_a = sorted(a - b)
        only_b = sorted(b - a)
        if only_a or only_b:
            print(
                f"calendar dual-check WARN: akshare_only={len(only_a)} "
                f"baostock_only={len(only_b)} window=[{chk_start}, {end}]"
            )
            if only_a[:5]:
                print(f"  akshare_only sample: {only_a[:5]}")
            if only_b[:5]:
                print(f"  baostock_only sample: {only_b[:5]}")
        else:
            print(f"calendar dual-check OK: open_days={len(a)} window=[{chk_start}, {end}]")

    if load and df.height:
        _load_calendar(df, source=batch.source, raw_path=batch.raw_path, target_date=end)


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
    from quantagent.data.collectors.base import Collector
    from quantagent.data.normalizers.price import PriceNormalizer

    collector: Collector
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
        preview = df.select(["symbol", "period_end", "period_type", "announced_at", "net_profit"])
        print(preview.head(5))
    if load and df.height:
        _load_financials(df, source=batch.source, raw_path=batch.raw_path, target_date=end)


async def _ingest_industry(
    *,
    symbols: list[str] | None,
    end: date,
    archive_root: Path | None,
    load: bool,
) -> None:
    import polars as pl

    from quantagent.data.collectors.akshare import AkshareIndustryCollector
    from quantagent.data.normalizers.industry import IndustryNormalizer

    collector = AkshareIndustryCollector(archive_root=archive_root)
    kwargs: dict[str, object] = {}
    if symbols:
        kwargs["symbols"] = symbols
    batch = await collector.collect(end, **kwargs)
    df = IndustryNormalizer().normalize(batch)
    n_ind = int(df.filter(pl.col("record_type") == "industry").height) if df.height else 0
    n_mem = int(df.filter(pl.col("record_type") == "membership").height) if df.height else 0
    print(
        f"collected source={batch.source} dataset={batch.dataset} batch_id={batch.batch_id} "
        f"rows_raw={batch.row_count} industries={n_ind} memberships={n_mem} path={batch.raw_path}"
    )
    if n_mem:
        preview = df.filter(pl.col("record_type") == "membership").select(
            ["symbol", "industry_code", "industry_name", "level", "valid_from"]
        )
        print(preview.head(5))
    if load and df.height:
        _load_industry(df, source=batch.source, raw_path=batch.raw_path, target_date=end)


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

    if dataset == "security_industry":
        from quantagent.data.normalizers.industry import IndustryNormalizer

        df = IndustryNormalizer().normalize_from_archive(raw_path)
        print(f"replayed industry normalize path={raw_path} rows={df.height}")
        if df.height:
            print(df.head(5))
        if load and df.height:
            source = str(df["source"][0]) if "source" in df.columns else "archive"
            _load_industry(df, source=source, raw_path=raw_path, target_date=date.today())
        return

    if dataset == "trading_calendar":
        from quantagent.data.normalizers.calendar import CalendarNormalizer

        df = CalendarNormalizer().normalize_from_archive(raw_path)
        print(f"replayed calendar normalize path={raw_path} rows={df.height}")
        if df.height:
            print(df.head(5))
        if load and df.height:
            source = str(df["source"][0]) if "source" in df.columns else "archive"
            _load_calendar(df, source=source, raw_path=raw_path, target_date=date.today())
        return

    from quantagent.data.normalizers.price import PriceNormalizer

    df = PriceNormalizer().normalize_from_archive(raw_path)
    print(f"replayed normalize path={raw_path} rows={df.height}")
    if df.height:
        print(df.head(5))
    if load and df.height:
        source = str(df["source"][0]) if "source" in df.columns else "archive"
        end_raw = df["trade_date"].max()
        if not isinstance(end_raw, date):
            raise TypeError(f"trade_date.max() returned {type(end_raw)!r}, expected date")
        _load_prices(df, source=source, raw_path=raw_path, target_date=end_raw)


def _run_portfolio_demo(*, market: str, top_n: int, min_score: float) -> int:
    """Synthetic equal-weight + risk check smoke (no DB)."""
    from quantagent.decision.portfolio import (
        CandidateMeta,
        PortfolioConfig,
        build_equal_weight_portfolio,
    )
    from quantagent.decision.portfolio.config import SelectionConfig, WeightingConfig
    from quantagent.decision.risk import RiskEngine, SecurityContext
    from quantagent.decision.risk.types import PortfolioState

    scores = {f"S{i:02d}": 0.95 - i * 0.02 for i in range(25)}
    meta = {
        s: CandidateMeta(
            symbol=s,
            industry=f"I{i % 4}",
            board="main",
            price=20.0 + i,
            avg_amount_20d=80_000_000.0,
        )
        for i, s in enumerate(scores)
    }
    # Force a few exclusions to demonstrate filtering
    meta["S00"] = meta["S00"].model_copy(update={"is_st": True})
    meta["S01"] = meta["S01"].model_copy(update={"is_suspended": True})

    cfg = PortfolioConfig(
        selection=SelectionConfig(top_n=top_n, min_score=min_score),
        weighting=WeightingConfig(method="equal", max_gross_exposure=0.90, min_cash=0.10),
    )
    target = build_equal_weight_portfolio(scores, meta=meta, cfg=cfg)
    print(
        f"market={market} selected={len(target.selected)} "
        f"gross={sum(target.weights.values()):.4f} cash={target.cash_weight:.4f}"
    )
    for sym in target.selected[:10]:
        print(f"  {sym}  w={target.weights[sym]:.4f}  score={scores[sym]:.2f}")
    if target.excluded:
        sample = list(target.excluded.items())[:5]
        print(f"excluded_sample={sample}")

    as_of = date.today()
    ctx = {
        s: SecurityContext(
            symbol=s,
            industry=meta[s].industry,
            board=meta[s].board,
            price=meta[s].price,
            avg_amount_20d=meta[s].avg_amount_20d,
            is_st=meta[s].is_st,
            is_suspended=meta[s].is_suspended,
        )
        for s in target.weights
    }
    state = PortfolioState(as_of=as_of, cash=100_000.0, total_value=1_000_000.0)
    result = RiskEngine().check(target.weights, state, as_of=as_of, context=ctx)
    print(
        f"risk decision={result.decision.value} "
        f"final_names={len(result.final_target)} "
        f"violations={len(result.violations)} hash={result.config_hash}"
    )
    for v in result.violations[:8]:
        print(f"  {v.rule_code}  {v.action}  {v.detail}" + (f"  [{v.symbol}]" if v.symbol else ""))
    return 0


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

    result = BuyAndHoldEngine().run(BuyAndHoldConfig(symbol=symbol, start=start, end=end))
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


def _run_report(
    *,
    market: str,
    as_of: date | None,
    out_dir: Path,
    shadow_dir: Path,
    synthetic: bool,
    universe: str,
) -> int:
    from quantagent.reporting.pipeline import run_daily_pipeline

    path = asyncio.run(
        run_daily_pipeline(
            as_of=as_of,
            market=market,
            out_dir=out_dir,
            shadow_dir=shadow_dir,
            synthetic=synthetic,
            write_cost_log=True,
            universe_code=universe,
        )
    )
    mode = "synthetic" if synthetic else "live"
    print(f"wrote {path} (mode={mode})")
    return 0


def _run_schedule(
    *,
    once: bool,
    as_of: date | None,
    out_dir: Path,
    shadow_dir: Path,
    synthetic: bool,
    universe: str,
    skip_ingest: bool = False,
    skip_seed: bool = False,
) -> int:
    if once:
        from quantagent.scheduler.app import run_once

        path = asyncio.run(
            run_once(
                as_of=as_of,
                out_dir=out_dir,
                shadow_dir=shadow_dir,
                synthetic=synthetic,
                universe_code=universe,
                skip_ingest=skip_ingest,
                skip_seed=skip_seed,
            )
        )
        print(f"schedule --once wrote {path}")
        return 0

    from quantagent.scheduler.app import run_scheduler_blocking

    run_scheduler_blocking(
        out_dir=out_dir,
        shadow_dir=shadow_dir,
        synthetic=synthetic,
        universe_code=universe,
        skip_ingest=skip_ingest,
        skip_seed=skip_seed,
    )
    return 0


def _run_ingest_daily(
    *,
    universe: str,
    as_of: date | None,
    source: str,
    lookback_sessions: int,
) -> int:
    from quantagent.data.ops import refresh_daily_market_data

    result = asyncio.run(
        refresh_daily_market_data(
            as_of=as_of,
            universe_code=universe,
            price_source=source,
            lookback_sessions=lookback_sessions,
        )
    )
    print(
        f"ingest-daily done as_of={result.as_of} symbols={result.n_symbols} "
        f"price_rows={result.price_rows} index_rows={result.index_rows} "
        f"seeded={result.n_seeded} missing={len(result.missing)}"
    )
    return 0


def _run_seed_universe(*, code: str, as_of: date, require_all: bool) -> int:
    from quantagent.core.universe import seed_universe_snapshot

    result = seed_universe_snapshot(code=code, as_of=as_of, require_all=require_all)
    print(
        f"seeded universe={result['code']} as_of={result['as_of']} "
        f"n={result['n_seeded']} missing={len(result['missing'])}"  # type: ignore[arg-type]
    )
    missing = result["missing"]
    if isinstance(missing, list) and missing:
        preview = ", ".join(str(s) for s in missing[:10])
        more = "" if len(missing) <= 10 else f" …(+{len(missing) - 10})"
        print(f"  missing (ingest first): {preview}{more}")
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
        choices=(
            "price_daily",
            "financial_statement",
            "index",
            "security_industry",
            "trading_calendar",
        ),
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
    ingest.add_argument(
        "--dual-check",
        action="store_true",
        help="For trading_calendar: compare akshare vs baostock open days",
    )
    ingest.add_argument(
        "--universe",
        default=None,
        help="Load bootstrap symbols from config/universe (e.g. mvp_cn_50)",
    )

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

    feat = sub.add_parser("features", help="List / describe MVP factors (W5)")
    feat.add_argument("--market", default="CN")
    feat.add_argument(
        "--list",
        action="store_true",
        default=True,
        help="Print registered MVP factor codes (default)",
    )

    ev = sub.add_parser(
        "evaluate",
        help="Factor IC / quantile evaluation + markdown reports (W6)",
    )
    ev.add_argument("--market", default="CN")
    ev.add_argument(
        "--panel",
        type=Path,
        default=None,
        help="Parquet panel with trade_date, close, and factor columns",
    )
    ev.add_argument(
        "--factors",
        default=None,
        help="Comma-separated factor columns (default: all non-price cols, or demo)",
    )
    ev.add_argument(
        "--synthetic",
        action="store_true",
        help="Evaluate built-in synthetic panel (no DB; writes demo reports)",
    )
    ev.add_argument("--horizon", type=int, default=5, help="Forward-return horizon (days)")
    ev.add_argument("--quantiles", type=int, default=5)
    ev.add_argument(
        "--out",
        type=Path,
        default=Path("docs/factor-reports"),
        help="Directory for markdown reports",
    )

    pf = sub.add_parser(
        "portfolio",
        help="Equal-weight Top-N + risk check demo (W7; synthetic, no DB)",
    )
    pf.add_argument("--market", default="CN")
    pf.add_argument("--top-n", type=int, default=15)
    pf.add_argument("--min-score", type=float, default=0.55)

    report = sub.add_parser(
        "report",
        help="Generate daily markdown report + shadow step (synthetic or live PIT)",
    )
    report.add_argument("--market", default="CN")
    report.add_argument("--as-of", type=_parse_date, default=None)
    report.add_argument(
        "--out",
        type=Path,
        default=Path("docs/daily-reports"),
        help="Directory for daily markdown",
    )
    report.add_argument(
        "--shadow-dir",
        type=Path,
        default=Path("data/shadow"),
        help="Append-only shadow journal directory",
    )
    report.add_argument(
        "--universe",
        default="mvp_cn_50",
        help="Universe code for live mode (default: mvp_cn_50)",
    )
    report_mode = report.add_mutually_exclusive_group()
    report_mode.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic demo bundle (default if neither flag set)",
    )
    report_mode.add_argument(
        "--live",
        action="store_true",
        help="Build report from PITRepository (requires ingest + seed-universe)",
    )

    sched = sub.add_parser(
        "schedule",
        help="APScheduler daily live pipeline (ingest→seed→report; A4)",
    )
    sched.add_argument(
        "--once",
        action="store_true",
        help="Run one pipeline iteration and exit",
    )
    sched.add_argument("--as-of", type=_parse_date, default=None)
    sched.add_argument("--out", type=Path, default=Path("docs/daily-reports"))
    sched.add_argument("--shadow-dir", type=Path, default=Path("data/shadow"))
    sched.add_argument("--universe", default="mvp_cn_50")
    sched.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Live mode: skip price/index refresh (report+seed only)",
    )
    sched.add_argument(
        "--skip-seed",
        action="store_true",
        help="Live mode: skip universe_snapshot seed",
    )
    sched_mode = sched.add_mutually_exclusive_group()
    sched_mode.add_argument(
        "--synthetic",
        action="store_true",
        help="Synthetic report-only job (no ingest)",
    )
    sched_mode.add_argument(
        "--live",
        action="store_true",
        help="Live chain (default): ingest→seed→report",
    )

    ingest_daily = sub.add_parser(
        "ingest-daily",
        help="Incremental universe+index ingest and seed (A4 refresh step)",
    )
    ingest_daily.add_argument("--universe", default="mvp_cn_50")
    ingest_daily.add_argument("--as-of", type=_parse_date, default=None)
    ingest_daily.add_argument(
        "--source",
        choices=("akshare", "baostock"),
        default="baostock",
        help="Equity price source (index always uses akshare)",
    )
    ingest_daily.add_argument(
        "--lookback-sessions",
        type=int,
        default=3,
        help="How many sessions to re-pull (default 3)",
    )

    seed_u = sub.add_parser(
        "seed-universe",
        help="Seed universe + snapshot from config/universe (symbols must exist in security)",
    )
    seed_u.add_argument("--universe", default="mvp_cn_50")
    seed_u.add_argument(
        "--as-of",
        type=_parse_date,
        required=True,
        help="Snapshot date (use a trade date present in price_daily)",
    )
    seed_u.add_argument(
        "--require-all",
        action="store_true",
        help="Fail if any bootstrap symbol is missing from security",
    )

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

    if args.command == "features":
        from quantagent.quant.features import MVP_FACTORS

        print(f"market={args.market} mvp_factors={len(MVP_FACTORS)}")
        for code, factor in MVP_FACTORS.items():
            print(
                f"  {code:24s}  category={factor.category:12s}  "
                f"lookback={factor.lookback_days:3d}  v={factor.version}  - {factor.name}"
            )
        return 0

    if args.command == "evaluate":
        return _run_evaluate(
            market=args.market,
            panel_path=args.panel,
            factors_arg=args.factors,
            synthetic=args.synthetic,
            horizon=args.horizon,
            n_quantiles=args.quantiles,
            out_dir=args.out,
        )

    if args.command == "portfolio":
        return _run_portfolio_demo(
            market=args.market,
            top_n=args.top_n,
            min_score=args.min_score,
        )

    if args.command == "seed-universe":
        return _run_seed_universe(
            code=args.universe,
            as_of=args.as_of,
            require_all=args.require_all,
        )

    if args.command == "report":
        synthetic = not bool(args.live)
        return _run_report(
            market=args.market,
            as_of=args.as_of,
            out_dir=args.out,
            shadow_dir=args.shadow_dir,
            synthetic=synthetic,
            universe=args.universe,
        )

    if args.command == "schedule":
        # Default to live (A4). Pass --synthetic for demo-only report.
        return _run_schedule(
            once=args.once,
            as_of=args.as_of,
            out_dir=args.out,
            shadow_dir=args.shadow_dir,
            synthetic=bool(args.synthetic),
            universe=args.universe,
            skip_ingest=bool(args.skip_ingest),
            skip_seed=bool(args.skip_seed),
        )

    if args.command == "ingest-daily":
        return _run_ingest_daily(
            universe=args.universe,
            as_of=args.as_of,
            source=args.source,
            lookback_sessions=args.lookback_sessions,
        )

    if args.command == "ingest":
        if args.from_archive is not None:
            dataset = args.dataset
            if dataset == "index":
                dataset = "price_daily"
            _replay_normalize(args.from_archive, load=args.load, dataset=dataset)
            return 0

        symbols: list[str] = []
        if args.universe:
            from quantagent.core.universe import load_universe_config

            cfg = load_universe_config(args.universe)
            symbols = list(cfg.bootstrap_symbols)
            print(f"ingest universe={cfg.code} symbols={len(symbols)}")
        elif args.symbols:
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

        if args.dataset == "trading_calendar":
            end = args.end or date.today()
            start = args.start
            if args.daily:
                start = end = date.today()
            asyncio.run(
                _ingest_calendar(
                    start=start,
                    end=end,
                    source=args.source,
                    archive_root=args.archive_root,
                    load=args.load,
                    dual_check=bool(args.dual_check),
                )
            )
            return 0

        if args.dataset == "security_industry":
            if args.source != "akshare":
                print(
                    "security_industry ingest currently supports --source akshare only",
                    file=sys.stderr,
                )
                return 2
            end = args.end or date.today()
            # symbols/universe optional: omit → full market L1 memberships
            if not symbols and not args.universe and not args.symbols:
                print("ingest industry: no symbol filter (full L1 memberships)")
            asyncio.run(
                _ingest_industry(
                    symbols=symbols or None,
                    end=end,
                    archive_root=args.archive_root,
                    load=args.load,
                )
            )
            return 0

        if not symbols:
            print(
                "ingest requires --symbols, --universe, or --from-archive",
                file=sys.stderr,
            )
            return 2

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

"""Backfill monthly universe_snapshot rows (month-end sessions + survivorship probes).

For CSI300 / ZZ500-dated membership, pass ``--from-index hs300`` (or ``zz500``)
so each month-end calls baostock instead of replaying bootstrap_symbols.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from quantagent.core.calendar import TradingCalendar
from quantagent.core.repository.pit import PITRepository
from quantagent.core.universe import (
    ensure_survivorship_probes,
    load_universe_config,
    resolve_backfill_symbols,
    seed_universe_snapshot,
)
from quantagent.data.collectors.baostock import BaostockIndexConstituentCollector
from quantagent.shared.config import get_settings


def _bootstrap_present(
    code: str, *, symbols_file: Path | None = None
) -> tuple[int, int, list[str]]:
    """Return (have, total, missing_sample) for candidate symbols in ``security``."""
    wanted = resolve_backfill_symbols(code, symbols_file=symbols_file)
    if not wanted:
        return 0, 0, []
    eng = create_engine(get_settings().database_url, pool_pre_ping=True)
    with eng.connect() as conn:
        stmt = text("SELECT symbol FROM security WHERE symbol = ANY(:syms)").bindparams(
            bindparam("syms", type_=ARRAY(TEXT()))
        )
        have = {str(r[0]) for r in conn.execute(stmt, {"syms": wanted})}
    missing = [s for s in wanted if s not in have]
    return len(have), len(wanted), missing[:10]


async def _main_async() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="mvp_cn_50")
    p.add_argument("--market", default="CN")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even when snapshot_date already exists",
    )
    p.add_argument(
        "--skip-survivorship",
        action="store_true",
        help="Do not ensure/include survivorship probe symbols",
    )
    p.add_argument(
        "--min-bootstrap",
        type=int,
        default=1,
        help="Abort unless at least this many candidate symbols exist in security",
    )
    p.add_argument(
        "--from-index",
        choices=("hs300", "zz500"),
        default=None,
        help="Fetch dated baostock constituents per month-end (CSI300/ZZ500)",
    )
    p.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        help="Used only for the pre-flight 'present in security' check",
    )
    args = p.parse_args()

    cfg = load_universe_config(args.universe)
    have, total, missing = _bootstrap_present(
        args.universe, symbols_file=args.symbols_file
    )
    print(f"candidates in security: {have}/{total}", flush=True)
    if have < args.min_bootstrap:
        print(
            "FAIL: candidate symbols are not in the security table "
            f"(have={have}, need>={args.min_bootstrap}).\n"
            "  Fix: backfill prices first, then re-run monthly snapshots.\n"
            f"  missing sample: {missing}",
            flush=True,
        )
        return 2

    cal = TradingCalendar(args.market)
    if cal.is_empty():
        print(
            "FAIL: trading_calendar empty for market="
            f"{args.market!r}.\n"
            "  Fix: run  make ingest-calendar\n"
            "  then retry  make backfill-universe-monthly",
            flush=True,
        )
        return 2

    sessions = cal.month_end_sessions(args.start, args.end)
    print(
        f"backfill-universe-monthly universe={cfg.code} "
        f"from_index={args.from_index} months={len(sessions)} "
        f"window=[{args.start}, {args.end}]",
        flush=True,
    )

    if not args.skip_survivorship:
        ensured = ensure_survivorship_probes(code=args.universe)
        print(
            f"survivorship ensured n={ensured['n_ensured']} {ensured['symbols']}",
            flush=True,
        )

    index_members: dict[str, list[str]] = {}
    if args.from_index is not None:
        coll = BaostockIndexConstituentCollector()
        print(
            f"fetch {args.from_index} constituents for {len(sessions)} month-ends "
            "(single login)...",
            flush=True,
        )
        index_members = await coll.fetch_symbols_many(
            list(sessions), index=args.from_index
        )

    existing = set(PITRepository().list_universe_snapshot_dates(name=cfg.code))
    seeded = 0
    skipped = 0
    failures: list[str] = []
    for i, sess in enumerate(sessions, 1):
        if not args.force and sess in existing:
            skipped += 1
            print(
                f"[{i}/{len(sessions)}] SKIP {sess.isoformat()} already present",
                flush=True,
            )
            continue
        try:
            symbols: list[str] | None = None
            if args.from_index is not None:
                symbols = index_members.get(sess.isoformat(), [])
                if not symbols:
                    raise RuntimeError(f"no {args.from_index} members for {sess}")
            result = seed_universe_snapshot(
                code=args.universe,
                as_of=sess,
                symbols=symbols,
                require_all=False,
                include_survivorship=not args.skip_survivorship,
            )
            seeded += 1
            print(
                f"[{i}/{len(sessions)}] OK {sess.isoformat()} "
                f"n={result['n_seeded']} missing={len(result['missing'])}",  # type: ignore[arg-type]
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{sess.isoformat()}:{exc}")
            print(f"[{i}/{len(sessions)}] FAIL {sess.isoformat()}: {exc}", flush=True)

    print(
        f"DONE seeded={seeded} skipped={skipped} failures={len(failures)}",
        flush=True,
    )
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())

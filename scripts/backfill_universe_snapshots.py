"""Backfill monthly universe_snapshot rows (month-end sessions + survivorship probes)."""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from quantagent.core.calendar import TradingCalendar
from quantagent.core.repository.pit import PITRepository
from quantagent.core.universe import (
    ensure_survivorship_probes,
    load_universe_config,
    seed_universe_snapshot,
)
from quantagent.shared.config import get_settings


def _bootstrap_present(code: str) -> tuple[int, int, list[str]]:
    """Return (have, total, missing_sample) for bootstrap symbols in ``security``."""
    cfg = load_universe_config(code)
    wanted = list(cfg.bootstrap_symbols)
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


def main() -> int:
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
        help="Abort unless at least this many bootstrap symbols exist in security",
    )
    args = p.parse_args()

    cfg = load_universe_config(args.universe)
    have, total, missing = _bootstrap_present(args.universe)
    print(f"bootstrap in security: {have}/{total}", flush=True)
    if have < args.min_bootstrap:
        print(
            "FAIL: MVP bootstrap symbols are not in the security table "
            f"(have={have}, need>={args.min_bootstrap}).\n"
            "  Earlier month SKIP rows may only contain survivorship probes.\n"
            "  Fix (pick one):\n"
            "    make ingest-universe\n"
            "    make backfill-10y\n"
            "  then re-run:\n"
            "    make backfill-universe-monthly\n"
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
        f"months={len(sessions)} window=[{args.start}, {args.end}]",
        flush=True,
    )

    if not args.skip_survivorship:
        ensured = ensure_survivorship_probes(code=args.universe)
        print(
            f"survivorship ensured n={ensured['n_ensured']} {ensured['symbols']}",
            flush=True,
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
            result = seed_universe_snapshot(
                code=args.universe,
                as_of=sess,
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


if __name__ == "__main__":
    raise SystemExit(main())

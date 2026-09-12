"""Audit mvp_cn_50 price coverage vs trading calendar (Gate 1 10y completeness)."""

from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from quantagent.core.universe import load_universe_config
from quantagent.shared.config import get_settings


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="mvp_cn_50")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--threshold", type=float, default=0.01, help="Max missing rate")
    args = p.parse_args()

    cfg = load_universe_config(args.universe)
    symbols = list(cfg.bootstrap_symbols)
    eng = create_engine(get_settings().database_url, pool_pre_ping=True)

    with eng.connect() as conn:
        open_days = int(
            conn.execute(
                text(
                    """
                    SELECT count(*) FROM trading_calendar
                    WHERE market = 'CN' AND is_open
                      AND trade_date >= :start AND trade_date <= :end
                    """
                ),
                {"start": args.start, "end": args.end},
            ).scalar_one()
        )
        stmt = text(
            """
            SELECT s.symbol,
                   count(p.trade_date) AS n_bars,
                   min(p.trade_date) AS dmin,
                   max(p.trade_date) AS dmax
            FROM security s
            LEFT JOIN price_daily p
              ON p.security_id = s.security_id
             AND p.trade_date >= :start
             AND p.trade_date <= :end
            WHERE s.symbol = ANY(:symbols)
            GROUP BY s.symbol
            ORDER BY s.symbol
            """
        ).bindparams(bindparam("symbols", type_=ARRAY(TEXT())))
        rows = conn.execute(
            stmt,
            {"start": args.start, "end": args.end, "symbols": symbols},
        ).mappings().all()

    by_sym = {r["symbol"]: r for r in rows}
    missing_syms = [s for s in symbols if s not in by_sym or int(by_sym[s]["n_bars"] or 0) == 0]

    # Pre-IPO days are not "missing" — measure coverage from each symbol's first bar.
    post_ipo_expected = 0
    post_ipo_actual = 0
    per_miss: list[tuple[str, int, float, object, object]] = []
    with eng.connect() as conn:
        for s in symbols:
            r = by_sym.get(s, {})
            n = int(r.get("n_bars") or 0)
            dmin = r.get("dmin")
            dmax = r.get("dmax")
            if dmin is None:
                per_miss.append((s, open_days, 1.0, None, None))
                continue
            expected_s = int(
                conn.execute(
                    text(
                        """
                        SELECT count(*) FROM trading_calendar
                        WHERE market = 'CN' AND is_open
                          AND trade_date >= :dmin AND trade_date <= :end
                        """
                    ),
                    {"dmin": dmin, "end": args.end},
                ).scalar_one()
            )
            miss = max(expected_s - n, 0)
            rate = miss / expected_s if expected_s else 1.0
            post_ipo_expected += expected_s
            post_ipo_actual += n
            per_miss.append((s, miss, rate, dmin, dmax))
    per_miss.sort(key=lambda x: -x[2])

    naive_expected = open_days * len(symbols)
    naive_actual = sum(int(by_sym.get(s, {}).get("n_bars") or 0) for s in symbols)
    naive_miss = 1.0 - (naive_actual / naive_expected) if naive_expected else 1.0
    pool_miss_rate = (
        1.0 - (post_ipo_actual / post_ipo_expected) if post_ipo_expected else 1.0
    )
    print(f"universe={args.universe} window=[{args.start}, {args.end}]")
    print(f"open_days={open_days} symbols={len(symbols)}")
    print(f"naive_missing_rate={naive_miss:.4%} (includes pre-IPO; not Gate metric)")
    print(
        f"post_ipo_bars={post_ipo_actual}/{post_ipo_expected} "
        f"post_ipo_missing_rate={pool_miss_rate:.4%}"
    )
    print(f"symbols_with_zero_bars={len(missing_syms)} {missing_syms[:10]}")
    print("worst_10_by_post_ipo_miss_rate:")
    for s, miss, rate, dmin, dmax in per_miss[:10]:
        print(f"  {s} miss={miss} rate={rate:.2%} [{dmin}..{dmax}]")

    ok = pool_miss_rate <= args.threshold and not missing_syms
    print(f"GATE={'PASS' if ok else 'FAIL'} threshold={args.threshold:.2%} (post-IPO)")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

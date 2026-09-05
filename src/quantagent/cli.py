"""CLI entrypoints used by Makefile targets."""

from __future__ import annotations

import argparse
import sys

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantagent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-reference-data", help="Seed taxonomy / reference rows")

    # Placeholders so Makefile targets fail with a clear message until implemented.
    for name, help_text in (
        ("ingest", "Ingest market data (not yet implemented)"),
        ("features", "Compute features (not yet implemented)"),
        ("backtest", "Run backtest (not yet implemented)"),
        ("report", "Generate daily report (not yet implemented)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--universe", default=None)
        p.add_argument("--start", default=None)
        p.add_argument("--daily", action="store_true")
        p.add_argument("--market", default=None)
        p.add_argument("--strategy", default=None)

    args = parser.parse_args(argv)

    if args.command == "init-reference-data":
        init_reference_data()
        return 0

    print(f"command '{args.command}' is not implemented yet (P0 later / P1)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

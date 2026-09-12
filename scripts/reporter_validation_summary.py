"""Summarize ReporterAgent validation fail-rate from docs/reporter-validation-log.md."""

from __future__ import annotations

import argparse
from pathlib import Path

from quantagent.agents.reporter.validation_log import summarize_validation_log


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--path",
        type=Path,
        default=Path("docs/reporter-validation-log.md"),
    )
    p.add_argument(
        "--max-fail-rate",
        type=float,
        default=0.05,
        help="Exit 1 if fail_rate exceeds this threshold (default 5%)",
    )
    p.add_argument(
        "--min-n",
        type=int,
        default=1,
        help="Require at least this many logged runs before gating",
    )
    args = p.parse_args()
    stats = summarize_validation_log(args.path)
    n = int(stats["n"])
    fail_rate = float(stats["fail_rate"])
    print(
        f"reporter_validation n={n} ok={stats['n_ok']} fail={stats['n_fail']} "
        f"fail_rate={fail_rate:.2%}"
    )
    if n < args.min_n:
        print(f"GATE SKIP: need >= {args.min_n} runs (have {n})")
        return 0
    if fail_rate > args.max_fail_rate:
        print(f"GATE FAIL: fail_rate {fail_rate:.2%} > {args.max_fail_rate:.2%}")
        return 1
    print(f"GATE PASS: fail_rate {fail_rate:.2%} <= {args.max_fail_rate:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

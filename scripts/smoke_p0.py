"""One-shot smoke for P0 (W2 collector → W3 loader → W4 financials / Buy&Hold).

Steps:
  A  unit tests
  B  alembic + reference seed + integration (Postgres / PIT / loaders / sentinel)
  C  baostock price ingest (+ optional --load)
  D  akshare price ingest (may be flaky upstream; default WARN)
  E  --from-archive normalize replay (+ optional --load)
  F  financial_statement ingest + load (akshare EM sheets)
  G  CSI300 index ingest + load
  H  Buy&Hold backtest on 000300.SH

Usage:
  uv run python scripts/smoke_p0.py
  uv run python scripts/smoke_p0.py --skip-network
  uv run python scripts/smoke_p0.py --strict-akshare
  uv run python scripts/smoke_p0_w2.py   # thin alias → smoke_p0.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOL = "600519.SH"
DEFAULT_INDEX = "000300.SH"
PATH_RE = re.compile(r"path=(\S+)")
LOADED_RE = re.compile(r"loaded(?:\s+financials)?\s+batch_id=\d+\s+rows=(\d+)\s+status=success")


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    soft: bool = False


@dataclass
class SmokeReport:
    results: list[StepResult] = field(default_factory=list)

    def add(self, result: StepResult) -> None:
        self.results.append(result)
        mark = "PASS" if result.ok else ("WARN" if result.soft else "FAIL")
        print(f"\n[{mark}] {result.name}")
        if result.detail:
            print(result.detail.rstrip())

    @property
    def hard_failed(self) -> bool:
        return any(not r.ok and not r.soft for r in self.results)

    @property
    def soft_failed(self) -> bool:
        return any(not r.ok and r.soft for r in self.results)


def _run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _combine_output(proc: subprocess.CompletedProcess[str]) -> str:
    parts = [p for p in (proc.stdout, proc.stderr) if p]
    return "\n".join(parts).strip()


def _extract_path(output: str) -> Path | None:
    match = PATH_RE.search(output)
    if not match:
        return None
    return Path(match.group(1))


def _load_ok(output: str) -> bool:
    return LOADED_RE.search(output) is not None


def step_a_unit(report: SmokeReport) -> None:
    proc = _run(["uv", "run", "pytest", "tests/unit", "-q", "--tb=line"])
    out = _combine_output(proc)
    report.add(
        StepResult(
            name="A unit tests",
            ok=proc.returncode == 0,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )


def step_b_integration(report: SmokeReport) -> None:
    migrate = _run(["uv", "run", "alembic", "upgrade", "head"])
    if migrate.returncode != 0:
        report.add(
            StepResult(
                name="B alembic upgrade",
                ok=False,
                detail=_combine_output(migrate)[-2000:],
            )
        )
        return

    seed = _run(["uv", "run", "python", "-m", "quantagent.cli", "init-reference-data"])
    if seed.returncode != 0:
        report.add(
            StepResult(
                name="B init-reference-data",
                ok=False,
                detail=_combine_output(seed)[-2000:],
            )
        )
        return

    integ = _run(["uv", "run", "pytest", "tests/integration", "-q", "--tb=line"])
    report.add(
        StepResult(
            name="B integration (PIT / loader / backtest sentinel)",
            ok=integ.returncode == 0,
            detail=_combine_output(integ)[-2000:],
        )
    )


def _ingest_price(
    *,
    source: str,
    symbol: str,
    start: date,
    end: date,
    archive_root: Path,
    load: bool,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "quantagent.cli",
        "ingest",
        "--dataset",
        "price_daily",
        "--symbols",
        symbol,
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--source",
        source,
        "--archive-root",
        str(archive_root),
    ]
    if load:
        cmd.append("--load")
    return _run(cmd)


def step_c_baostock(
    report: SmokeReport,
    *,
    symbol: str,
    start: date,
    end: date,
    archive_root: Path,
    load: bool,
) -> Path | None:
    proc = _ingest_price(
        source="baostock",
        symbol=symbol,
        start=start,
        end=end,
        archive_root=archive_root,
        load=load,
    )
    out = _combine_output(proc)
    path = _extract_path(out)
    ok = proc.returncode == 0 and path is not None and path.exists()
    if load and ok:
        ok = _load_ok(out)
    report.add(
        StepResult(
            name="C baostock price ingest" + (" + load" if load else ""),
            ok=ok,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )
    return path if ok else None


def step_d_akshare(
    report: SmokeReport,
    *,
    symbol: str,
    start: date,
    end: date,
    archive_root: Path,
    load: bool,
    strict: bool,
) -> Path | None:
    proc = _ingest_price(
        source="akshare",
        symbol=symbol,
        start=start,
        end=end,
        archive_root=archive_root,
        load=load,
    )
    out = _combine_output(proc)
    path = _extract_path(out)
    ok = proc.returncode == 0 and path is not None and path.exists()
    if load and ok:
        ok = _load_ok(out)
    report.add(
        StepResult(
            name="D akshare price ingest" + (" + load" if load else ""),
            ok=ok,
            soft=not strict,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )
    return path if ok else None


def step_e_replay(
    report: SmokeReport,
    raw_path: Path | None,
    *,
    load: bool,
) -> None:
    if raw_path is None:
        report.add(
            StepResult(
                name="E --from-archive replay",
                ok=False,
                detail="skipped: no archived parquet from C/D",
            )
        )
        return

    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "quantagent.cli",
        "ingest",
        "--from-archive",
        str(raw_path),
    ]
    if load:
        cmd.append("--load")
    proc = _run(cmd)
    out = _combine_output(proc)
    ok = proc.returncode == 0 and "rows=" in out
    if load and ok:
        ok = _load_ok(out)
    report.add(
        StepResult(
            name="E --from-archive replay" + (" + load" if load else ""),
            ok=ok,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )


def step_f_financial(
    report: SmokeReport,
    *,
    symbol: str,
    archive_root: Path,
    load: bool,
    soft: bool,
) -> None:
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "quantagent.cli",
        "ingest",
        "--dataset",
        "financial_statement",
        "--symbols",
        symbol,
        "--archive-root",
        str(archive_root),
    ]
    if load:
        cmd.append("--load")
    proc = _run(cmd)
    out = _combine_output(proc)
    path = _extract_path(out)
    ok = proc.returncode == 0 and path is not None and path.exists() and "rows_norm=" in out
    if load and ok:
        ok = _load_ok(out)
    report.add(
        StepResult(
            name="F financial ingest" + (" + load" if load else ""),
            ok=ok,
            soft=soft,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )


def step_g_index(
    report: SmokeReport,
    *,
    symbol: str,
    start: date,
    end: date,
    archive_root: Path,
    load: bool,
    soft: bool,
) -> None:
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "quantagent.cli",
        "ingest",
        "--dataset",
        "index",
        "--symbols",
        symbol,
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--archive-root",
        str(archive_root),
    ]
    if load:
        cmd.append("--load")
    proc = _run(cmd)
    out = _combine_output(proc)
    path = _extract_path(out)
    ok = proc.returncode == 0 and path is not None and path.exists()
    if load and ok:
        ok = _load_ok(out)
    # Guard against bare-digit → .SZ mis-tag (W4 fix).
    if ok and symbol.endswith(".SH"):
        wrong = f"{symbol.split('.')[0]}.SZ"
        if wrong in out and symbol not in out:
            ok = False
            out = f"{out}\nERROR: index normalized to {wrong} instead of {symbol}"
    report.add(
        StepResult(
            name="G index ingest" + (" + load" if load else ""),
            ok=ok,
            soft=soft,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )


def step_h_backtest(
    report: SmokeReport,
    *,
    symbol: str,
    start: date,
    end: date,
) -> None:
    proc = _run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "quantagent.cli",
            "backtest",
            "--strategy",
            "buy_and_hold",
            "--symbol",
            symbol,
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
        ]
    )
    out = _combine_output(proc)
    ok = (
        proc.returncode == 0
        and "total_return=" in out
        and "cagr=" in out
        and "max_drawdown=" in out
    )
    report.add(
        StepResult(
            name="H Buy&Hold backtest",
            ok=ok,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description="P0 smoke checklist (A→H, through W4)")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--index-symbol", default=DEFAULT_INDEX)
    parser.add_argument("--start", type=date.fromisoformat, default=today - timedelta(days=16))
    parser.add_argument("--end", type=date.fromisoformat, default=today)
    parser.add_argument(
        "--index-start",
        type=date.fromisoformat,
        default=date(2015, 1, 1),
        help="CSI300 history start for G/H (default: 2015-01-01)",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=ROOT / "data" / "raw" / "smoke",
    )
    parser.add_argument(
        "--skip-network",
        action="store_true",
        help="Only A + B (no vendor HTTP / backtest)",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip B and all --load / backtest steps",
    )
    parser.add_argument(
        "--no-load",
        action="store_true",
        help="Collect/normalize only (skip Postgres load even if DB is up)",
    )
    parser.add_argument(
        "--strict-akshare",
        action="store_true",
        help="Treat akshare price failure as hard FAIL (default: WARN)",
    )
    parser.add_argument(
        "--soft-financial",
        action="store_true",
        help="Treat financial ingest failure as WARN (default: hard FAIL)",
    )
    parser.add_argument(
        "--soft-index",
        action="store_true",
        help="Treat index ingest failure as WARN (default: hard FAIL)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = SmokeReport()
    load = not args.skip_db and not args.no_load

    print("=== QuantAgent smoke P0 (W2+W3+W4) ===")
    print(f"symbol={args.symbol} price_window={args.start}..{args.end}")
    print(f"index={args.index_symbol} index_start={args.index_start}")
    print(f"archive_root={args.archive_root} load={load}")

    step_a_unit(report)

    if not args.skip_db:
        step_b_integration(report)
    else:
        report.add(StepResult(name="B integration", ok=True, detail="skipped (--skip-db)"))

    if args.skip_network:
        for name in (
            "C baostock price ingest",
            "D akshare price ingest",
            "E --from-archive replay",
            "F financial ingest",
            "G index ingest",
            "H Buy&Hold backtest",
        ):
            report.add(StepResult(name=name, ok=True, detail="skipped (--skip-network)"))
    else:
        args.archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = step_c_baostock(
            report,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            archive_root=args.archive_root,
            load=load,
        )
        ak_path = step_d_akshare(
            report,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            archive_root=args.archive_root,
            load=load,
            strict=args.strict_akshare,
        )
        step_e_replay(report, archive_path or ak_path, load=load)
        step_f_financial(
            report,
            symbol=args.symbol,
            archive_root=args.archive_root,
            load=load,
            soft=args.soft_financial,
        )
        step_g_index(
            report,
            symbol=args.index_symbol,
            start=args.index_start,
            end=args.end,
            archive_root=args.archive_root,
            load=load,
            soft=args.soft_index,
        )
        if load:
            step_h_backtest(
                report,
                symbol=args.index_symbol,
                start=args.index_start,
                end=args.end,
            )
        else:
            report.add(
                StepResult(
                    name="H Buy&Hold backtest",
                    ok=True,
                    detail="skipped (no DB load)",
                )
            )

    print("\n=== Summary ===")
    for r in report.results:
        mark = "PASS" if r.ok else ("WARN" if r.soft else "FAIL")
        print(f"  {mark}  {r.name}")

    if report.hard_failed:
        print("\nSmoke FAILED")
        return 1
    if report.soft_failed:
        print("\nSmoke PASSED with warnings")
        return 0
    print("\nSmoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

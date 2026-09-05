"""One-shot smoke for P0 (PIT) + W2 (collector / normalizer / archive).

Steps (see prior test checklist):
  A  unit tests
  B  alembic + reference seed + integration (Postgres)
  C  baostock ingest (near window)
  D  akshare ingest (may be flaky upstream)
  E  --from-archive normalize replay

Usage:
  uv run python scripts/smoke_p0_w2.py
  uv run python scripts/smoke_p0_w2.py --skip-network
  uv run python scripts/smoke_p0_w2.py --strict-akshare
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
PATH_RE = re.compile(r"path=(\S+)")


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
            name="B integration (PIT sentinel)",
            ok=integ.returncode == 0,
            detail=_combine_output(integ)[-2000:],
        )
    )


def _ingest(
    *,
    source: str,
    symbol: str,
    start: date,
    end: date,
    archive_root: Path,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "quantagent.cli",
            "ingest",
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
    )


def _extract_path(output: str) -> Path | None:
    match = PATH_RE.search(output)
    if not match:
        return None
    return Path(match.group(1))


def step_c_baostock(
    report: SmokeReport,
    *,
    symbol: str,
    start: date,
    end: date,
    archive_root: Path,
) -> Path | None:
    proc = _ingest(
        source="baostock",
        symbol=symbol,
        start=start,
        end=end,
        archive_root=archive_root,
    )
    out = _combine_output(proc)
    path = _extract_path(out)
    ok = proc.returncode == 0 and path is not None and path.exists()
    report.add(
        StepResult(
            name="C baostock ingest",
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
    strict: bool,
) -> Path | None:
    proc = _ingest(
        source="akshare",
        symbol=symbol,
        start=start,
        end=end,
        archive_root=archive_root,
    )
    out = _combine_output(proc)
    path = _extract_path(out)
    ok = proc.returncode == 0 and path is not None and path.exists()
    report.add(
        StepResult(
            name="D akshare ingest",
            ok=ok,
            soft=not strict,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )
    return path if ok else None


def step_e_replay(report: SmokeReport, raw_path: Path | None) -> None:
    if raw_path is None:
        report.add(
            StepResult(
                name="E --from-archive replay",
                ok=False,
                detail="skipped: no archived parquet from C/D",
            )
        )
        return

    proc = _run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "quantagent.cli",
            "ingest",
            "--from-archive",
            str(raw_path),
        ]
    )
    out = _combine_output(proc)
    report.add(
        StepResult(
            name="E --from-archive replay",
            ok=proc.returncode == 0 and "rows=" in out,
            detail=out[-2000:] if out else f"exit={proc.returncode}",
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description="P0+W2 smoke checklist (A→E)")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--start", type=date.fromisoformat, default=today - timedelta(days=16))
    parser.add_argument("--end", type=date.fromisoformat, default=today)
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=ROOT / "data" / "raw" / "smoke",
    )
    parser.add_argument(
        "--skip-network",
        action="store_true",
        help="Only A + B (no vendor HTTP)",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip B (no Postgres / alembic)",
    )
    parser.add_argument(
        "--strict-akshare",
        action="store_true",
        help="Treat akshare failure as hard FAIL (default: WARN)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = SmokeReport()

    print("=== QuantAgent smoke P0+W2 ===")
    print(f"symbol={args.symbol} window={args.start}..{args.end}")
    print(f"archive_root={args.archive_root}")

    step_a_unit(report)

    if not args.skip_db:
        step_b_integration(report)
    else:
        report.add(StepResult(name="B integration", ok=True, detail="skipped (--skip-db)"))

    archive_path: Path | None = None
    if args.skip_network:
        report.add(StepResult(name="C baostock ingest", ok=True, detail="skipped (--skip-network)"))
        report.add(StepResult(name="D akshare ingest", ok=True, detail="skipped (--skip-network)"))
        report.add(StepResult(name="E --from-archive", ok=True, detail="skipped (--skip-network)"))
    else:
        args.archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = step_c_baostock(
            report,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            archive_root=args.archive_root,
        )
        ak_path = step_d_akshare(
            report,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            archive_root=args.archive_root,
            strict=args.strict_akshare,
        )
        step_e_replay(report, archive_path or ak_path)

    print("\n=== Summary ===")
    for r in report.results:
        mark = "PASS" if r.ok else ("WARN" if r.soft else "FAIL")
        print(f"  {mark}  {r.name}")

    if report.hard_failed:
        print("\nSmoke FAILED")
        return 1
    if report.soft_failed:
        print("\nSmoke PASSED with warnings (akshare soft-fail)")
        return 0
    print("\nSmoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Gate-1: decision/quant must not hard-code CN price-limit ratios."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "quantagent"

SCAN_DIRS = ("decision", "quant")
LIMIT_PATTERNS = (
    re.compile(r"limit_up\s*=\s*0\.10\b"),
    re.compile(r"limit_down\s*=\s*0\.10\b"),
    re.compile(r"limit_pct\s*=\s*0\.1(?:0)?\b"),
    re.compile(r"\*\s*0\.10\b.*limit"),
    re.compile(r"limit.*\*\s*0\.10\b"),
    re.compile(r"(?:fee|commission|stamp_duty).{0,30}['\"]CNY['\"]"),
)


def _scan_file(path: Path) -> list[str]:
    if path.name.endswith("config.py"):
        return []
    rel = path.relative_to(SRC).as_posix()
    if not any(rel.startswith(d) for d in SCAN_DIRS):
        return []
    hits: list[str] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pat in LIMIT_PATTERNS:
            if pat.search(line):
                hits.append(f"{rel}:{i}: {stripped}")
                break
    return hits


def test_no_hardcoded_market_constants() -> None:
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        violations.extend(_scan_file(path))
    assert not violations, "hard-coded market constants:\n" + "\n".join(violations)

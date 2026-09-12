#!/usr/bin/env python3
"""Static check: business modules must not embed raw SQL via sqlalchemy.text()."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "quantagent"

# Packages that may call sqlalchemy.text() for SQL.
ALLOWED_PREFIXES = (
    "core/repository",
    "data/loaders",
    "data/validators",
    "data/ops",
)

# Business layers that must route historical reads through PITRepository.
FORBIDDEN_PREFIXES = (
    "agents",
    "quant",
    "decision",
    "evaluation",
    "reporting",
    "backtest",
    "scheduler",
)

IMPORT_TEXT = re.compile(
    r"^\s*from\s+sqlalchemy(?:\.\w+)?\s+import\s+([^#\n]+)",
    re.MULTILINE,
)
IMPORT_TEXT_AS = re.compile(r"^\s*import\s+sqlalchemy(?:\.\w+)?\s+as\s+(\w+)", re.MULTILINE)
TEXT_CALL = re.compile(r"\btext\s*\(")

# Optional: hard-coded CN price-limit ratios outside market config.
LIMIT_LITERAL = re.compile(
    r"(?:limit_up|limit_down|limit_pct|up_ratio|down_ratio).{0,40}0\.10\b|"
    r"\b0\.10\b.{0,40}(?:limit_up|limit_down|limit_pct)",
    re.IGNORECASE,
)
MARKET_CONST_DIRS = FORBIDDEN_PREFIXES + ("execution",)


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _imports_sqlalchemy_text(content: str) -> bool:
    for match in IMPORT_TEXT.finditer(content):
        names = [n.strip() for n in match.group(1).split(",")]
        if any(n.split(" as ")[0].strip() == "text" for n in names):
            return True
    return bool(IMPORT_TEXT_AS.search(content))


def _text_call_lines(content: str) -> list[int]:
    if not _imports_sqlalchemy_text(content):
        return []
    lines: list[int] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if TEXT_CALL.search(line):
            lines.append(i)
    return lines


def _is_allowed(path: Path) -> bool:
    rel = _rel(path)
    return any(rel.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def _is_forbidden(path: Path) -> bool:
    rel = _rel(path)
    parts = rel.split("/")
    if not parts:
        return False
    top = parts[0]
    if top not in FORBIDDEN_PREFIXES:
        return False
    if top == "backtest" and "sentinel" in path.name:
        return False
    return True


def scan_sql_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if _is_allowed(path) or not _is_forbidden(path):
            continue
        content = path.read_text(encoding="utf-8")
        for line_no in _text_call_lines(content):
            rel = _rel(path)
            msg = f"src/quantagent/{rel}:{line_no}: sqlalchemy.text() in business layer"
            violations.append(msg)
    return violations


def scan_market_constant_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = _rel(path)
        if not any(rel.startswith(d) for d in MARKET_CONST_DIRS):
            continue
        if rel.endswith("config.py"):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if LIMIT_LITERAL.search(line):
                violations.append(
                    f"{path.relative_to(ROOT)}:{i}: hard-coded limit ratio 0.10"
                )
    return violations


def main() -> int:
    violations = scan_sql_violations() + scan_market_constant_violations()
    if violations:
        print("lint_pit: violations found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print("lint_pit: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

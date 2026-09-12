"""Summarize coverage.json for Gate 1 (overall + core modules)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CORE_KEYS = (
    "core/assertions",
    "core/repository",
    "data/loaders",
    "data/validators",
    "evaluation/shadow",
)


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    t = data["totals"]
    overall = float(t["percent_covered"])
    print(
        f"TOTAL {overall:.2f}%  {t['covered_lines']}/{t['num_statements']}"
    )
    core_c = core_n = 0
    for fpath, info in sorted(data["files"].items()):
        p = fpath.replace("\\", "/")
        if any(k in p for k in CORE_KEYS):
            s = info["summary"]
            core_c += s["covered_lines"]
            core_n += s["num_statements"]
    core_pct = 100.0 * core_c / core_n if core_n else 0.0
    print(f"CORE  {core_pct:.2f}%  {core_c}/{core_n}")
    ok = overall >= 70.0 and core_pct >= 85.0
    print("GATE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for scripts/lint_pit.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_lint_pit():
    spec = importlib.util.spec_from_file_location("lint_pit", ROOT / "scripts" / "lint_pit.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_lint_pit_repo_clean() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "lint_pit.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_lint_pit_flags_forbidden_sql(tmp_path: Path) -> None:
    lp = _load_lint_pit()
    fake_src = tmp_path / "src" / "quantagent"
    bad = fake_src / "quant" / "bad_factor.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "from sqlalchemy import text\n\ndef load():\n    return text('SELECT 1')\n",
        encoding="utf-8",
    )
    original = lp.SRC
    lp.SRC = fake_src
    try:
        hits = lp.scan_sql_violations()
    finally:
        lp.SRC = original
    assert any("bad_factor.py" in h for h in hits)

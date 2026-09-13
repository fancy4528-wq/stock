"""Score figure extraction against a gold JSONL baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantagent.agents.news_extractor.figures import extract_figures


@dataclass(frozen=True)
class FigureScore:
    n: int
    exact: int
    label_unit: int
    value_tol: int

    @property
    def exact_rate(self) -> float:
        return self.exact / self.n if self.n else 0.0

    @property
    def soft_rate(self) -> float:
        """Label+unit match and value within 1% relative tolerance."""
        return self.value_tol / self.n if self.n else 0.0


def _load_gold(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _match_value(expected: float, actual: float, *, tol: float = 0.01) -> bool:
    if expected == 0:
        return abs(actual) <= tol
    return abs(actual - expected) / abs(expected) <= tol


def score_figures_gold(path: Path | str) -> FigureScore:
    """Compare extractor output to gold figures (one expected figure per row)."""
    gold = _load_gold(Path(path))
    exact = 0
    label_unit = 0
    value_tol = 0
    for row in gold:
        text = str(row["text"])
        expected = row["figure"]
        preds = extract_figures(text)
        exp_label = str(expected["label"])
        exp_value = float(expected["value"])
        exp_unit = str(expected["unit"])
        hit_exact = False
        hit_lu = False
        hit_val = False
        for pred in preds:
            if pred.label == exp_label and pred.unit == exp_unit:
                hit_lu = True
                if _match_value(exp_value, pred.value):
                    hit_val = True
                if pred.value == exp_value:
                    hit_exact = True
        if hit_exact:
            exact += 1
        if hit_lu:
            label_unit += 1
        if hit_val:
            value_tol += 1
    return FigureScore(n=len(gold), exact=exact, label_unit=label_unit, value_tol=value_tol)

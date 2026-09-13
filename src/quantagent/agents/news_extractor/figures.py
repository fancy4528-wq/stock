"""Rule-based Chinese financial figure extraction (LLM later)."""

from __future__ import annotations

import re

from quantagent.agents.news_extractor.schema import Figure

# Examples: 营收12.3亿元 / 同比增长15% / 中标金额3.5亿元 / 净利润 -1.2亿元
_FIGURE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(?P<label>营收|营业收入|收入|净利润|净利|归母净利润|"
            r"中标金额|合同金额|订单金额|投资额|募资|产能|"
            r"同比|环比|增长|下降)"
            r"[^\d\-－]{0,6}"
            r"(?P<sign>[\-－])?"
            r"(?P<num>\d+(?:\.\d+)?)"
            r"(?P<unit>亿元|万元|万吨|吨|元|%|个百分点|倍)?"
        ),
        "labeled",
    ),
    (
        re.compile(
            r"(?P<label>同比|环比)"
            r"[^\d\-－]{0,4}"
            r"(?:增长|下降|升|跌|增|减)?"
            r"[^\d\-－]{0,2}"
            r"(?P<sign>[\-－])?"
            r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>%|个百分点)"
        ),
        "yoy",
    ),
]


def _to_float(sign: str | None, num: str) -> float:
    value = float(num)
    if sign in {"-", "－"}:
        return -value
    return value


def _normalize_label(label: str) -> str:
    mapping = {
        "净利": "净利润",
        "营业收入": "营收",
        "收入": "营收",
        "增长": "同比",
        "下降": "同比",
    }
    return mapping.get(label, label)


def extract_figures(text: str, *, max_figures: int = 12) -> list[Figure]:
    """Extract numeric claims from Chinese financial text."""
    if not text or not text.strip():
        return []

    seen: set[tuple[str, float, str]] = set()
    out: list[Figure] = []
    for pattern, _kind in _FIGURE_PATTERNS:
        for m in pattern.finditer(text):
            label = _normalize_label(m.group("label"))
            unit = m.group("unit") or ("%" if label in {"同比", "环比"} else "元")
            value = _to_float(m.groupdict().get("sign"), m.group("num"))
            # Directional verbs after 同比/环比
            span = m.group(0)
            if "下降" in span or "跌" in span or "减" in span:
                if value > 0 and label in {"同比", "环比"}:
                    value = -value
            key = (label, value, unit)
            if key in seen:
                continue
            seen.add(key)
            period = None
            if label in {"同比", "环比"}:
                period = label
            out.append(
                Figure(
                    label=label,
                    value=value,
                    unit=unit,
                    period=period,
                    raw=span.strip(),
                )
            )
            if len(out) >= max_figures:
                return out
    return out

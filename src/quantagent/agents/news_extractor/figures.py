"""Rule-based Chinese financial figure extraction (LLM later)."""

from __future__ import annotations

import re

from quantagent.agents.news_extractor.schema import Figure

# Common CN finance spans, e.g. 营收12.3亿元 / 同比增长15% / 总产值213亿元 / 持股5%.
_FIGURE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(?P<label>营收|营业收入|收入|净利润|净利|归母净利润|"
            r"中标金额|合同金额|订单金额|投资额|募资|产能|"
            r"总产值|进出口|货值|净流入|规模|装机|回购|持股|权益|"
            r"同比|环比|增长|下降)"
            r"[^\d\-－]{0,8}"
            r"(?P<sign>[\-－])?"
            r"(?P<num>\d+(?:\.\d+)?)"
            r"(?P<unit>亿美元|亿千瓦|亿元|亿|万元|万吨|吨|元|%|个百分点|倍)?"
        ),
        "labeled",
    ),
    (
        re.compile(
            r"(?P<label>同比|环比)"
            r"[^\d\-－]{0,6}"
            r"(?:增长|下降|升|跌|增|减|回升|上涨|涨幅)?"
            r"[^\d\-－]{0,4}"
            r"(?P<sign>[\-－])?"
            r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>%|个百分点)"
        ),
        "yoy",
    ),
    # Bare amount with 亿元/万元 when preceded by 达/至/为/近
    (
        re.compile(
            r"(?P<label>达|至|为|近|约)"
            r"(?P<sign>[\-－])?"
            r"(?P<num>\d+(?:\.\d+)?)"
            r"(?P<unit>亿美元|亿元|亿|万元|万吨|吨)"
        ),
        "bare_amount",
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
        "达": "金额",
        "至": "金额",
        "为": "金额",
        "近": "金额",
        "约": "金额",
        "权益": "持股",
    }
    return mapping.get(label, label)


def _normalize_unit(unit: str | None, *, label: str) -> str:
    if not unit:
        return "%" if label in {"同比", "环比", "回购", "持股"} else "元"
    if unit == "亿":
        return "亿元"
    return unit


def extract_figures(text: str, *, max_figures: int = 12) -> list[Figure]:
    """Extract numeric claims from Chinese financial text."""
    if not text or not text.strip():
        return []

    # Flatten newlines so "增长\\n9%" still matches.
    flat = re.sub(r"\s+", " ", text)

    seen: set[tuple[str, float, str]] = set()
    out: list[Figure] = []
    for pattern, _kind in _FIGURE_PATTERNS:
        for m in pattern.finditer(flat):
            label = _normalize_label(m.group("label"))
            unit = _normalize_unit(m.group("unit"), label=label)
            value = _to_float(m.groupdict().get("sign"), m.group("num"))
            span = m.group(0)
            # Skip year-like false positives: 预计2026年
            yearish = unit in {"元", "亿元"} and 1900 <= value <= 2100
            if yearish and "年" in flat[m.end() : m.end() + 2]:
                continue
            if "下降" in span or "跌" in span or "减" in span:
                if value > 0 and label in {"同比", "环比"}:
                    value = -value
            key = (label, value, unit)
            if key in seen:
                continue
            seen.add(key)
            period = label if label in {"同比", "环比"} else None
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

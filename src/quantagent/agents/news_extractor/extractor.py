"""Rule / template NewsExtractor (LLM backend plugged in later)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from quantagent.agents.news_extractor.figures import extract_figures
from quantagent.agents.news_extractor.schema import EventExtraction, EventType
from quantagent.data.normalizers.symbol import normalize_symbol

EXTRACTOR_MODEL = "rule_v1"
EXTRACTOR_VERSION = "0.1.0"

_SYMBOL_RE = re.compile(
    r"(?<!\d)(?P<code>\d{6})(?:\.(?P<ex>SH|SZ|BJ))?(?!\d)",
    re.IGNORECASE,
)

_EVENT_KEYWORDS: list[tuple[EventType, tuple[str, ...]]] = [
    ("earnings", ("净利润", "营收", "业绩", "年报", "季报", "财报", "预告")),
    ("guidance", ("指引", "展望", "预计", "目标")),
    ("contract", ("中标", "合同", "订单", "签约")),
    ("mna", ("并购", "收购", "重组", "要约")),
    ("shareholding", ("增持", "减持", "回购", "股权激励", "质押")),
    ("management", ("董事长", "总经理", "辞职", "任命", "高管")),
    ("litigation", ("诉讼", "仲裁", "判决", "立案")),
    ("regulation", ("监管", "处罚", "问询", "关注函", "警示")),
    ("policy", ("国务院", "央行", "证监会", "发改委", "政策")),
    ("macro", ("GDP", "CPI", "PMI", "利率", "社融")),
    ("product", ("发布", "新品", "获批", "注册")),
    ("capacity", ("产能", "扩产", "投产")),
    ("price_change", ("涨价", "降价", "提价")),
    ("rating", ("上调", "下调", "评级", "目标价")),
]

_POS = ("增长", "中标", "获批", "上调", "增持", "回购", "突破", "创新高")
_NEG = ("下降", "亏损", "处罚", "减持", "下跌", "警示", "诉讼", "下调", "暴跌")
_MAJOR = ("重大", "亿元", "涨停", "跌停", "立案", "退市")


def _repo_config() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "announcement_types.yaml"


class RuleNewsExtractor:
    """Deterministic extractor: keywords + regex figures + symbol scan."""

    def __init__(self, announcement_map: dict[str, str] | None = None) -> None:
        self._announce_map = announcement_map or self._load_announce_map()

    @staticmethod
    def _load_announce_map() -> dict[str, str]:
        path = _repo_config()
        if not path.exists():
            return {}
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = payload.get("mappings") or {}
        return {str(k): str(v) for k, v in raw.items()}

    def extract(
        self,
        *,
        title: str,
        body: str | None = None,
        announce_type: str | None = None,
        hint_symbol: str | None = None,
    ) -> EventExtraction:
        text = f"{title}\n{body or ''}".strip()
        figures = extract_figures(text)
        symbols = self._extract_symbols(text)
        if hint_symbol:
            try:
                canon = normalize_symbol(hint_symbol, market="CN")
                if canon not in symbols:
                    symbols.insert(0, canon)
            except ValueError:
                pass

        event_type = self._classify(text, announce_type=announce_type)
        direction = self._direction(text)
        magnitude = self._magnitude(text, figures)
        is_relevant = bool(symbols) or event_type != "other" or bool(figures)

        summary = title.strip()
        if len(summary) > 200:
            summary = summary[:197] + "..."

        conf = 0.35
        if symbols:
            conf += 0.2
        if figures:
            conf += 0.2
        if announce_type:
            conf += 0.1
        conf = min(conf, 0.9)

        return EventExtraction(
            is_relevant=is_relevant,
            event_type=event_type,
            summary=summary,
            primary_symbols=symbols[:5],
            direction=direction,
            magnitude=magnitude,
            horizon="short",
            confidence=round(conf, 3),
            figures=figures,
        )

    def extract_batch(self, items: list[dict[str, Any]]) -> list[EventExtraction]:
        out: list[EventExtraction] = []
        for item in items:
            out.append(
                self.extract(
                    title=str(item.get("title") or ""),
                    body=item.get("body"),
                    announce_type=item.get("announce_type"),
                    hint_symbol=item.get("related_symbol") or item.get("hint_symbol"),
                )
            )
        return out

    def _classify(self, text: str, *, announce_type: str | None) -> EventType:
        if announce_type:
            for key, etype in self._announce_map.items():
                if key in announce_type:
                    return etype  # type: ignore[return-value]
        for etype, keys in _EVENT_KEYWORDS:
            if any(k in text for k in keys):
                return etype
        return "other"

    def _direction(self, text: str) -> str:
        pos = sum(1 for k in _POS if k in text)
        neg = sum(1 for k in _NEG if k in text)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        if pos and neg:
            return "unclear"
        return "neutral"

    def _magnitude(self, text: str, figures: list[Any]) -> str:
        if any(k in text for k in _MAJOR):
            return "major"
        for fig in figures:
            if fig.unit == "亿元" and abs(fig.value) >= 10:
                return "major"
            if fig.unit == "%" and abs(fig.value) >= 50:
                return "major"
        if figures:
            return "moderate"
        return "minor"

    def _extract_symbols(self, text: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for m in _SYMBOL_RE.finditer(text):
            code = m.group("code")
            ex = m.group("ex")
            raw = f"{code}.{ex}" if ex else code
            try:
                canon = normalize_symbol(raw, market="CN")
            except ValueError:
                continue
            if canon in seen:
                continue
            seen.add(canon)
            found.append(canon)
        return found

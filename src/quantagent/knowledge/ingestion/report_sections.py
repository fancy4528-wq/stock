"""Extract MD&A / risk-factor sections from periodic-report plain text."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Heading patterns used in A-share annual / interim reports (plain text / HTML→text).
_MDA_START = re.compile(
    r"(?:"
    r"(?:第[一二三四五六七八九十0-9]+节\s*[：:.]?\s*)?"
    r"(?:管理层讨论与分析|经营情况讨论与分析|董事会报告|"
    r"董事会关于公司报告期内经营情况的讨论与分析)"
    r"|"
    r"Management(?:'s)?\s+Discussion\s+and\s+Analysis"
    r")",
    re.IGNORECASE,
)

_RISK_START = re.compile(
    r"(?:"
    r"(?:第[一二三四五六七八九十0-9]+节\s*[：:.]?\s*)?"
    r"(?:可能面对的风险|风险因素|公司面临的风险|主要风险|重大风险提示)"
    r"|"
    r"Risk\s+Factors?"
    r")",
    re.IGNORECASE,
)

# Common section boundaries that end MD&A / risk blocks.
_SECTION_END = re.compile(
    r"(?:"
    r"第[一二三四五六七八九十0-9]+节\s*[：:.]?\s*"
    r"(?:公司治理|重要事项|财务报告|合并财务报表|"
    r"公司基本情况|释义|会计数据|股份变动|董事、监事、高级管理人员|"
    r"投资者关系|备查文件|环境和社会责任)"
    r"|"
    r"(?:五、|六、|七、|八、)\s*(?:公司治理|重要事项|财务报告)"
    r")"
)

_SUBSECTION = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    r"[（(][一二三四五六七八九十0-9]+[)）]"
    r"|"
    r"[一二三四五六七八九十]+、"
    r"|"
    r"[0-9]+[、.]"
    r")"
    r"\s*[^\n]{0,40}"
)

_RISK_ITEM = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    r"[（(][一二三四五六七八九十0-9]+[)）]"
    r"|"
    r"[0-9]+[、.]"
    r"|"
    r"[•●◆■]"
    r"|"
    r"风险[0-9]+[：:]"
    r")"
    r"\s*"
)


@dataclass(frozen=True)
class ReportSections:
    """Extracted narrative sections (may be empty if markers missing)."""

    mda: str
    risk: str


def normalize_report_text(text: str) -> str:
    """Collapse noisy whitespace while keeping paragraph breaks."""
    if not text:
        return ""
    # HTML leftovers from notice pages
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = cleaned.replace("\u3000", " ").replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_section(
    text: str,
    *,
    start: re.Pattern[str],
    end: re.Pattern[str] | None = None,
) -> str:
    """Return body after ``start`` until ``end`` (or next chapter-like heading)."""
    cleaned = normalize_report_text(text)
    if not cleaned:
        return ""
    m = start.search(cleaned)
    if m is None:
        return ""
    body = cleaned[m.end() :]
    stopper = end or _SECTION_END
    stop = stopper.search(body)
    if stop is not None and stop.start() > 40:
        body = body[: stop.start()]
    return body.strip(" ：:\n\t")


def extract_report_sections(
    full_text: str,
    *,
    mda_text: str | None = None,
    risk_text: str | None = None,
) -> ReportSections:
    """Prefer explicit fields; otherwise pull sections from ``full_text``."""
    mda = (mda_text or "").strip()
    risk = (risk_text or "").strip()
    if not mda and full_text:
        mda = extract_section(full_text, start=_MDA_START)
    if not risk and full_text:
        risk = extract_section(full_text, start=_RISK_START)
    return ReportSections(
        mda=normalize_report_text(mda),
        risk=normalize_report_text(risk),
    )


def split_mda_subsections(text: str, *, max_chars: int = 800) -> list[str]:
    """Split MD&A by subsection headings; fall back to fixed-size windows."""
    cleaned = normalize_report_text(text)
    if not cleaned:
        return []
    spans = _split_by_pattern(cleaned, _SUBSECTION)
    if len(spans) >= 2:
        return _cap_spans(spans, max_chars=max_chars)
    from quantagent.knowledge.ingestion.documents import chunk_text

    return chunk_text(cleaned, max_chars=max_chars, overlap=80)


def split_risk_items(text: str, *, max_chars: int = 800) -> list[str]:
    """Split risk factors by numbered / bulleted items."""
    cleaned = normalize_report_text(text)
    if not cleaned:
        return []
    spans = _split_by_pattern(cleaned, _RISK_ITEM)
    if len(spans) >= 2:
        return _cap_spans(spans, max_chars=max_chars)
    from quantagent.knowledge.ingestion.documents import chunk_text

    return chunk_text(cleaned, max_chars=max_chars, overlap=40)


def _split_by_pattern(text: str, pattern: re.Pattern[str]) -> list[str]:
    matches = list(pattern.finditer(text))
    if not matches:
        return [text]
    parts: list[str] = []
    # Leading preamble before first marker (keep if substantial).
    if matches[0].start() > 40:
        head = text[: matches[0].start()].strip()
        if head:
            parts.append(head)
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[m.start() : end].strip()
        if chunk:
            parts.append(chunk)
    return parts


def _cap_spans(spans: list[str], *, max_chars: int) -> list[str]:
    """Keep one span per subsection/item; hard-split only when oversized."""
    from quantagent.knowledge.ingestion.documents import chunk_text

    out: list[str] = []
    for span in spans:
        span = span.strip()
        if not span:
            continue
        if len(span) <= max_chars:
            out.append(span)
        else:
            out.extend(chunk_text(span, max_chars=max_chars, overlap=60))
    return out

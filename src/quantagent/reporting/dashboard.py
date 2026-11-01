"""Static HTML dashboard for the current read-only reports (docs/01 §8).

Jinja2 pages plus one Plotly chart. Inputs are the files the pipeline
already writes: daily markdown, shadow JSONL, backtest markdown, and the
optional Agent IC note. Nothing here rescores or starts a server.

``refresh_readout`` rebuilds the page after those writers finish.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import plotly.graph_objects as go
from jinja2 import Environment, StrictUndefined
from markupsafe import Markup
from pydantic import ValidationError

from quantagent.evaluation.agent.journal import agent_score_journal_path
from quantagent.evaluation.agent.types import AgentScoreDay
from quantagent.evaluation.shadow.types import ShadowDayRecord, ShadowPortfolioId

logger = logging.getLogger(__name__)

PORTFOLIOS: tuple[ShadowPortfolioId, ...] = (
    "shadow_baseline",
    "shadow_factor",
    "shadow_quant",
    "shadow_agent",
    "shadow_fused",
    "shadow_fused_norisk",
)

PORTFOLIO_LABELS: dict[str, str] = {
    "shadow_baseline": "shadow_baseline · 等权池",
    "shadow_factor": "shadow_factor · 单因子",
    "shadow_quant": "shadow_quant · 量化",
    "shadow_agent": "shadow_agent · Agent",
    "shadow_fused": "shadow_fused · Fusion",
    "shadow_fused_norisk": "shadow_fused_norisk · Fusion 无风控",
}

_DATE_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_SAFE_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")

_ENV = Environment(autoescape=True, undefined=StrictUndefined)

_CSS = """
:root { color-scheme: light; }
body {
  margin: 0;
  background: #f4f6f8;
  color: #1c1f24;
  font-family: "Segoe UI", "PingFang SC", "Noto Sans SC", sans-serif;
  line-height: 1.5;
}
main { max-width: 1080px; margin: 0 auto; padding: 28px 20px 72px; }
h1 { font-size: 1.55rem; margin: 0 0 0.3rem; }
h2 { font-size: 1.15rem; margin: 0 0 0.75rem; }
a { color: #0b57d0; }
.muted { color: #5c6570; }
.banner {
  background: #fff8e8;
  border: 1px solid #ead7a1;
  border-radius: 8px;
  padding: 10px 14px;
  margin: 14px 0 0;
}
section {
  background: #fff;
  border: 1px solid #e4e7ec;
  border-radius: 10px;
  padding: 16px 18px 18px;
  margin-top: 16px;
}
table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
th, td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #eef0f3;
  vertical-align: top;
}
th { color: #5c6570; font-weight: 600; }
.pos { color: #0d7a3f; }
.neg { color: #b42318; }
ul.plain { padding-left: 1.2rem; }
article.report table { width: max-content; min-width: 100%; border-collapse: collapse; }
.table-wrap { overflow-x: auto; }
article.report h1 { font-size: 1.35rem; }
article.report h2 { font-size: 1.05rem; margin-top: 1.4rem; }
.chart { height: 460px; }
"""

_INDEX = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>QuantAgent 只读看板</title>
  <style>{{ css }}</style>
</head>
<body>
<main>
  <h1>QuantAgent 只读看板</h1>
  <p class="muted">生成于 {{ generated_at }}。数据来自本地日报、Shadow 日志和回测稿。</p>
  <p class="banner">本页只展示已经落盘的结果，不构成投资建议。回测与 Shadow 的撮合假设尚未校准。</p>
  <p><nav class="top">
    <a href="#shadow">Shadow</a>
    <a href="#agent">Agent 打分</a>
    <a href="#daily">日报</a>
    <a href="#backtests">回测</a>
  </nav></p>

  <section id="shadow">
    <h2>Shadow 累计收益</h2>
    {% if span %}
    <p class="muted">{{ span }}</p>
    {% endif %}
    {% if chart_html %}
    <div class="chart">{{ chart_html }}</div>
    {% else %}
    <p>尚无 Shadow 记录。</p>
    {% endif %}
    {% if rows %}
    <table>
      <thead>
        <tr>
          <th>组合</th><th>截至</th><th>今日</th><th>累计</th>
          <th>最大回撤</th><th>净值</th><th>持仓数</th><th>策略版本</th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
        <tr>
          <td>{{ row.label }}</td>
          <td>{{ row.as_of }}</td>
          <td class="{{ row.ret_1d_tone }}">{{ row.ret_1d }}</td>
          <td class="{{ row.ret_cum_tone }}">{{ row.ret_cum }}</td>
          <td class="{{ row.mdd_tone }}">{{ row.max_drawdown }}</td>
          <td>{{ row.nav }}</td>
          <td>{{ row.n_positions }}</td>
          <td>{{ row.strategy_version }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </section>

  <section id="agent">
    <h2>Agent 打分日志</h2>
    <p>{{ agent_summary }}</p>
    {% if agent_href %}
    <p><a href="{{ agent_href }}">查看 IC 报告</a></p>
    {% else %}
    <p>IC 报告尚未生成。</p>
    {% endif %}
  </section>

  <section id="daily">
    <h2>日报</h2>
    {% if daily %}
    <ul class="plain">
      {% for doc in daily %}
      <li><a href="{{ doc.href }}">{{ doc.title }}</a></li>
      {% endfor %}
    </ul>
    {% else %}
    <p>尚无日报。</p>
    {% endif %}
  </section>

  <section id="backtests">
    <h2>回测</h2>
    {% if backtests %}
    <ul class="plain">
      {% for doc in backtests %}
      <li><a href="{{ doc.href }}">{{ doc.title }}</a></li>
      {% endfor %}
    </ul>
    {% else %}
    <p>尚无回测。</p>
    {% endif %}
  </section>

  {% if warnings %}
  <section>
    <h2>读取提示</h2>
    <ul class="plain">
      {% for warning in warnings %}
      <li>{{ warning }}</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}
</main>
</body>
</html>
"""

_ARTICLE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>{{ title }}</title>
  <style>{{ css }}</style>
</head>
<body>
<main>
  <p>
    <a href="{{ home_href }}">返回看板</a>
    {% if source_href %} · <a href="{{ source_href }}">原文</a>{% endif %}
  </p>
  <p class="banner">只读摘录，不构成投资建议。撮合假设尚未校准。</p>
  <article class="report">
    {{ body }}
  </article>
</main>
</body>
</html>
"""


@dataclass(frozen=True)
class ShadowPoint:
    portfolio: str
    as_of: date
    ret_1d: float
    ret_cum: float
    max_drawdown: float
    nav: float
    n_positions: int
    strategy_version: str


@dataclass(frozen=True)
class SnapshotRow:
    label: str
    as_of: str
    ret_1d: str
    ret_1d_tone: str
    ret_cum: str
    ret_cum_tone: str
    max_drawdown: str
    mdd_tone: str
    nav: str
    n_positions: int
    strategy_version: str


@dataclass(frozen=True)
class MarkdownDoc:
    slug: str
    title: str
    source: Path


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def _tone(value: float) -> str:
    if value > 0:
        return "pos"
    if value < 0:
        return "neg"
    return ""


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _render_markdown(text: str) -> Markup:
    import markdown

    html = markdown.markdown(text, extensions=["tables", "fenced_code"])
    if not isinstance(html, str):
        raise TypeError("markdown renderer did not return a string")
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>"
    )
    return Markup(html)


def _href(from_html: Path, target: Path) -> str:
    return Path(os.path.relpath(target, start=from_html.parent)).as_posix()


def load_shadow_series(shadow_dir: Path) -> tuple[dict[str, list[ShadowPoint]], list[str]]:
    """Last row per portfolio and date wins. Bad lines are skipped."""
    series: dict[str, list[ShadowPoint]] = {}
    warnings: list[str] = []
    if not shadow_dir.is_dir():
        return series, warnings
    for portfolio in PORTFOLIOS:
        path = shadow_dir / f"{portfolio}.jsonl"
        if not path.is_file():
            continue
        by_day: dict[date, ShadowPoint] = {}
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                record = ShadowDayRecord.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as exc:
                warnings.append(f"{path.name} 第 {lineno} 行无法读取（{type(exc).__name__}）")
                continue
            if record.portfolio != portfolio:
                warnings.append(f"{path.name} 第 {lineno} 行组合是 {record.portfolio}，已跳过")
                continue
            by_day[record.as_of] = ShadowPoint(
                portfolio=portfolio,
                as_of=record.as_of,
                ret_1d=record.ret_1d,
                ret_cum=record.ret_cum,
                max_drawdown=record.max_drawdown,
                nav=record.nav,
                n_positions=record.n_positions,
                strategy_version=record.strategy_version,
            )
        if by_day:
            series[portfolio] = [by_day[day] for day in sorted(by_day)]
    return series, warnings


def snapshot_rows(series: dict[str, list[ShadowPoint]]) -> list[SnapshotRow]:
    rows: list[SnapshotRow] = []
    for portfolio in PORTFOLIOS:
        points = series.get(portfolio)
        if not points:
            continue
        last = points[-1]
        rows.append(
            SnapshotRow(
                label=PORTFOLIO_LABELS[portfolio],
                as_of=last.as_of.isoformat(),
                ret_1d=_pct(last.ret_1d),
                ret_1d_tone=_tone(last.ret_1d),
                ret_cum=_pct(last.ret_cum),
                ret_cum_tone=_tone(last.ret_cum),
                max_drawdown=_pct(last.max_drawdown),
                mdd_tone=_tone(last.max_drawdown),
                nav=f"{last.nav:,.0f}",
                n_positions=last.n_positions,
                strategy_version=last.strategy_version,
            )
        )
    return rows


def _span(series: dict[str, list[ShadowPoint]]) -> str:
    days = [point.as_of for points in series.values() for point in points]
    if not days:
        return ""
    return f"{min(days).isoformat()} → {max(days).isoformat()}"


def list_daily_reports(reports_dir: Path) -> list[MarkdownDoc]:
    if not reports_dir.is_dir():
        return []
    found: list[tuple[str, MarkdownDoc]] = []
    for path in reports_dir.glob("*.md"):
        match = _DATE_NAME.match(path.name)
        if match is None:
            continue
        text = path.read_text(encoding="utf-8")
        stamp = match.group(1)
        found.append(
            (
                stamp,
                MarkdownDoc(
                    slug=stamp,
                    title=_title_from_markdown(text, stamp),
                    source=path,
                ),
            )
        )
    found.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in found]


def list_backtests(backtests_dir: Path) -> list[MarkdownDoc]:
    if not backtests_dir.is_dir():
        return []
    docs: list[MarkdownDoc] = []
    for path in sorted(backtests_dir.glob("*.md")):
        if path.name.lower() == "readme.md" or _SAFE_SLUG.match(path.stem) is None:
            continue
        text = path.read_text(encoding="utf-8")
        docs.append(
            MarkdownDoc(
                slug=path.stem,
                title=_title_from_markdown(text, path.stem),
                source=path,
            )
        )
    return docs


def agent_journal_counts(shadow_dir: Path) -> tuple[int, int, int, list[str]]:
    """Return live days, synthetic days, live point count, and read warnings."""
    path = agent_score_journal_path(shadow_dir)
    if not path.is_file():
        return 0, 0, 0, []
    live_days = 0
    synthetic_days = 0
    live_points = 0
    warnings: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            day = AgentScoreDay.model_validate(json.loads(stripped))
        except (json.JSONDecodeError, ValidationError) as exc:
            warnings.append(f"{path.name} 第 {lineno} 行无法读取（{type(exc).__name__}）")
            continue
        if day.origin == "synthetic":
            synthetic_days += 1
        else:
            live_days += 1
            live_points += len(day.points)
    return live_days, synthetic_days, live_points, warnings


def _chart_html(series: dict[str, list[ShadowPoint]]) -> Markup:
    fig = go.Figure()
    for portfolio in PORTFOLIOS:
        points = series.get(portfolio)
        if not points:
            continue
        fig.add_trace(
            go.Scatter(
                x=[point.as_of.isoformat() for point in points],
                y=[point.ret_cum * 100 for point in points],
                mode="lines+markers" if len(points) < 3 else "lines",
                name=PORTFOLIO_LABELS[portfolio],
                hovertemplate="%{x}<br>%{y:.2f}%<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        yaxis_title="%",
        xaxis_title=None,
        hovermode="x unified",
        template="plotly_white",
        height=440,
        margin={"l": 56, "r": 16, "t": 24, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    )
    raw = fig.to_html(full_html=False, include_plotlyjs="cdn")
    if not isinstance(raw, str):
        raise TypeError("Plotly did not return HTML")
    return Markup(raw)


def _disambiguate(docs: list[MarkdownDoc]) -> list[MarkdownDoc]:
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.title] = counts.get(doc.title, 0) + 1
    if all(count == 1 for count in counts.values()):
        return docs
    return [
        MarkdownDoc(
            slug=doc.slug,
            title=doc.title if counts[doc.title] == 1 else f"{doc.title} ({doc.slug})",
            source=doc.source,
        )
        for doc in docs
    ]


def _clear_html(directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in directory.glob("*.html"):
        path.unlink()


def _write_article(doc: MarkdownDoc, dest: Path, home: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = _render_markdown(doc.source.read_text(encoding="utf-8"))
    html = _ENV.from_string(_ARTICLE).render(
        css=_CSS,
        title=doc.title,
        home_href=_href(dest, home),
        source_href=_href(dest, doc.source),
        body=body,
    )
    dest.write_text(html, encoding="utf-8")


def write_dashboard(
    *,
    shadow_dir: Path,
    reports_dir: Path,
    backtests_dir: Path,
    out: Path,
    agent_eval: Path | None = None,
) -> Path:
    """Write ``out`` plus linked daily, backtest, and optional IC pages."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _clear_html(out.parent / "daily")
    _clear_html(out.parent / "backtests")
    series, warnings = load_shadow_series(shadow_dir)
    live_days, synthetic_days, live_points, agent_warnings = agent_journal_counts(shadow_dir)
    warnings.extend(agent_warnings)
    daily = _disambiguate(list_daily_reports(reports_dir))
    backtests = _disambiguate(list_backtests(backtests_dir))

    for doc in daily:
        _write_article(doc, out.parent / "daily" / f"{doc.slug}.html", out)
    for doc in backtests:
        _write_article(doc, out.parent / "backtests" / f"{doc.slug}.html", out)

    agent_href = ""
    agent_page = out.parent / "agent-ic.html"
    if agent_eval is not None and agent_eval.is_file():
        agent_doc = MarkdownDoc(
            slug="agent-ic",
            title=_title_from_markdown(agent_eval.read_text(encoding="utf-8"), "Agent IC"),
            source=agent_eval,
        )
        _write_article(agent_doc, agent_page, out)
        agent_href = _href(out, agent_page)
    elif agent_page.is_file():
        agent_page.unlink()

    chart = _chart_html(series) if series else Markup("")
    agent_summary = (
        f"前向打分：live {live_days} 天（{live_points} 个分数），synthetic {synthetic_days} 天。"
        "IC 与校准要等收益标签兑现后再计算；有效截面不足 20 天时只作跟踪。"
    )
    page = _ENV.from_string(_INDEX).render(
        css=_CSS,
        generated_at=datetime.now().astimezone().isoformat(timespec="minutes"),
        span=_span(series),
        chart_html=chart,
        rows=snapshot_rows(series),
        agent_summary=agent_summary,
        agent_href=agent_href,
        daily=[{"title": doc.title, "href": f"daily/{doc.slug}.html"} for doc in daily],
        backtests=[{"title": doc.title, "href": f"backtests/{doc.slug}.html"} for doc in backtests],
        warnings=warnings,
    )
    out.write_text(page, encoding="utf-8")
    return out


def refresh_readout(
    *,
    reports_dir: Path | str,
    shadow_dir: Path | str,
    backtests_dir: Path | str | None = None,
    agent_eval: Path | str | None = None,
    out: Path | str | None = None,
) -> Path | None:
    """Rebuild the dashboard beside ``reports_dir``.

    The daily pipeline, backtest writer, and agent-eval call this so the page
    follows files already on disk. A render error is logged and swallowed.
    """
    reports = Path(reports_dir)
    root = reports.parent
    try:
        path = write_dashboard(
            shadow_dir=Path(shadow_dir),
            reports_dir=reports,
            backtests_dir=(
                Path(backtests_dir) if backtests_dir is not None else root / "backtest-reports"
            ),
            out=Path(out) if out is not None else root / "dashboard" / "index.html",
            agent_eval=(
                Path(agent_eval) if agent_eval is not None else root / "agent-eval" / "agent-ic.md"
            ),
        )
    except Exception:
        logger.exception("dashboard refresh failed")
        return None
    print(f"dashboard: wrote {path}")
    return path

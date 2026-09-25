"""B-class portfolio risk triggers — pure rules, zero LLM (P2a)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from quantagent.decision.risk.config import RiskConfig, load_risk_config
from quantagent.monitor.triggers.base import TriggerSpec, format_message
from quantagent.monitor.types import QuoteSnapshot, Severity, TriggerHit
from quantagent.positions.types import ManualPositionBook

_DEFAULTS: dict[str, TriggerSpec] = {
    "RISK_SECTOR_CONCENTRATION": TriggerSpec(
        code="RISK_SECTOR_CONCENTRATION",
        severity="high",
        message="{industry} 行业权重达 {weight:.1%}，接近上限 {limit:.0%}",
        cooldown_hours=24,
    ),
    "RISK_PORTFOLIO_DRAWDOWN": TriggerSpec(
        code="RISK_PORTFOLIO_DRAWDOWN",
        severity="critical",
        message="组合回撤 {drawdown:.1%}（峰值 {peak_nav:.0f} → 现 {nav:.0f}）",
        cooldown_hours=12,
    ),
    "RISK_DAILY_LOSS": TriggerSpec(
        code="RISK_DAILY_LOSS",
        severity="critical",
        message="今日组合亏损 {daily_pnl_pct:.1%}",
        cooldown_hours=6,
    ),
    "RISK_SINGLE_WEIGHT": TriggerSpec(
        code="RISK_SINGLE_WEIGHT",
        severity="medium",
        message="{name} 权重 {weight:.1%} 接近单股上限 {limit:.0%}",
        cooldown_hours=24,
    ),
    "RISK_CASH_LOW": TriggerSpec(
        code="RISK_CASH_LOW",
        severity="medium",
        message="现金比例 {cash_ratio:.1%}，低于建议下限 {limit:.0%}",
        cooldown_hours=24,
    ),
    "RISK_DD_005": TriggerSpec(
        code="RISK_DD_005",
        severity="critical",
        message="{name} 浮亏 {holding_return:.1%}，触及系统底线 -25%（强制减仓提醒）",
        cooldown_hours=24,
    ),
}

# Soft warn thresholds (fire before hard config limit).
_SECTOR_WARN_RATIO = 0.92  # 0.25 * 0.92 ≈ 0.23
_SINGLE_WARN_RATIO = 0.95  # 0.10 * 0.95 = 0.095
_CASH_WARN_RATIO = 0.50  # warn at half of min_cash (0.10 → 0.05)
_PORTFOLIO_DD_WARN = 0.10
_DAILY_LOSS_WARN = -0.025
_DD_005 = -0.25


@dataclass(frozen=True)
class PortfolioRiskMetrics:
    nav: float
    peak_nav: float
    portfolio_drawdown: float
    daily_pnl_pct: float
    cash_ratio: float
    max_single_weight: float
    max_single_symbol: str
    max_single_name: str
    industry_weights: dict[str, float]
    max_industry: str
    max_industry_weight: float
    holding_returns: dict[str, float]


def compute_portfolio_risk_metrics(
    book: ManualPositionBook,
    quotes: dict[str, QuoteSnapshot],
) -> PortfolioRiskMetrics:
    last_map = {s: q.last for s, q in quotes.items() if q.last > 0}
    prev_map = {
        s: float(q.prev_close)
        for s, q in quotes.items()
        if q.prev_close is not None and q.prev_close > 0
    }
    nav = book.market_value(last_map)
    prev_nav = book.market_value(prev_map) if prev_map else nav
    peak = float(book.peak_nav) if book.peak_nav and book.peak_nav > 0 else max(nav, prev_nav)
    peak = max(peak, nav)
    dd = nav / peak - 1.0 if peak > 0 else 0.0
    daily = nav / prev_nav - 1.0 if prev_nav > 0 else 0.0
    cash_ratio = (book.cash / nav) if nav > 0 else 1.0

    max_w = 0.0
    max_sym = ""
    max_name = ""
    for p in book.positions:
        w = book.weight(p.symbol, last_map)
        if w > max_w:
            max_w = w
            max_sym = p.symbol
            max_name = p.name or p.symbol

    ind: dict[str, float] = {}
    for p in book.positions:
        key = (p.industry or "").strip() or "_unknown"
        ind[key] = ind.get(key, 0.0) + book.weight(p.symbol, last_map)
    max_ind = ""
    max_ind_w = 0.0
    for k, w in ind.items():
        if k == "_unknown":
            continue
        if w > max_ind_w:
            max_ind_w = w
            max_ind = k

    rets: dict[str, float] = {}
    for p in book.positions:
        px = last_map.get(p.symbol)
        if px is not None and p.avg_cost > 0:
            rets[p.symbol] = px / p.avg_cost - 1.0

    return PortfolioRiskMetrics(
        nav=nav,
        peak_nav=peak,
        portfolio_drawdown=dd,
        daily_pnl_pct=daily,
        cash_ratio=cash_ratio,
        max_single_weight=max_w,
        max_single_symbol=max_sym,
        max_single_name=max_name,
        industry_weights=ind,
        max_industry=max_ind,
        max_industry_weight=max_ind_w,
        holding_returns=rets,
    )


def _hit(
    spec: TriggerSpec,
    *,
    symbol: str,
    message_kwargs: dict[str, Any],
    evidence: dict[str, Any],
) -> TriggerHit:
    return TriggerHit(
        code=spec.code,
        severity=cast(Severity, spec.severity),
        symbol=symbol,
        title=f"{spec.code} {symbol}"[:60],
        message=format_message(spec.message, **message_kwargs),
        evidence=evidence,
        cooldown_hours=spec.cooldown_hours,
    )


def evaluate_risk_triggers(
    book: ManualPositionBook,
    quotes: dict[str, QuoteSnapshot],
    *,
    risk_cfg: RiskConfig | None = None,
    specs: dict[str, TriggerSpec] | None = None,
    market: str = "CN",
) -> list[TriggerHit]:
    """Evaluate B-class portfolio risk rules."""
    cfg = risk_cfg or load_risk_config(market)
    specs = specs or dict(_DEFAULTS)
    m = compute_portfolio_risk_metrics(book, quotes)
    hits: list[TriggerHit] = []

    # Sector concentration (skip if no industry labels)
    sector_limit = cfg.position.max_industry_weight * _SECTOR_WARN_RATIO
    if m.max_industry and m.max_industry_weight >= sector_limit:
        spec = specs.get("RISK_SECTOR_CONCENTRATION")
        if spec and spec.enabled:
            hits.append(
                _hit(
                    spec,
                    symbol=m.max_industry,
                    message_kwargs={
                        "industry": m.max_industry,
                        "weight": m.max_industry_weight,
                        "limit": cfg.position.max_industry_weight,
                    },
                    evidence={
                        "industry": m.max_industry,
                        "weight": m.max_industry_weight,
                        "limit": cfg.position.max_industry_weight,
                    },
                )
            )

    if m.portfolio_drawdown <= -_PORTFOLIO_DD_WARN:
        spec = specs.get("RISK_PORTFOLIO_DRAWDOWN")
        if spec and spec.enabled:
            hits.append(
                _hit(
                    spec,
                    symbol="PORTFOLIO",
                    message_kwargs={
                        "drawdown": m.portfolio_drawdown,
                        "peak_nav": m.peak_nav,
                        "nav": m.nav,
                    },
                    evidence={
                        "drawdown": m.portfolio_drawdown,
                        "peak_nav": m.peak_nav,
                        "nav": m.nav,
                    },
                )
            )

    if m.daily_pnl_pct <= _DAILY_LOSS_WARN:
        spec = specs.get("RISK_DAILY_LOSS")
        if spec and spec.enabled:
            hits.append(
                _hit(
                    spec,
                    symbol="PORTFOLIO",
                    message_kwargs={"daily_pnl_pct": m.daily_pnl_pct},
                    evidence={"daily_pnl_pct": m.daily_pnl_pct, "nav": m.nav},
                )
            )

    if m.max_single_weight >= cfg.position.max_single_weight * _SINGLE_WARN_RATIO:
        spec = specs.get("RISK_SINGLE_WEIGHT")
        if spec and spec.enabled and m.max_single_symbol:
            hits.append(
                _hit(
                    spec,
                    symbol=m.max_single_symbol,
                    message_kwargs={
                        "name": m.max_single_name,
                        "weight": m.max_single_weight,
                        "limit": cfg.position.max_single_weight,
                    },
                    evidence={
                        "weight": m.max_single_weight,
                        "limit": cfg.position.max_single_weight,
                    },
                )
            )

    cash_floor = cfg.position.min_cash * _CASH_WARN_RATIO
    if m.cash_ratio < cash_floor:
        spec = specs.get("RISK_CASH_LOW")
        if spec and spec.enabled:
            hits.append(
                _hit(
                    spec,
                    symbol="CASH",
                    message_kwargs={
                        "cash_ratio": m.cash_ratio,
                        "limit": cfg.position.min_cash,
                    },
                    evidence={"cash_ratio": m.cash_ratio, "min_cash": cfg.position.min_cash},
                )
            )

    # System floor DD_005 — independent of user exit policy
    spec = specs.get("RISK_DD_005")
    if spec and spec.enabled:
        name_map = {p.symbol: (p.name or p.symbol) for p in book.positions}
        for sym, ret in m.holding_returns.items():
            if ret <= _DD_005:
                hits.append(
                    _hit(
                        spec,
                        symbol=sym,
                        message_kwargs={
                            "name": name_map.get(sym, sym),
                            "holding_return": ret,
                        },
                        evidence={"holding_return": ret, "floor": _DD_005},
                    )
                )

    return hits

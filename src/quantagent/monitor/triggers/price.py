"""A-class price triggers — pure rules, zero LLM (P2a)."""

from __future__ import annotations

from typing import Any, cast

from quantagent.monitor.exit_policy import ExitPolicy
from quantagent.monitor.triggers.base import TriggerSpec, format_message
from quantagent.monitor.types import HoldingMetrics, Severity, TriggerHit

# Default templates if YAML missing a code.
_DEFAULTS: dict[str, TriggerSpec] = {
    "PX_STOP_LOSS": TriggerSpec(
        code="PX_STOP_LOSS",
        severity="critical",
        message="{name} 浮亏达 {holding_return:.1%}，触及止损线 {threshold:.0%}",
        cooldown_hours=24,
    ),
    "PX_TRAILING_STOP": TriggerSpec(
        code="PX_TRAILING_STOP",
        severity="critical",
        message=(
            "{name} 自持仓高点回撤 {drawdown_from_entry_high:.1%}，触及移动止损 {trail_pct:.0%}"
        ),
        cooldown_hours=24,
    ),
    "PX_TAKE_PROFIT": TriggerSpec(
        code="PX_TAKE_PROFIT",
        severity="high",
        message="{name} 浮盈 {holding_return:.1%}，达到止盈档位（建议减 {reduce:.0%}）",
        cooldown_hours=24,
    ),
    "PX_TARGET_PRICE": TriggerSpec(
        code="PX_TARGET_PRICE",
        severity="high",
        message="{name} 触及目标价 {target_price}",
        cooldown_hours=24,
    ),
    "PX_LIMIT_UP": TriggerSpec(
        code="PX_LIMIT_UP",
        severity="medium",
        message="{name} 涨停。若计划卖出，注意封板可能打开",
        cooldown_hours=4,
    ),
    "PX_LIMIT_DOWN": TriggerSpec(
        code="PX_LIMIT_DOWN",
        severity="critical",
        message="{name} 跌停，当前无法卖出",
        cooldown_hours=4,
    ),
    "PX_SUSPENDED": TriggerSpec(
        code="PX_SUSPENDED",
        severity="critical",
        message="{name} 停牌",
        cooldown_hours=24,
    ),
    "PX_BREAK_MA60": TriggerSpec(
        code="PX_BREAK_MA60",
        severity="medium",
        message="{name} 跌破 60 日线",
        cooldown_hours=72,
    ),
    "PX_VOL_SPIKE": TriggerSpec(
        code="PX_VOL_SPIKE",
        severity="high",
        message="{name} 放量异动，成交量为 5 日均量 {volume_ratio_5d:.1f} 倍",
        cooldown_hours=6,
    ),
    "PX_DRAWDOWN_FROM_HIGH": TriggerSpec(
        code="PX_DRAWDOWN_FROM_HIGH",
        severity="high",
        message="{name} 自建仓后高点回撤 {drawdown_from_entry_high:.1%}",
        cooldown_hours=24,
    ),
}


def _hit(
    spec: TriggerSpec,
    m: HoldingMetrics,
    *,
    evidence: dict[str, Any],
    **fmt: object,
) -> TriggerHit:
    ctx = {
        "name": m.name,
        "symbol": m.symbol,
        "holding_return": m.holding_return,
        "drawdown_from_entry_high": m.drawdown_from_entry_high,
        "weight": m.weight,
        "last": m.last,
        "volume_ratio_5d": m.volume_ratio_5d or 0.0,
        "target_price": m.target_price or 0.0,
        **fmt,
    }
    return TriggerHit(
        code=spec.code,
        severity=cast(Severity, spec.severity),
        symbol=m.symbol,
        title=f"{spec.code} {m.symbol}",
        message=format_message(spec.message, **ctx),
        evidence=evidence,
        cooldown_hours=spec.cooldown_hours,
    )


def evaluate_price_triggers(
    m: HoldingMetrics,
    policy: ExitPolicy,
    specs: dict[str, TriggerSpec] | None = None,
) -> list[TriggerHit]:
    """Evaluate all A-class rules for one holding/watch metrics row."""
    specs = specs or _DEFAULTS
    hits: list[TriggerHit] = []

    is_holding = m.quantity > 0 and m.avg_cost > 0

    # Stop / trailing — mutually exclusive by policy.type
    if is_holding and policy.stop_loss.enabled:
        if policy.stop_loss.type == "fixed":
            spec = specs.get("PX_STOP_LOSS")
            if spec and spec.enabled and m.holding_return <= policy.stop_loss.threshold:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={
                            "holding_return": m.holding_return,
                            "threshold": policy.stop_loss.threshold,
                            "policy": policy.stop_loss.model_dump(),
                        },
                        threshold=policy.stop_loss.threshold,
                    )
                )
        elif policy.stop_loss.type == "trailing":
            spec = specs.get("PX_TRAILING_STOP")
            trail = policy.stop_loss.trail_pct
            # drawdown_from_entry_high is negative when below high
            if spec and spec.enabled and m.drawdown_from_entry_high <= -abs(trail):
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={
                            "drawdown_from_entry_high": m.drawdown_from_entry_high,
                            "trail_pct": trail,
                            "policy": policy.stop_loss.model_dump(),
                        },
                        trail_pct=trail,
                    )
                )

    # Take profit (staged / fixed) — holdings only
    if is_holding and policy.take_profit.enabled:
        if policy.take_profit.type == "staged":
            stage = policy.next_take_profit_stage(m.holding_return)
            spec = specs.get("PX_TAKE_PROFIT")
            if stage is not None and spec and spec.enabled:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={
                            "holding_return": m.holding_return,
                            "stage": stage.model_dump(),
                            "policy": policy.take_profit.model_dump(),
                        },
                        reduce=stage.reduce,
                        stage=stage.gain,
                    )
                )
        elif policy.take_profit.type == "fixed":
            gain = policy.take_profit.fixed_gain
            spec = specs.get("PX_TAKE_PROFIT")
            if gain is not None and spec and spec.enabled and m.holding_return >= gain:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={
                            "holding_return": m.holding_return,
                            "fixed_gain": gain,
                        },
                        reduce=1.0,
                    )
                )
        elif policy.take_profit.type == "target_price":
            spec = specs.get("PX_TARGET_PRICE")
            if spec and spec.enabled and m.target_price is not None and m.last >= m.target_price:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={"last": m.last, "target_price": m.target_price},
                        target_price=m.target_price,
                    )
                )

    # Watchlist target (even when take_profit.type != target_price)
    if not is_holding and m.target_price is not None and m.last >= m.target_price:
        spec = specs.get("PX_TARGET_PRICE")
        if spec and spec.enabled:
            hits.append(
                _hit(
                    spec,
                    m,
                    evidence={"last": m.last, "target_price": m.target_price},
                    target_price=m.target_price,
                )
            )

    # Market microstructure — holdings preferred (weight > 0) but fire if holding
    if is_holding:
        if m.is_limit_up:
            spec = specs.get("PX_LIMIT_UP")
            if spec and spec.enabled:
                hits.append(_hit(spec, m, evidence={"is_limit_up": True}))
        if m.is_limit_down:
            spec = specs.get("PX_LIMIT_DOWN")
            if spec and spec.enabled:
                hits.append(_hit(spec, m, evidence={"is_limit_down": True}))
        if m.is_suspended:
            spec = specs.get("PX_SUSPENDED")
            if spec and spec.enabled:
                hits.append(_hit(spec, m, evidence={"is_suspended": True}))

        if (
            m.ma60 is not None
            and m.prev_close is not None
            and m.prev_ma60 is not None
            and m.last < m.ma60
            and m.prev_close >= m.prev_ma60
        ):
            spec = specs.get("PX_BREAK_MA60")
            if spec and spec.enabled:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={"last": m.last, "ma60": m.ma60, "prev_close": m.prev_close},
                    )
                )

        vr = m.volume_ratio_5d
        pc = m.pct_change
        if vr is not None and pc is not None and vr > 3.0 and abs(pc) > 0.05:
            spec = specs.get("PX_VOL_SPIKE")
            if spec and spec.enabled:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={"volume_ratio_5d": vr, "pct_change": pc},
                        volume_ratio_5d=vr,
                    )
                )

        # Absolute drawdown from entry high (independent of trailing stop)
        if m.drawdown_from_entry_high <= -0.12:
            spec = specs.get("PX_DRAWDOWN_FROM_HIGH")
            if spec and spec.enabled:
                hits.append(
                    _hit(
                        spec,
                        m,
                        evidence={"drawdown_from_entry_high": m.drawdown_from_entry_high},
                    )
                )

    return hits

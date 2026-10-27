"""Gate 4 §9.2 control baselines for portfolio backtests (docs/08 §4.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from quantagent.backtest.engine import BuyAndHoldConfig, BuyAndHoldEngine
from quantagent.backtest.l2_panel import RealL2TopNPanel
from quantagent.backtest.portfolio import L2TopNBacktest, L2TopNConfig, RebalanceFreq
from quantagent.evaluation.shadow.quant_signals import CSI300_L2_IC_MEANS_5Y
from quantagent.quant.features.base import entity_col
from quantagent.quant.training.holdout_guard import HoldoutGuard
from quantagent.shared.errors import QuantAgentError

if TYPE_CHECKING:
    from quantagent.execution.broker.simulated import PriceBar

# Highest |ICIR| among CSI300 5y L1-admitted factors (docs/factor-reports-csi300-5y).
DEFAULT_BEST_SINGLE_FACTOR: str = "max_ret_20d"
# Match ``shadow_baseline`` / cn_shadow.yaml ``baseline_n``.
DEFAULT_POOL_N: int = 50
DEFAULT_MC_TRIALS: int = 100
DEFAULT_MC_SEED: int = 42


@dataclass(frozen=True)
class ControlSuiteResult:
    buy_and_hold: float
    equal_weight_pool: float
    best_single_factor: float
    best_single_factor_code: str
    l2_equal: float
    strategy: float
    random_p95: float
    random_p50: float
    random_p80: float
    n_trials: int
    pool_n: int
    beats_random_p95: bool
    notes: tuple[str, ...] = ()

    def as_report_controls(self) -> dict[str, str]:
        """Strings for :func:`write_portfolio_backtest_report` ``controls=``."""
        mark = "✅ 超出随机范围" if self.beats_random_p95 else "❌ 未超随机 95 分位"
        return {
            "buy_and_hold": f"{self.buy_and_hold:+.2%}",
            "equal_weight_pool": f"{self.equal_weight_pool:+.2%} (n={self.pool_n})",
            "best_single_factor": (
                f"{self.best_single_factor:+.2%} (`{self.best_single_factor_code}`)"
            ),
            "l2_equal": f"{self.l2_equal:+.2%}",
            "random_p95": f"{self.random_p95:+.2%}   {mark}",
        }


def pick_best_single_factor(
    ic_means: dict[str, float],
    codes: list[str] | tuple[str, ...],
    *,
    preferred: str | None = DEFAULT_BEST_SINGLE_FACTOR,
) -> str:
    """Choose strongest admitted factor by |IC mean|; prefer documented ICIR leader."""
    available = [c for c in codes if c in ic_means]
    if not available:
        raise QuantAgentError("no factor codes with IC means for best-single control")
    if preferred is not None and preferred in available:
        return preferred
    return max(available, key=lambda c: abs(float(ic_means[c])))


def scores_from_single_factor(
    panel: pl.DataFrame,
    code: str,
    ic_mean: float,
    *,
    start: date,
    end: date,
    membership: dict[date, frozenset[str]] | None,
) -> dict[date, dict[str, float]]:
    """Sign-align one rank column into Top-N scores (higher = expected better)."""
    if code not in panel.columns:
        raise QuantAgentError(f"factor column missing for control: {code}")
    key = "symbol" if "symbol" in panel.columns else entity_col(panel)
    aligned = (
        (1.0 - pl.col(code)) if ic_mean < 0 else pl.col(code)
    ).alias("_score")
    rows = (
        panel.filter(
            (pl.col("trade_date") >= start)
            & (pl.col("trade_date") <= end)
            & pl.col(code).is_not_null()
        )
        .with_columns(aligned)
        .select(["trade_date", key, "_score"])
    )
    scores: dict[date, dict[str, float]] = {}
    for row in rows.iter_rows(named=True):
        day = row["trade_date"]
        if not isinstance(day, date):
            day = date.fromisoformat(str(day))
        sym = str(row[key])
        if membership is not None:
            members = membership.get(day)
            if members is not None and sym not in members:
                continue
        scores.setdefault(day, {})[sym] = float(row["_score"])
    return scores


def equal_pool_scores(
    membership: dict[date, frozenset[str]],
    *,
    pool_n: int = DEFAULT_POOL_N,
) -> dict[date, dict[str, float]]:
    """Deterministic equal-weight pool: first ``pool_n`` symbols sorted by ticker."""
    if pool_n < 1:
        raise QuantAgentError("pool_n must be >= 1")
    out: dict[date, dict[str, float]] = {}
    for day, members in membership.items():
        picks = sorted(members)[:pool_n]
        if picks:
            out[day] = {sym: 1.0 for sym in picks}
    return out


def random_topn_scores(
    membership: dict[date, frozenset[str]],
    *,
    top_n: int,
    seed: int,
) -> dict[date, dict[str, float]]:
    """Per-day random Top-N from membership (stable under ``seed``)."""
    import random

    rng = random.Random(seed)
    out: dict[date, dict[str, float]] = {}
    for day in sorted(membership):
        members = list(membership[day])
        if not members:
            continue
        k = min(top_n, len(members))
        picks = rng.sample(members, k=k)
        # Distinct scores so _top_n order is stable / matches sample order.
        out[day] = {sym: float(k - i) for i, sym in enumerate(picks)}
    return out


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        raise QuantAgentError("empty sample for percentile")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    w = pos - lo
    return sorted_vals[lo] * (1.0 - w) + sorted_vals[hi] * w


def index_bars_by_date(bars: list[PriceBar]) -> dict[date, list[PriceBar]]:
    """Pre-bucket bars once for repeated control backtests."""
    by_date: dict[date, list[PriceBar]] = {}
    for bar in bars:
        by_date.setdefault(bar.trade_date, []).append(bar)
    return by_date


async def _run_topn(
    *,
    bars_by_date: dict[date, list[PriceBar]],
    scores: dict[date, dict[str, float]],
    start: date,
    end: date,
    top_n: int,
    rebalance: RebalanceFreq,
    strategy: str,
    guard: HoldoutGuard | None,
) -> float:
    cfg = L2TopNConfig(
        start=start,
        end=end,
        top_n=top_n,
        strategy=strategy,
        rebalance=rebalance,
    )
    result = await L2TopNBacktest(guard=guard).run(
        cfg, scores=scores, bars_by_date=bars_by_date
    )
    return float(result.total_return)


async def run_control_suite(
    panel: RealL2TopNPanel,
    *,
    strategy_return: float,
    top_n: int = 15,
    rebalance: RebalanceFreq = "weekly",
    pool_n: int = DEFAULT_POOL_N,
    mc_trials: int = DEFAULT_MC_TRIALS,
    mc_seed: int = DEFAULT_MC_SEED,
    benchmark_symbol: str = "000300.SH",
    guard: HoldoutGuard | None = None,
    best_factor: str | None = None,
) -> ControlSuiteResult:
    """Run Buy&Hold + equal pool + best single + Monte Carlo vs ``strategy_return``."""
    if panel.factor_panel is None or not panel.factor_codes:
        raise QuantAgentError("panel missing factor_panel/factor_codes for controls")
    membership = panel.membership
    if not membership:
        # Fall back to score keys as the tradable set each day.
        membership = {
            d: frozenset(syms) for d, syms in panel.scores.items() if syms
        }
    means = dict(panel.ic_means or CSI300_L2_IC_MEANS_5Y)
    code = pick_best_single_factor(
        means, panel.factor_codes, preferred=best_factor or DEFAULT_BEST_SINGLE_FACTOR
    )
    ic = float(means.get(code, 0.0))

    print(f"controls: Buy&Hold {benchmark_symbol}", flush=True)
    bh = BuyAndHoldEngine().run(
        BuyAndHoldConfig(
            symbol=benchmark_symbol,
            start=panel.start,
            end=panel.end,
            apply_constraints=False,
            probe_t1=False,
        )
    )
    bh_ret = float(bh.metrics.total_return)

    bars_by_date = index_bars_by_date(panel.bars)

    print(f"controls: equal-weight pool n={pool_n}", flush=True)
    pool_scores = equal_pool_scores(membership, pool_n=pool_n)
    pool_ret = await _run_topn(
        bars_by_date=bars_by_date,
        scores=pool_scores,
        start=panel.start,
        end=panel.end,
        top_n=pool_n,
        rebalance=rebalance,
        strategy="control_equal_pool",
        guard=guard,
    )

    print(f"controls: best single factor `{code}` (ic_mean={ic:+.4f})", flush=True)
    single_scores = scores_from_single_factor(
        panel.factor_panel,
        code,
        ic,
        start=panel.start,
        end=panel.end,
        membership=membership,
    )
    single_ret = await _run_topn(
        bars_by_date=bars_by_date,
        scores=single_scores,
        start=panel.start,
        end=panel.end,
        top_n=top_n,
        rebalance=rebalance,
        strategy=f"control_single_{code}",
        guard=guard,
    )

    print(f"controls: Monte Carlo random Top-{top_n} x{mc_trials}", flush=True)
    random_rets: list[float] = []
    for i in range(mc_trials):
        rnd_scores = random_topn_scores(
            membership, top_n=top_n, seed=mc_seed + i
        )
        ret = await _run_topn(
            bars_by_date=bars_by_date,
            scores=rnd_scores,
            start=panel.start,
            end=panel.end,
            top_n=top_n,
            rebalance=rebalance,
            strategy=f"control_random_{i}",
            guard=None,  # holdout already checked on strategy run
        )
        random_rets.append(ret)
        if (i + 1) % 10 == 0 or i == 0:
            print(
                f"controls: MC {i + 1}/{mc_trials} last={ret:+.2%}",
                flush=True,
            )
    ordered = sorted(random_rets)
    p50 = _percentile(ordered, 0.50)
    p80 = _percentile(ordered, 0.80)
    p95 = _percentile(ordered, 0.95)
    beats = strategy_return > p95

    return ControlSuiteResult(
        buy_and_hold=bh_ret,
        equal_weight_pool=pool_ret,
        best_single_factor=single_ret,
        best_single_factor_code=code,
        l2_equal=strategy_return,
        strategy=strategy_return,
        random_p95=p95,
        random_p50=p50,
        random_p80=p80,
        n_trials=mc_trials,
        pool_n=pool_n,
        beats_random_p95=beats,
        notes=(
            f"equal pool n={pool_n} (shadow_baseline-aligned)",
            f"best single=`{code}` by L1 |ICIR| leader among admitted",
            f"MC trials={mc_trials} seed={mc_seed} "
            f"p50={p50:+.2%} p80={p80:+.2%} p95={p95:+.2%}",
        ),
    )

"""Shadow Portfolio engine: baseline + factor + quant + agent + fused (+ norisk)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.core.repository.shadow_day import ShadowDayStore
from quantagent.evaluation.journal.store import AppendOnlyJournal
from quantagent.evaluation.shadow.fusion_signals import (
    apply_risk_filter,
    fuse_quant_agent_scores,
    top_n_symbols,
)
from quantagent.evaluation.shadow.types import ShadowConfig, ShadowDayRecord, ShadowPortfolioId
from quantagent.execution.broker.simulated import PriceBar, SimulatedBroker
from quantagent.execution.rebalance import rebalance_equal_weight

_PORTFOLIO_IDS: tuple[ShadowPortfolioId, ...] = (
    "shadow_baseline",
    "shadow_factor",
    "shadow_quant",
    "shadow_agent",
    "shadow_fused",
    "shadow_fused_norisk",
)


class ShadowPortfolioState:
    def __init__(
        self,
        portfolio_id: ShadowPortfolioId,
        *,
        cfg: ShadowConfig,
        market: MarketConfig,
        journal: AppendOnlyJournal,
    ) -> None:
        self.portfolio_id = portfolio_id
        self.cfg = cfg
        self.market = market
        self.journal = journal
        self.broker = SimulatedBroker(market, cash=cfg.initial_cash)
        self.peak_nav = cfg.initial_cash
        self.prev_nav = cfg.initial_cash
        self.initial_nav = cfg.initial_cash
        self.max_drawdown = 0.0

    def status_row(self, *, as_of: date) -> ShadowDayRecord | None:
        _ = as_of
        return None


class ShadowEngine:
    """Runs the six Gate-4 shadow portfolios (per-portfolio idempotent).

    Newly added portfolios (e.g. ``shadow_fused``) can catch up on past
    ``as_of`` dates without duplicating peers' journal rows.
    """

    def __init__(
        self,
        store_dir: Path | str,
        *,
        cfg: ShadowConfig | None = None,
        market: MarketConfig | None = None,
        code_version: str = "dev",
    ) -> None:
        self.cfg = cfg or ShadowConfig()
        self.market = market or load_market_config("CN")
        self.code_version = code_version
        root = Path(store_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._db_store = ShadowDayStore.try_connect()
        self._states: dict[ShadowPortfolioId, ShadowPortfolioState] = {
            pid: ShadowPortfolioState(
                pid,
                cfg=self.cfg,
                market=self.market,
                journal=AppendOnlyJournal(root / f"{pid}.jsonl"),
            )
            for pid in _PORTFOLIO_IDS
        }

    def load_history_metrics(self) -> dict[ShadowPortfolioId, dict[str, float]]:
        out: dict[ShadowPortfolioId, dict[str, float]] = {}
        for pid, st in self._states.items():
            rows = st.journal.read_all()
            if not rows:
                out[pid] = {
                    "ret_1d": 0.0,
                    "ret_cum": 0.0,
                    "max_drawdown": 0.0,
                    "n_positions": 0,
                    "nav": st.initial_nav,
                }
                continue
            last = rows[-1]
            out[pid] = {
                "ret_1d": float(last["ret_1d"]),
                "ret_cum": float(last["ret_cum"]),
                "max_drawdown": float(last["max_drawdown"]),
                "n_positions": int(last["n_positions"]),
                "nav": float(last["nav"]),
            }
            st.prev_nav = float(last["nav"])
            st.peak_nav = max(st.peak_nav, float(last["nav"]))
            st.max_drawdown = float(last["max_drawdown"])
        return out

    async def step(
        self,
        *,
        as_of: date,
        run_id: str,
        bars: list[PriceBar],
        baseline_symbols: list[str],
        factor_scores: dict[str, float],
        agent_scores: dict[str, float] | None = None,
        quant_scores: dict[str, float] | None = None,
    ) -> list[ShadowDayRecord]:
        """Rebalance shadows for one day and append journal rows.

        Per-portfolio idempotent: portfolios that already have ``as_of`` return
        the cached row (with ``idempotent_skip``) without re-trading.
        """
        agent_scores = agent_scores or {}
        quant_scores = quant_scores or {}
        ranked_factor = sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)
        factor_syms = [s for s, _ in ranked_factor[: self.cfg.factor_top_n]]
        ranked_quant = sorted(quant_scores.items(), key=lambda x: x[1], reverse=True)
        quant_syms = [s for s, _ in ranked_quant[: self.cfg.quant_top_n]]
        ranked_agent = sorted(agent_scores.items(), key=lambda x: x[1], reverse=True)
        agent_syms = [s for s, _ in ranked_agent[: self.cfg.agent_top_n]]

        fused_scores = fuse_quant_agent_scores(quant_scores, agent_scores)
        fused_raw = top_n_symbols(fused_scores, self.cfg.fused_top_n)
        fused_st = self._states.get("shadow_fused")
        fused_nav = fused_st.prev_nav if fused_st is not None else self.cfg.initial_cash
        fused_risk_syms, fused_risk_notes = apply_risk_filter(
            fused_raw,
            bars=bars,
            as_of=as_of,
            total_value=fused_nav if fused_nav > 0 else self.cfg.initial_cash,
            cash=max(fused_nav * 0.10, 0.0),
        )

        targets: dict[ShadowPortfolioId, list[str]] = {
            "shadow_baseline": baseline_symbols[: self.cfg.baseline_n],
            "shadow_factor": factor_syms,
            "shadow_quant": quant_syms,
            "shadow_agent": agent_syms,
            "shadow_fused": fused_risk_syms,
            "shadow_fused_norisk": fused_raw,
        }
        extra_notes: dict[ShadowPortfolioId, list[str]] = {
            "shadow_baseline": [],
            "shadow_factor": [],
            "shadow_quant": (["no_quant_scores"] if not quant_syms else []),
            "shadow_agent": (["no_agent_scores"] if not agent_syms else []),
            "shadow_fused": (
                (["no_fused_scores"] if not fused_raw else [])
                + fused_risk_notes
            ),
            "shadow_fused_norisk": (
                ["no_fused_scores"] if not fused_raw else ["risk_skipped"]
            ),
        }

        records: list[ShadowDayRecord] = []
        for pid, symbols in targets.items():
            st = self._states.get(pid)
            if st is None:
                continue
            cached = self._cached_portfolio_day(st, as_of)
            if cached is not None:
                records.append(cached)
                continue
            notes = list(extra_notes.get(pid, []))
            rec = await self._step_one(
                st,
                as_of=as_of,
                run_id=run_id,
                bars=bars,
                symbols=symbols,
                notes=notes,
            )
            records.append(rec)
        return records

    def _cached_portfolio_day(
        self, st: ShadowPortfolioState, as_of: date
    ) -> ShadowDayRecord | None:
        if not st.journal.has_as_of(as_of):
            return None
        raw = st.journal.latest_for_as_of(as_of)
        if raw is None:
            return None
        raw = {
            **raw,
            "portfolio": st.portfolio_id,
            "notes": list(raw.get("notes") or []) + ["idempotent_skip"],
        }
        return ShadowDayRecord.model_validate(raw)

    async def _step_one(
        self,
        st: ShadowPortfolioState,
        *,
        as_of: date,
        run_id: str,
        bars: list[PriceBar],
        symbols: list[str],
        notes: list[str],
    ) -> ShadowDayRecord:
        st.broker.set_bars(bars, trade_date=as_of)
        st.broker.roll_day()
        equity_before = st.broker.mark_to_market()
        await self._rebalance(st, symbols=symbols, as_of=as_of, run_id=run_id)
        nav = st.broker.mark_to_market()
        ret_1d = (nav / st.prev_nav - 1.0) if st.prev_nav > 0 else 0.0
        ret_cum = nav / st.initial_nav - 1.0
        st.peak_nav = max(st.peak_nav, nav)
        dd = nav / st.peak_nav - 1.0 if st.peak_nav > 0 else 0.0
        st.max_drawdown = min(st.max_drawdown, dd)
        st.prev_nav = nav

        positions = await st.broker.get_positions()
        weights = {p.symbol: (p.market_value / nav if nav > 0 else 0.0) for p in positions}
        day_unfilled = [
            {
                "symbol": u.symbol,
                "side": u.side,
                "quantity": u.quantity,
                "reason": u.reason,
            }
            for u in st.broker.unfilled
            if u.trade_date == as_of
        ]
        day_notes = list(notes)
        if equity_before <= 0:
            day_notes.append("zero_equity")
        acct = await st.broker.get_account()
        rec = ShadowDayRecord(
            portfolio=st.portfolio_id,
            as_of=as_of,
            run_id=run_id,
            strategy_version=self.cfg.strategy_version,
            code_version=self.code_version,
            nav=nav,
            cash=acct.cash,
            ret_1d=ret_1d,
            ret_cum=ret_cum,
            max_drawdown=st.max_drawdown,
            n_positions=len(positions),
            weights=weights,
            unfilled=day_unfilled,
            notes=day_notes,
        )
        st.journal.append(rec)
        if self._db_store is not None:
            self._db_store.append(rec)
        return rec

    async def _rebalance(
        self,
        st: ShadowPortfolioState,
        *,
        symbols: list[str],
        as_of: date,
        run_id: str,
    ) -> None:
        await rebalance_equal_weight(
            st.broker,
            self.market,
            symbols,
            as_of=as_of,
            run_id=f"{run_id}-{st.portfolio_id}",
        )

    def latest_status(self) -> list[dict[str, float | int | str]]:
        rows: list[dict[str, float | int | str]] = []
        for pid, st in self._states.items():
            hist = st.journal.read_all()
            if not hist:
                rows.append(
                    {
                        "portfolio": pid,
                        "ret_1d": 0.0,
                        "ret_cum": 0.0,
                        "max_drawdown": 0.0,
                        "n_positions": 0,
                    }
                )
            else:
                last = hist[-1]
                rows.append(
                    {
                        "portfolio": pid,
                        "ret_1d": float(last["ret_1d"]),
                        "ret_cum": float(last["ret_cum"]),
                        "max_drawdown": float(last["max_drawdown"]),
                        "n_positions": int(last["n_positions"]),
                    }
                )
        return rows

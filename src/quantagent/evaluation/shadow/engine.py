"""Shadow Portfolio engine: equal-weight baseline + factor Top-N via SimulatedBroker."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from quantagent.core.market import MarketConfig, load_market_config
from quantagent.decision.portfolio.lots import floor_to_lot
from quantagent.evaluation.journal.store import AppendOnlyJournal
from quantagent.evaluation.shadow.types import ShadowConfig, ShadowDayRecord, ShadowPortfolioId
from quantagent.execution.broker.base import OrderRequest
from quantagent.execution.broker.simulated import PriceBar, SimulatedBroker
from quantagent.execution.orders.idempotency import make_client_order_id


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
    """Runs ``shadow_baseline`` and ``shadow_factor``; append-only daily records."""

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
        self._states: dict[ShadowPortfolioId, ShadowPortfolioState] = {
            "shadow_baseline": ShadowPortfolioState(
                "shadow_baseline",
                cfg=self.cfg,
                market=self.market,
                journal=AppendOnlyJournal(root / "shadow_baseline.jsonl"),
            ),
            "shadow_factor": ShadowPortfolioState(
                "shadow_factor",
                cfg=self.cfg,
                market=self.market,
                journal=AppendOnlyJournal(root / "shadow_factor.jsonl"),
            ),
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
    ) -> list[ShadowDayRecord]:
        """Rebalance both shadows for one day and append journal rows."""
        records: list[ShadowDayRecord] = []
        # Factor Top-N
        ranked = sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)
        factor_syms = [s for s, _ in ranked[: self.cfg.factor_top_n]]

        targets: dict[ShadowPortfolioId, list[str]] = {
            "shadow_baseline": baseline_symbols[: self.cfg.baseline_n],
            "shadow_factor": factor_syms,
        }

        for pid, symbols in targets.items():
            st = self._states[pid]
            st.broker.set_bars(bars, trade_date=as_of)
            st.broker.roll_day()
            # Mark before rebalance to get start-of-day equity for sizing
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
            notes: list[str] = []
            if equity_before <= 0:
                notes.append("zero_equity")
            acct = await st.broker.get_account()
            rec = ShadowDayRecord(
                portfolio=pid,
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
                notes=notes,
            )
            st.journal.append(rec)
            records.append(rec)
        return records

    async def _rebalance(
        self,
        st: ShadowPortfolioState,
        *,
        symbols: list[str],
        as_of: date,
        run_id: str,
    ) -> None:
        if not symbols:
            return
        equity = st.broker.mark_to_market()
        if equity <= 0:
            return
        target_w = 1.0 / len(symbols)
        positions = {p.symbol: p for p in await st.broker.get_positions()}
        oid_run = f"{run_id}-{st.portfolio_id}-{as_of.isoformat()}"
        seq = 0
        # Sell names not in target
        for sym, pos in positions.items():
            if sym in symbols:
                continue
            sellable = pos.sellable_qty if pos.sellable_qty > 0 else 0.0
            if sellable <= 0:
                continue
            qty = floor_to_lot(sellable, self.market.lot_size("main")) or sellable
            # allow odd-lot full exit
            if pos.quantity <= self.market.min_lot_buy:
                qty = pos.quantity
            seq += 1
            await st.broker.place_order(
                OrderRequest(
                    client_order_id=make_client_order_id(oid_run, sym, "sell", seq),
                    symbol=sym,
                    side="sell",
                    quantity=float(qty),
                )
            )
        equity = st.broker.mark_to_market()
        positions = {p.symbol: p for p in await st.broker.get_positions()}
        for sym in symbols:
            bar = st.broker._bars.get(sym)  # noqa: SLF001 — MVP mark/price access
            if bar is None or bar.close <= 0:
                continue
            target_notional = target_w * equity
            current = positions.get(sym)
            current_notional = current.market_value if current else 0.0
            delta = target_notional - current_notional
            if abs(delta) < bar.close * self.market.lot_size("main") * 0.5:
                continue
            if delta > 0:
                qty = floor_to_lot(delta / bar.close, self.market.lot_size("main"))
                if qty <= 0:
                    continue
                seq += 1
                await st.broker.place_order(
                    OrderRequest(
                        client_order_id=make_client_order_id(oid_run, sym, "buy", seq),
                        symbol=sym,
                        side="buy",
                        quantity=float(qty),
                    )
                )
            else:
                if current is None or current.sellable_qty <= 0:
                    continue
                qty = floor_to_lot(abs(delta) / bar.close, self.market.lot_size("main"))
                qty = min(qty, current.sellable_qty)
                if qty <= 0:
                    continue
                seq += 1
                await st.broker.place_order(
                    OrderRequest(
                        client_order_id=make_client_order_id(oid_run, sym, "sell", seq),
                        symbol=sym,
                        side="sell",
                        quantity=float(qty),
                    )
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

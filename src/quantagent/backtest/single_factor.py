"""Thin single-factor backtest: IC long-short sign consistency check."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from quantagent.quant.evaluation.runner import evaluate_factor, synthetic_mvp_eval_panel


class SingleFactorBacktestResult(BaseModel):
    factor_code: str
    ic_mean: float
    long_short_return: float
    ic_sign: int
    ls_sign: int
    signs_match: bool
    admission_pass: bool
    admission_notes: list[str] = Field(default_factory=list)
    summary: str = ""


@dataclass(frozen=True)
class SingleFactorBacktestConfig:
    factor_code: str = "mom_20d"
    horizon: int = 5
    n_quantiles: int = 5


class SingleFactorBacktest:
    """Evaluate one MVP factor on synthetic panel; compare IC vs LS direction."""

    def run(self, cfg: SingleFactorBacktestConfig) -> SingleFactorBacktestResult:
        panel = synthetic_mvp_eval_panel()
        result = evaluate_factor(
            panel,
            factor_code=cfg.factor_code,
            horizon=cfg.horizon,
            n_quantiles=cfg.n_quantiles,
        )
        ic_sign = 1 if result.ic_mean > 0 else (-1 if result.ic_mean < 0 else 0)
        ls_sign = 1 if result.long_short_return > 0 else (-1 if result.long_short_return < 0 else 0)
        signs_match = ic_sign == ls_sign or ic_sign == 0 or ls_sign == 0
        summary = (
            f"factor={cfg.factor_code} ic_mean={result.ic_mean:+.4f} "
            f"long_short={result.long_short_return:+.4%} "
            f"ic_sign={'+' if ic_sign >= 0 else '-'}{abs(ic_sign)} "
            f"ls_sign={'+' if ls_sign >= 0 else '-'}{abs(ls_sign)} "
            f"consistent={'yes' if signs_match else 'NO'}"
        )
        return SingleFactorBacktestResult(
            factor_code=cfg.factor_code,
            ic_mean=result.ic_mean,
            long_short_return=result.long_short_return,
            ic_sign=ic_sign,
            ls_sign=ls_sign,
            signs_match=signs_match,
            admission_pass=result.admission_pass,
            admission_notes=result.admission_notes,
            summary=summary,
        )

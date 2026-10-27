"""Unit tests for SignalFusion."""

from __future__ import annotations

from quantagent.decision.fusion import FusionConfig, SignalFusion


def test_fuse_rank_renormalize_two_signals() -> None:
    fusion = SignalFusion()
    out = fusion.fuse(
        {
            "quant": {"A": 0.9, "B": 0.1, "C": 0.5},
            "stock": {"A": 0.2, "B": 0.8, "C": 0.5},
        },
        FusionConfig(),
    )
    assert set(out) == {"A", "B", "C"}
    # Rank: quant A=1,B=0,C=0.5; stock A=0,B=1,C=0.5 → equal weights → A=B=C=0.5
    assert abs(out["A"].final_score - 0.5) < 1e-9
    assert abs(out["B"].final_score - 0.5) < 1e-9
    assert abs(out["C"].final_score - 0.5) < 1e-9
    assert set(out["A"].weights_used) == {"quant", "stock"}
    assert abs(sum(out["A"].weights_used.values()) - 1.0) < 1e-9


def test_fuse_missing_signal_renormalizes() -> None:
    fusion = SignalFusion()
    out = fusion.fuse({"quant": {"A": 1.0, "B": 0.0}}, FusionConfig())
    assert set(out) == {"A", "B"}
    assert out["A"].final_score > out["B"].final_score
    assert out["A"].weights_used == {"quant": 1.0}
    assert "stock" in out["A"].missing


def test_fuse_empty_signals() -> None:
    assert SignalFusion().fuse({}) == {}

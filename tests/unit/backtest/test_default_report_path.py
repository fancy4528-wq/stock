"""Default Gate 4 L2 report paths encode cadence."""

from __future__ import annotations

from pathlib import Path

from quantagent.backtest.report import default_l2_report_path


def test_default_l2_report_path_monthly_is_primary() -> None:
    assert default_l2_report_path("csi300", "monthly") == Path(
        "docs/backtest-reports/l2_equal_topn-csi300-5y-monthly.md"
    )


def test_default_l2_report_path_weekly_keeps_to30_contrast() -> None:
    assert default_l2_report_path("csi300", "weekly") == Path(
        "docs/backtest-reports/l2_equal_topn-csi300-5y-weekly-to30.md"
    )


def test_default_l2_report_path_other_freq_suffix() -> None:
    assert default_l2_report_path("csi300", "daily") == Path(
        "docs/backtest-reports/l2_equal_topn-csi300-5y-daily.md"
    )

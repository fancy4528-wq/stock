"""Unit tests for unit conversion helpers."""

import pytest

from quantagent.data.normalizers.units import lots_to_shares, percent_to_ratio


def test_lots_to_shares() -> None:
    assert lots_to_shares(1) == 100
    assert lots_to_shares(1052468) == 105_246_800


def test_percent_to_ratio() -> None:
    assert percent_to_ratio(15) == 0.15
    assert percent_to_ratio(0.38) == pytest.approx(0.0038)

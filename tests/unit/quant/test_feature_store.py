"""Feature store: year partitions, as-of reads, one code version."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from quantagent.quant.features.base import FactorInput
from quantagent.quant.store import (
    FeatureStore,
    FeatureStoreError,
    FeatureVersionError,
    append_factors,
    rebuild_factors,
)
from quantagent.quant.store.feature_store import bundle_code_version


def _frame(rows: list[tuple[int, date, float]], *, version: str = "v1") -> tuple[pl.DataFrame, dict[str, str]]:
    versions = {"mom_20d": version}
    frame = pl.DataFrame(
        {
            "security_id": [row[0] for row in rows],
            "trade_date": [row[1] for row in rows],
            "mom_20d": [row[2] for row in rows],
        }
    ).with_columns(pl.lit(bundle_code_version(versions)).alias("code_version"))
    return frame, versions


def test_rebuild_partitions_by_year_and_load_respects_as_of(tmp_path) -> None:
    store = FeatureStore(tmp_path)
    frame, versions = _frame(
        [
            (1, date(2020, 12, 31), 0.1),
            (2, date(2020, 12, 31), 0.2),
            (1, date(2021, 1, 4), 0.3),
        ]
    )
    store.rebuild("CN", frame, versions=versions)

    assert (tmp_path / "cn" / "panel" / "year=2020" / "part-0.parquet").is_file()
    assert (tmp_path / "cn" / "panel" / "year=2021" / "part-0.parquet").is_file()
    assert store.versions("cn") == {"mom_20d": "v1"}

    loaded = store.load_panel(
        "cn",
        ["mom_20d"],
        date(2020, 12, 1),
        date(2021, 1, 4),
        as_of=date(2021, 1, 4),
    )
    assert loaded.height == 3
    assert loaded.columns == ["security_id", "trade_date", "mom_20d"]

    clipped = store.load_panel(
        "cn",
        ["mom_20d"],
        date(2020, 1, 1),
        date(2020, 12, 31),
        as_of=date(2020, 12, 31),
    )
    assert clipped.height == 2
    with pytest.raises(FeatureStoreError, match="as_of"):
        store.load_panel(
            "cn",
            ["mom_20d"],
            date(2020, 1, 1),
            date(2021, 1, 4),
            as_of=date(2020, 12, 31),
        )


def test_append_is_idempotent_and_rejects_a_new_version(tmp_path) -> None:
    store = FeatureStore(tmp_path)
    first, versions = _frame([(1, date(2021, 1, 4), 0.3)])
    store.append("cn", first, versions=versions)
    again, _ = _frame([(1, date(2021, 1, 4), 0.9)])
    store.append("cn", again, versions=versions)
    loaded = store.load_panel(
        "cn", ["mom_20d"], date(2021, 1, 4), date(2021, 1, 4), as_of=date(2021, 1, 4)
    )
    assert loaded.height == 1
    assert loaded["mom_20d"].item() == pytest.approx(0.9)

    nxt, _ = _frame([(1, date(2021, 1, 5), 0.4), (2, date(2021, 1, 5), -0.1)])
    store.append("cn", nxt, versions=versions)
    both = store.load_panel(
        "cn", ["mom_20d"], date(2021, 1, 4), date(2021, 1, 5), as_of=date(2021, 1, 5)
    )
    assert both.height == 3

    prior, _ = _frame([(1, date(2020, 12, 31), 0.2)])
    store.append("cn", prior, versions=versions)
    changed, changed_versions = _frame([(1, date(2021, 1, 6), 1.0)], version="v2")
    with pytest.raises(FeatureVersionError, match="rebuild"):
        store.append("cn", changed, versions=changed_versions)
    assert store.versions("cn") == {"mom_20d": "v1"}
    untouched = store.load_panel(
        "cn", ["mom_20d"], date(2021, 1, 1), date(2021, 12, 31), as_of=date(2021, 12, 31)
    )
    assert untouched["trade_date"].max() == date(2021, 1, 5)

    store.rebuild("cn", changed, versions=changed_versions)
    assert store.versions("cn") == {"mom_20d": "v2"}
    assert (tmp_path / "cn" / "panel" / "year=2021" / "part-0.parquet").is_file()
    assert not (tmp_path / "cn" / "panel" / "year=2020").exists()
    rebuilt = store.load_panel(
        "cn", ["mom_20d"], date(2021, 1, 1), date(2021, 1, 6), as_of=date(2021, 1, 6)
    )
    assert rebuilt.height == 1
    assert rebuilt["mom_20d"].item() == pytest.approx(1.0)


def test_append_factors_writes_only_the_as_of_day(tmp_path) -> None:
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(30)]
    dates = [d for d in dates if d.weekday() < 5][:25]
    closes = [100.0 * (1.01**i) for i in range(len(dates))]
    prices = pl.DataFrame(
        {
            "security_id": [1] * len(dates),
            "trade_date": dates,
            "close": closes,
        }
    )
    store = FeatureStore(tmp_path)
    first_as_of = dates[-2]
    append_factors(
        store,
        FactorInput(prices=prices, as_of=first_as_of),
        market="cn",
        codes=["mom_20d"],
    )
    day_one = store.load_panel(
        "cn", ["mom_20d"], dates[0], first_as_of, as_of=first_as_of
    )
    assert day_one.height == 1
    assert day_one["trade_date"].item() == first_as_of
    assert day_one["mom_20d"].item() == pytest.approx(closes[-2] / closes[-2 - 20] - 1.0)

    append_factors(
        store,
        FactorInput(prices=prices, as_of=dates[-1]),
        market="cn",
        codes=["mom_20d"],
    )
    both = store.load_panel("cn", ["mom_20d"], dates[0], dates[-1], as_of=dates[-1])
    assert both.height == 2
    assert both["trade_date"].to_list() == [first_as_of, dates[-1]]


def test_rebuild_factors_drops_prices_after_as_of(tmp_path) -> None:
    dates = [date(2024, 6, 3) + timedelta(days=i) for i in range(40)]
    dates = [d for d in dates if d.weekday() < 5][:25]
    prices = pl.DataFrame(
        {
            "security_id": [7] * len(dates),
            "trade_date": dates,
            "close": [50.0 + i for i in range(len(dates))],
        }
    )
    store = FeatureStore(tmp_path)
    as_of = dates[21]
    rebuild_factors(
        store,
        FactorInput(prices=prices, as_of=as_of),
        market="cn",
        codes=["rev_5d"],
    )
    loaded = store.load_panel("cn", ["rev_5d"], dates[0], dates[-1], as_of=dates[-1])
    assert loaded["trade_date"].max() == as_of
    assert dates[-1] not in loaded["trade_date"].to_list()

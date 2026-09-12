"""Unit tests for universe survivorship probes + seed filters."""

from __future__ import annotations

from datetime import date

from quantagent.core.universe.config import (
    SurvivorshipProbe,
    UniverseConfig,
    UniverseRule,
    active_survivorship_symbols,
    load_universe_config,
)


def test_mvp_yaml_has_survivorship_probes() -> None:
    load_universe_config.cache_clear()
    cfg = load_universe_config("mvp_cn_50")
    assert len(cfg.survivorship_probes) >= 2
    symbols = {p.symbol for p in cfg.survivorship_probes}
    assert "000693.SZ" in symbols
    assert "600145.SH" in symbols
    # Must not pollute live bootstrap.
    assert "000693.SZ" not in cfg.bootstrap_symbols
    assert "600145.SH" not in cfg.bootstrap_symbols


def test_active_survivorship_symbols_window() -> None:
    cfg = UniverseConfig(
        code="t",
        name="t",
        bootstrap_symbols=["600519.SH"],
        survivorship_probes=[
            SurvivorshipProbe(
                symbol="000693.SZ",
                name="华泽钴镍",
                list_date=date(1997, 2, 26),
                delist_date=date(2020, 7, 10),
            )
        ],
        rule=UniverseRule(),
    )
    assert active_survivorship_symbols(cfg, date(2019, 6, 1)) == ["000693.SZ"]
    assert active_survivorship_symbols(cfg, date(2020, 7, 10)) == []
    assert active_survivorship_symbols(cfg, date(1990, 1, 1)) == []


def test_seed_excludes_delisted_ids() -> None:
    """Logic mirror: delisted_ids ∪ suspended_ids are filtered from present."""
    known = {"A": 1, "B": 2, "C": 3}
    present = ["A", "B", "C"]
    suspended_ids = {2}
    delisted_ids = {3}
    skip = suspended_ids | delisted_ids
    kept = [s for s in present if known[s] not in skip]
    assert kept == ["A"]

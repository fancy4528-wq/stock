"""Universe YAML loader + snapshot seeding."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.engine import Engine

from quantagent.shared.config import get_settings
from quantagent.shared.errors import ConfigError, QuantAgentError


class UniverseRule(BaseModel):
    base: str | None = None
    note: str | None = None
    filters: list[str] = Field(default_factory=list)
    industry_coverage: dict[str, Any] = Field(default_factory=dict)
    select: dict[str, Any] = Field(default_factory=dict)
    snapshot_frequency: str | None = None


class SurvivorshipProbe(BaseModel):
    """Historically delisted name for survivorship / PIT_007 evidence.

    Not part of live ``bootstrap_symbols``; only seeded into snapshots with
    ``as_of < delist_date``.
    """

    symbol: str
    name: str
    list_date: date
    delist_date: date
    board: str = "main"
    raw_symbol: str | None = None


class UniverseConfig(BaseModel):
    code: str
    name: str
    market: str = "CN"
    rule: UniverseRule = Field(default_factory=UniverseRule)
    bootstrap_symbols: list[str] = Field(default_factory=list)
    survivorship_probes: list[SurvivorshipProbe] = Field(default_factory=list)


class UniverseSeedError(QuantAgentError):
    """Universe seed / snapshot failure."""


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    raise ConfigError("Cannot locate repo root containing config/")


def universe_config_path(code: str, *, config_dir: Path | None = None) -> Path:
    root = config_dir or (_repo_root() / "config" / "universe")
    # mvp_cn_50 → mvp_cn.yaml
    stem = code.removesuffix("_50") if code.endswith("_50") else code
    candidates = [
        root / f"{stem}.yaml",
        root / f"{code}.yaml",
        root / "mvp_cn.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise ConfigError(f"Universe config not found for {code!r} under {root}")


@lru_cache
def load_universe_config(code: str = "mvp_cn_50") -> UniverseConfig:
    path = universe_config_path(code)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid universe config YAML: {path}")
    cfg = UniverseConfig.model_validate(raw)
    if cfg.code != code and code not in {cfg.code, "mvp_cn"}:
        # Allow loading mvp_cn.yaml via alias mvp_cn_50
        if not (cfg.code == "mvp_cn_50" and code in {"mvp_cn_50", "mvp_cn"}):
            pass
    return cfg


def active_survivorship_symbols(cfg: UniverseConfig, as_of: date) -> list[str]:
    """Probe symbols that were listed and not yet delisted on ``as_of``."""
    out: list[str] = []
    for probe in cfg.survivorship_probes:
        if as_of < probe.list_date:
            continue
        if as_of < probe.delist_date:
            out.append(probe.symbol)
    return out


def ensure_survivorship_probes(
    *,
    code: str = "mvp_cn_50",
    engine: Engine | None = None,
) -> dict[str, object]:
    """Upsert probe securities + delisted status history (does not touch bootstrap)."""
    cfg = load_universe_config(code)
    if not cfg.survivorship_probes:
        return {"code": cfg.code, "n_ensured": 0, "symbols": []}

    eng = engine or create_engine(get_settings().database_url, pool_pre_ping=True)
    ensured: list[str] = []
    with eng.begin() as conn:
        for probe in cfg.survivorship_probes:
            raw = probe.raw_symbol or probe.symbol.split(".")[0]
            sid = conn.execute(
                text(
                    """
                    INSERT INTO security
                        (market, symbol, raw_symbol, name, board, list_date, delist_date)
                    VALUES
                        (:market, :symbol, :raw, :name, CAST(:board AS board_type),
                         :list_date, :delist_date)
                    ON CONFLICT (market, symbol) DO UPDATE
                      SET name = EXCLUDED.name,
                          board = EXCLUDED.board,
                          list_date = EXCLUDED.list_date,
                          delist_date = EXCLUDED.delist_date
                    RETURNING security_id
                    """
                ),
                {
                    "market": cfg.market,
                    "symbol": probe.symbol,
                    "raw": raw,
                    "name": probe.name,
                    "board": probe.board,
                    "list_date": probe.list_date,
                    "delist_date": probe.delist_date,
                },
            ).scalar_one()
            # Listed interval then delisted from delist_date onward.
            conn.execute(
                text(
                    """
                    INSERT INTO security_status_history
                        (security_id, valid_from, valid_to, name, status, is_st, source)
                    VALUES
                        (
                            :sid, :list_date, :delist_date, :name,
                            'listed', FALSE, 'survivorship_probe'
                        )
                    ON CONFLICT (security_id, valid_from) DO UPDATE
                      SET valid_to = EXCLUDED.valid_to,
                          name = EXCLUDED.name,
                          status = EXCLUDED.status,
                          source = EXCLUDED.source
                    """
                ),
                {
                    "sid": sid,
                    "list_date": probe.list_date,
                    "delist_date": probe.delist_date,
                    "name": probe.name,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO security_status_history
                        (security_id, valid_from, valid_to, name, status, is_st, source)
                    VALUES
                        (:sid, :delist_date, NULL, :name, 'delisted', FALSE, 'survivorship_probe')
                    ON CONFLICT (security_id, valid_from) DO UPDATE
                      SET valid_to = EXCLUDED.valid_to,
                          name = EXCLUDED.name,
                          status = EXCLUDED.status,
                          source = EXCLUDED.source
                    """
                ),
                {
                    "sid": sid,
                    "delist_date": probe.delist_date,
                    "name": probe.name,
                },
            )
            ensured.append(probe.symbol)
    return {"code": cfg.code, "n_ensured": len(ensured), "symbols": ensured}


def seed_universe_snapshot(
    *,
    code: str = "mvp_cn_50",
    as_of: date,
    symbols: list[str] | None = None,
    engine: Engine | None = None,
    require_all: bool = False,
    include_survivorship: bool = False,
) -> dict[str, object]:
    """Upsert universe row + replace snapshot for ``as_of`` with known securities.

    Only symbols already present in ``security`` are written. Missing symbols are
    reported; set ``require_all=True`` to fail hard.

    Excludes names suspended on ``as_of`` and names with ``delist_date <= as_of``.
    When ``include_survivorship`` is True, merges active probe symbols for the date
    (for historical monthly backfill).
    """
    cfg = load_universe_config(code)
    wanted = list(symbols) if symbols is not None else list(cfg.bootstrap_symbols)
    if include_survivorship:
        for sym in active_survivorship_symbols(cfg, as_of):
            if sym not in wanted:
                wanted.append(sym)
    if not wanted:
        raise UniverseSeedError(f"No symbols to seed for universe {cfg.code}")

    eng = engine or create_engine(get_settings().database_url, pool_pre_ping=True)
    with eng.begin() as conn:
        stmt = text(
            "SELECT symbol, security_id FROM security WHERE symbol = ANY(:syms)"
        ).bindparams(bindparam("syms", type_=ARRAY(TEXT())))
        known = {str(r.symbol): int(r.security_id) for r in conn.execute(stmt, {"syms": wanted})}
        missing = [s for s in wanted if s not in known]
        if missing and require_all:
            raise UniverseSeedError(f"Missing securities (ingest first): {missing}")
        present = [s for s in wanted if s in known]
        if not present:
            raise UniverseSeedError(
                "No bootstrap symbols exist in security table; ingest prices first"
            )

        # A2 / universe rule ``not is_suspended``: exclude names suspended on as_of.
        suspended_ids = {
            int(r.security_id)
            for r in conn.execute(
                text(
                    """
                    SELECT security_id
                    FROM price_daily
                    WHERE trade_date = :d AND is_suspended IS TRUE
                    """
                ),
                {"d": as_of},
            )
        }
        # Already-delisted names must not appear in current / post-delist snapshots.
        delisted_ids = {
            int(r.security_id)
            for r in conn.execute(
                text(
                    """
                    SELECT security_id
                    FROM security
                    WHERE delist_date IS NOT NULL AND delist_date <= :d
                    """
                ),
                {"d": as_of},
            )
        }
        skip_ids = suspended_ids | delisted_ids
        if skip_ids:
            present = [s for s in present if known[s] not in skip_ids]
        if not present:
            raise UniverseSeedError(
                f"All candidate symbols suspended/delisted/missing on as_of={as_of.isoformat()}"
            )

        universe_id = conn.execute(
            text(
                """
                INSERT INTO universe (code, name, market, rule, description)
                VALUES (:code, :name, :market, CAST(:rule AS jsonb), :description)
                ON CONFLICT (code) DO UPDATE
                  SET name = EXCLUDED.name,
                      market = EXCLUDED.market,
                      rule = EXCLUDED.rule,
                      description = EXCLUDED.description
                RETURNING universe_id
                """
            ),
            {
                "code": cfg.code,
                "name": cfg.name,
                "market": cfg.market,
                "rule": json.dumps(cfg.rule.model_dump(), ensure_ascii=False),
                "description": "Bootstrap seed from config/universe until rule engine exists",
            },
        ).scalar_one()

        conn.execute(
            text(
                """
                DELETE FROM universe_snapshot
                WHERE universe_id = :uid AND snapshot_date = :d
                """
            ),
            {"uid": universe_id, "d": as_of},
        )
        weight = 1.0 / len(present)
        for sym in present:
            conn.execute(
                text(
                    """
                    INSERT INTO universe_snapshot
                        (universe_id, snapshot_date, security_id, weight)
                    VALUES (:uid, :d, :sid, :w)
                    """
                ),
                {
                    "uid": universe_id,
                    "d": as_of,
                    "sid": known[sym],
                    "w": weight,
                },
            )

    return {
        "code": cfg.code,
        "as_of": as_of.isoformat(),
        "n_seeded": len(present),
        "seeded": present,
        "missing": missing,
    }

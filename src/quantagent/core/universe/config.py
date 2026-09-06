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


class UniverseConfig(BaseModel):
    code: str
    name: str
    market: str = "CN"
    rule: UniverseRule = Field(default_factory=UniverseRule)
    bootstrap_symbols: list[str] = Field(default_factory=list)


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


def seed_universe_snapshot(
    *,
    code: str = "mvp_cn_50",
    as_of: date,
    symbols: list[str] | None = None,
    engine: Engine | None = None,
    require_all: bool = False,
) -> dict[str, object]:
    """Upsert universe row + replace snapshot for ``as_of`` with known securities.

    Only symbols already present in ``security`` are written. Missing symbols are
    reported; set ``require_all=True`` to fail hard.
    """
    cfg = load_universe_config(code)
    wanted = list(symbols) if symbols is not None else list(cfg.bootstrap_symbols)
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

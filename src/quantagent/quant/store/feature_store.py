"""Year-partitioned feature panels (docs/07-quant-engine.md §8)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from quantagent.shared.errors import QuantAgentError

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MARKET = re.compile(r"^[A-Za-z0-9_]+$")
_KEY_COLS = ("security_id", "trade_date", "code_version")


class FeatureStoreError(QuantAgentError):
    """Feature panel is missing, empty, or shaped wrong."""


class FeatureVersionError(FeatureStoreError):
    """Stored factor versions cannot be mixed with a different code version."""


def bundle_code_version(versions: dict[str, str]) -> str:
    """Stable id for one factor-code → version map."""
    if not versions:
        raise FeatureStoreError("versions must not be empty")
    payload = "|".join(f"{code}={versions[code]}" for code in sorted(versions))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class FeatureStore:
    """Parquet panels under ``{root}/{market}/panel/year=YYYY/part-0.parquet``."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def append(self, market: str, frame: pl.DataFrame, *, versions: dict[str, str]) -> None:
        """Write one ``trade_date``. Same version replaces that date; a new version raises."""
        normalized = _normalize(frame, versions)
        dates = normalized["trade_date"].unique().sort()
        if dates.len() != 1:
            raise FeatureStoreError(
                "append accepts exactly one trade_date; use rebuild for a history"
            )
        trade_date = dates.item()
        if not isinstance(trade_date, date):
            raise FeatureStoreError("trade_date must be a date")
        code_version = bundle_code_version(versions)
        meta = self._read_meta(market)
        if meta is None:
            self._write_part(market, trade_date.year, normalized)
            self._write_meta(market, versions, code_version)
            return
        self._require_same_version(meta, versions, code_version)
        path = self._part_path(market, trade_date.year)
        if path.is_file():
            existing = pl.read_parquet(path)
            self._require_frame_version(existing, code_version)
            existing = existing.filter(pl.col("trade_date") != trade_date)
            merged = pl.concat([existing, normalized], how="vertical_relaxed")
        else:
            merged = normalized
        self._write_part(market, trade_date.year, _sort_panel(merged))

    def rebuild(self, market: str, frame: pl.DataFrame, *, versions: dict[str, str]) -> None:
        """Replace every year partition and the version meta for ``market``."""
        normalized = _normalize(frame, versions)
        if normalized.is_empty():
            raise FeatureStoreError("rebuild requires at least one row")
        code_version = bundle_code_version(versions)
        panel_root = self._panel_root(market)
        if panel_root.is_dir():
            for child in panel_root.iterdir():
                if child.is_dir() and child.name.startswith("year="):
                    shutil.rmtree(child)
        stamped = normalized.with_columns(pl.col("trade_date").dt.year().alias("_year"))
        for year in stamped["_year"].unique().sort().to_list():
            part = stamped.filter(pl.col("_year") == year).drop("_year")
            self._write_part(market, int(year), _sort_panel(part))
        self._write_meta(market, versions, code_version)

    def load_panel(
        self,
        market: str,
        factors: list[str],
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> pl.DataFrame:
        """Load ``[start, end]`` with DuckDB. ``end`` cannot pass ``as_of``."""
        if end > as_of:
            raise FeatureStoreError(f"Cannot load features beyond as_of={as_of.isoformat()}")
        if start > end:
            raise FeatureStoreError("start must be <= end")
        if not factors:
            raise FeatureStoreError("at least one factor is required")
        for code in factors:
            _check_ident(code, label="factor")
        meta = self._read_meta(market)
        if meta is None:
            raise FeatureStoreError(f"no feature store for market {market}")
        unknown = [code for code in factors if code not in meta["factors"]]
        if unknown:
            raise FeatureStoreError(f"factors not in store: {unknown}")
        paths = sorted(self._panel_root(market).glob("year=*/part-0.parquet"))
        if not paths:
            raise FeatureStoreError(f"feature panel is empty for market {market}")
        selected = ["security_id", "trade_date", *factors, "code_version"]
        cols = ", ".join(_quote(name) for name in selected)
        globs = [path.as_posix() for path in paths]
        con = duckdb.connect(database=":memory:")
        try:
            frame = con.execute(
                f"""
                SELECT {cols}
                FROM read_parquet(?, hive_partitioning = true)
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date, security_id
                """,
                [globs, start, end],
            ).pl()
        finally:
            con.close()
        if frame.is_empty():
            return frame.drop("code_version")
        frame = frame.with_columns(pl.col("trade_date").cast(pl.Date))
        self._require_frame_version(frame, str(meta["code_version"]))
        return frame.drop("code_version")

    def versions(self, market: str) -> dict[str, str]:
        meta = self._read_meta(market)
        if meta is None:
            raise FeatureStoreError(f"no feature store for market {market}")
        return dict(meta["factors"])

    def _require_same_version(
        self,
        meta: dict[str, Any],
        versions: dict[str, str],
        code_version: str,
    ) -> None:
        stored = meta["factors"]
        if stored != versions or meta["code_version"] != code_version:
            raise FeatureVersionError(
                "stored factor versions differ from the incoming panel; "
                "rebuild the feature store instead of appending. "
                f"stored={stored} incoming={versions}"
            )

    def _require_frame_version(self, frame: pl.DataFrame, code_version: str) -> None:
        if frame.is_empty():
            return
        found = [str(value) for value in frame["code_version"].unique().to_list()]
        if found != [code_version]:
            raise FeatureVersionError(
                f"panel code_version {found} does not match meta {code_version}"
            )

    def _market(self, market: str) -> str:
        code = market.strip().lower()
        if not _MARKET.fullmatch(code):
            raise FeatureStoreError(f"invalid market {market!r}")
        return code

    def _panel_root(self, market: str) -> Path:
        return self.root / self._market(market) / "panel"

    def _meta_path(self, market: str) -> Path:
        return self.root / self._market(market) / "meta" / "factor_versions.json"

    def _part_path(self, market: str, year: int) -> Path:
        return self._panel_root(market) / f"year={year}" / "part-0.parquet"

    def _write_part(self, market: str, year: int, frame: pl.DataFrame) -> None:
        path = self._part_path(market, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        _sort_panel(frame).write_parquet(path)

    def _write_meta(self, market: str, versions: dict[str, str], code_version: str) -> None:
        path = self._meta_path(market)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "code_version": code_version,
            "factors": {code: versions[code] for code in sorted(versions)},
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

    def _read_meta(self, market: str) -> dict[str, Any] | None:
        path = self._meta_path(market)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FeatureStoreError(f"factor version meta unreadable: {path}") from exc
        if not isinstance(raw, dict):
            raise FeatureStoreError(f"factor version meta is not an object: {path}")
        factors = raw.get("factors")
        code_version = raw.get("code_version")
        if not isinstance(factors, dict) or not factors or not isinstance(code_version, str):
            raise FeatureStoreError(f"factor version meta missing fields: {path}")
        parsed = {str(key): str(value) for key, value in factors.items()}
        if bundle_code_version(parsed) != code_version:
            raise FeatureVersionError(
                f"factor version meta hash does not match code_version in {path}"
            )
        return {"code_version": code_version, "factors": parsed}


def _check_ident(name: str, *, label: str) -> None:
    if not _IDENT.fullmatch(name):
        raise FeatureStoreError(f"invalid {label} {name!r}")


def _quote(name: str) -> str:
    _check_ident(name, label="column")
    return f'"{name}"'


def _normalize(frame: pl.DataFrame, versions: dict[str, str]) -> pl.DataFrame:
    if not versions:
        raise FeatureStoreError("versions must not be empty")
    for code, version in versions.items():
        _check_ident(code, label="factor")
        if not isinstance(version, str) or not version.strip():
            raise FeatureStoreError(f"version for {code} must be a non-empty string")
    if "security_id" not in frame.columns or "trade_date" not in frame.columns:
        raise FeatureStoreError("panel requires security_id and trade_date")
    factors = sorted(versions)
    missing = [code for code in factors if code not in frame.columns]
    if missing:
        raise FeatureStoreError(f"panel missing factor columns: {missing}")
    code_version = bundle_code_version(versions)
    if "code_version" in frame.columns:
        supplied = [str(value) for value in frame["code_version"].unique().to_list()]
        if supplied != [code_version]:
            raise FeatureVersionError(
                f"frame code_version {supplied} does not match versions hash {code_version}"
            )
    out = frame.select(["security_id", "trade_date", *factors]).with_columns(
        pl.col("trade_date").cast(pl.Date),
        pl.lit(code_version).alias("code_version"),
    )
    if out.select(["security_id", "trade_date"]).is_duplicated().any():
        raise FeatureStoreError("duplicate security_id and trade_date")
    return out


def _sort_panel(frame: pl.DataFrame) -> pl.DataFrame:
    factors = [name for name in frame.columns if name not in _KEY_COLS]
    return frame.select(["security_id", "trade_date", *sorted(factors), "code_version"]).sort(
        ["trade_date", "security_id"]
    )

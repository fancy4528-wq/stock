"""One-time holdout access log (docs/07-quant-engine.md §6.2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml  # type: ignore[import-untyped]

from quantagent.shared.errors import ConfigError

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class HoldoutViolation(RuntimeError):
    """Raised when a sealed window is reused, or training reaches into it."""


@dataclass(frozen=True)
class HoldoutUse:
    """One recorded consumption of the holdout window."""

    date: date
    purpose: str
    end_date: date


class HoldoutGuard:
    """Seal dates on or after ``holdout_start``.

    ``check_access`` is the single allowed final look: the first call that
    reaches the seal is appended to ``log_path``; a later call raises
    ``HoldoutViolation``. ``assert_excluded`` refuses the same dates without
    writing the log, so walk-forward can stop the day before and leave the
    one use unused.
    """

    def __init__(self, holdout_start: date, log_path: Path):
        if not isinstance(holdout_start, date):
            raise TypeError("holdout_start must be a date")
        self.holdout_start = holdout_start
        self.log_path = Path(log_path)

    def touches(self, end_date: date) -> bool:
        return end_date >= self.holdout_start

    def clip(self, panel_end: date) -> date:
        """Last date walk-forward may use. Does not record a holdout use."""
        if self.touches(panel_end):
            return self.holdout_start.fromordinal(self.holdout_start.toordinal() - 1)
        return panel_end

    def assert_excluded(self, end_date: date) -> None:
        """Refuse a window that reaches the seal. Does not record a use."""
        if self.touches(end_date):
            raise HoldoutViolation(
                f"window end {end_date.isoformat()} reaches holdout starting "
                f"{self.holdout_start.isoformat()}. "
                "Walk-forward must stop the day before. "
                "The single allowed final check is HoldoutGuard.check_access."
            )

    def check_access(self, end_date: date, purpose: str) -> None:
        """Allow the first look at the seal; refuse every later look."""
        text = purpose.strip()
        if not text:
            raise ValueError("purpose is required")
        if not self.touches(end_date):
            return
        uses = self._read_log()
        if uses:
            detail = "\n".join(f"  {u.date.isoformat()} - {u.purpose}" for u in uses)
            raise HoldoutViolation(
                f"封存期已使用过 {len(uses)} 次:\n"
                f"{detail}\n"
                "再次使用将使封存期失去意义。"
            )
        self._log_use(text, end_date)

    def uses(self) -> list[HoldoutUse]:
        return self._read_log()

    def _read_log(self) -> list[HoldoutUse]:
        if not self.log_path.is_file():
            return []
        rows: list[HoldoutUse] = []
        raw = self.log_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HoldoutViolation(
                    f"holdout log unreadable at {self.log_path}:{line_no}"
                ) from exc
            if not isinstance(payload, dict):
                raise HoldoutViolation(
                    f"holdout log row is not an object at {self.log_path}:{line_no}"
                )
            rows.append(_parse_use(payload, self.log_path, line_no))
        return rows

    def _log_use(self, purpose: str, end_date: date) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        used_on = datetime.now(_SHANGHAI).date()
        record = {
            "date": used_on.isoformat(),
            "purpose": purpose,
            "end_date": end_date.isoformat(),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _parse_use(payload: dict[str, Any], path: Path, line_no: int) -> HoldoutUse:
    try:
        used_on = date.fromisoformat(str(payload["date"]))
        purpose = str(payload["purpose"]).strip()
        end = date.fromisoformat(str(payload["end_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HoldoutViolation(
            f"holdout log row missing fields at {path}:{line_no}"
        ) from exc
    if not purpose:
        raise HoldoutViolation(f"holdout log purpose empty at {path}:{line_no}")
    return HoldoutUse(date=used_on, purpose=purpose, end_date=end)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "config").is_dir():
            return parent
    raise ConfigError("Cannot locate repo root containing config/")


def holdout_config_path(market: str = "CN", *, config_dir: Path | None = None) -> Path:
    root = config_dir or (_repo_root() / "config" / "quant")
    path = root / f"holdout_{market.strip().lower()}.yaml"
    if not path.is_file():
        raise ConfigError(f"Holdout config not found: {path}")
    return path


def load_holdout_guard(
    market: str = "CN",
    *,
    config_path: Path | None = None,
) -> HoldoutGuard:
    """Load the frozen seal. ``log_path`` in YAML is relative to the repo root."""
    path = config_path or holdout_config_path(market)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid holdout config YAML: {path}")
    try:
        start = date.fromisoformat(str(raw["holdout_start"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"holdout_start missing or invalid in {path}") from exc
    log_raw = raw.get("log_path")
    if not isinstance(log_raw, str) or not log_raw.strip():
        raise ConfigError(f"log_path missing in {path}")
    log_path = Path(log_raw)
    if not log_path.is_absolute():
        log_path = _repo_root() / log_path
    return HoldoutGuard(start, log_path)

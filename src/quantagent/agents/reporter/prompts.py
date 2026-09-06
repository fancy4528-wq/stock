"""Load versioned prompts from prompts/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    # src/quantagent/agents/reporter/prompts.py -> repo root
    return Path(__file__).resolve().parents[4]


@lru_cache
def load_prompt(name: str, version: str = "v1") -> str:
    path = _repo_root() / "prompts" / name / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")


@lru_cache
def load_common_constraints() -> str:
    path = _repo_root() / "prompts" / "_common" / "constraints.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

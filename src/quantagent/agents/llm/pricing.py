"""Token estimation and USD pricing helpers (no external tokenizer dep)."""

from __future__ import annotations

from quantagent.agents.llm.config import LLMConfig, TierConfig


def estimate_tokens(text: str) -> int:
    """Heuristic token count for pre-call budget (CJK ≈ 1 tok/char, else ≈4 chars).

    Gate 2 prefers a real tokenizer; this stays dependency-free and conservative
    enough for ADR-0010 pre-call interception.
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        code = ord(ch)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0x3000 <= code <= 0x303F
            or 0xFF00 <= code <= 0xFFEF
        ):
            cjk += 1
        else:
            other += 1
    return max(1, cjk + (other + 3) // 4)


def estimate_prompt_tokens(*, system: str, user: str) -> int:
    # Chat markup overhead (~4 tokens/message + role names).
    return estimate_tokens(system) + estimate_tokens(user) + 8


def price_usd(
    tier: TierConfig,
    *,
    tokens_in: int,
    tokens_out: int,
) -> float:
    return (
        tokens_in * tier.input_usd_per_1m / 1_000_000.0
        + tokens_out * tier.output_usd_per_1m / 1_000_000.0
    )


def price_usd_for_tier(
    cfg: LLMConfig,
    tier_name: str,
    *,
    tokens_in: int,
    tokens_out: int,
) -> float:
    return price_usd(cfg.tier(tier_name), tokens_in=tokens_in, tokens_out=tokens_out)

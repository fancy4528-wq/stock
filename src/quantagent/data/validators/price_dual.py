"""Dual-source price comparison helpers (PX_009)."""

from __future__ import annotations

import polars as pl


def attach_peer_closes(primary: pl.DataFrame, peer: pl.DataFrame) -> pl.DataFrame:
    """Join ``close_peer`` from *peer* onto *primary* by ``symbol`` + ``trade_date``."""
    if peer.is_empty():
        return primary.with_columns(pl.lit(None).cast(pl.Float64).alias("close_peer"))
    peer_sel = peer.select(
        [
            "symbol",
            "trade_date",
            pl.col("close").alias("close_peer"),
        ]
    )
    return primary.join(peer_sel, on=["symbol", "trade_date"], how="left")

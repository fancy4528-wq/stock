"""PIT integrity checks (docs/04-data-sources.md §3.4 + edge-case checklist G)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text

from quantagent.data.validators.report import RuleResult, ValidationReport

# Tables that must carry a non-null announced_at (PIT_002). Absent tables are skipped.
_PIT_002_TABLES: tuple[str, ...] = (
    "financial_statement",
    "financial_indicator",
    "adjust_factor",
    "macro_observation",
)


def _relation_exists(conn: Connection, name: str) -> bool:
    found = conn.execute(
        text("SELECT to_regclass(:n) IS NOT NULL"),
        {"n": f"public.{name}"},
    ).scalar_one()
    return bool(found)


def _column_exists(conn: Connection, table: str, column: str) -> bool:
    n = conn.execute(
        text(
            """
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :t
              AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).scalar_one()
    return int(n) > 0


def rule_pit_001_announced_before_ingested(conn: Connection) -> RuleResult:
    """No row may have announced_at later than ingested_at (FATAL)."""
    tables = (
        ("financial_statement", "announced_at", "ingested_at"),
        ("adjust_factor", "announced_at", "ingested_at"),
    )
    keys: list[str] = []
    for table, ann, ing in tables:
        if not _relation_exists(conn, table):
            continue
        rows = conn.execute(
            text(
                f"""
                SELECT COUNT(*) AS n
                FROM {table}
                WHERE {ann} IS NOT NULL AND {ing} IS NOT NULL AND {ann} > {ing}
                """
            )
        ).scalar_one()
        if int(rows) > 0:
            keys.append(f"{table}:{int(rows)}")
    return RuleResult(
        code="PIT_001",
        level="FATAL",
        status="fail" if keys else "pass",
        detail="announced_at > ingested_at" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def rule_pit_002_announced_at_required(conn: Connection) -> RuleResult:
    """Financial / macro / adjust tables must not have announced_at IS NULL (FATAL)."""
    keys: list[str] = []
    checked = 0
    for table in _PIT_002_TABLES:
        if not _relation_exists(conn, table):
            continue
        if not _column_exists(conn, table, "announced_at"):
            continue
        checked += 1
        n = conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE announced_at IS NULL")
        ).scalar_one()
        if int(n) > 0:
            keys.append(f"{table}:{int(n)}")
    if checked == 0:
        return RuleResult(
            code="PIT_002",
            level="FATAL",
            status="pass",
            detail="skipped: no announced_at tables present",
        )
    return RuleResult(
        code="PIT_002",
        level="FATAL",
        status="fail" if keys else "pass",
        detail="announced_at IS NULL" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def rule_pit_003_no_interval_overlap(conn: Connection) -> RuleResult:
    """security_industry intervals for same (security, industry) must not overlap."""
    rows = (
        conn.execute(
            text(
                """
            SELECT a.security_id, a.industry_id, a.valid_from
            FROM security_industry a
            JOIN security_industry b
              ON a.security_id = b.security_id
             AND a.industry_id = b.industry_id
             AND a.valid_from < b.valid_from
             AND (a.valid_to IS NULL OR a.valid_to > b.valid_from)
            LIMIT 50
            """
            )
        )
        .mappings()
        .all()
    )
    keys = [f"{r['security_id']}|{r['industry_id']}|{r['valid_from']}" for r in rows]
    return RuleResult(
        code="PIT_003",
        level="FATAL",
        status="fail" if keys else "pass",
        detail="overlapping industry intervals" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def rule_pit_005_snapshot_on_rebalance(
    conn: Connection, *, rebalance_dates: list[date] | None = None
) -> RuleResult:
    """Every rebalance date should have a universe_snapshot (ERROR)."""
    if not rebalance_dates:
        return RuleResult(code="PIT_005", level="ERROR", status="pass", detail="skipped")
    missing: list[str] = []
    for d in rebalance_dates:
        n = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM universe_snapshot WHERE snapshot_date = :d
                """
            ),
            {"d": d},
        ).scalar_one()
        if int(n) == 0:
            missing.append(d.isoformat())
    return RuleResult(
        code="PIT_005",
        level="ERROR",
        status="fail" if missing else "pass",
        detail=f"missing snapshots: {missing[:5]}" if missing else "ok",
        affected_count=len(missing),
        affected_keys=missing,
    )


def rule_pit_006_no_price_after_delist(conn: Connection) -> RuleResult:
    """Prices after security.delist_date → WARN."""
    rows = (
        conn.execute(
            text(
                """
            SELECT s.symbol, p.trade_date
            FROM price_daily p
            JOIN security s ON s.security_id = p.security_id
            WHERE s.delist_date IS NOT NULL
              AND p.trade_date > s.delist_date
            LIMIT 50
            """
            )
        )
        .mappings()
        .all()
    )
    keys = [f"{r['symbol']}|{r['trade_date']}" for r in rows]
    return RuleResult(
        code="PIT_006",
        level="WARN",
        status="warn" if keys else "pass",
        detail="price after delist_date" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def rule_pit_007_delisted_security_retained(conn: Connection) -> RuleResult:
    """Delisted status history must still resolve to a security row (FATAL)."""
    rows = (
        conn.execute(
            text(
                """
            SELECT h.security_id
            FROM security_status_history h
            LEFT JOIN security s ON s.security_id = h.security_id
            WHERE h.status = 'delisted' AND s.security_id IS NULL
            LIMIT 50
            """
            )
        )
        .mappings()
        .all()
    )
    keys = [str(r["security_id"]) for r in rows]
    return RuleResult(
        code="PIT_007",
        level="FATAL",
        status="fail" if keys else "pass",
        detail="delisted status without security row" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def rule_pit_008_document_chunk_visible_at(conn: Connection) -> RuleResult:
    """document_chunk.visible_at must be non-null and not after ingest time (FATAL).

    Uses ``ingested_at`` when present, otherwise ``created_at`` (schema in docs/03).
    Absent table → pass (knowledge base not yet migrated).
    """
    table = "document_chunk"
    if not _relation_exists(conn, table):
        return RuleResult(
            code="PIT_008",
            level="FATAL",
            status="pass",
            detail="skipped: document_chunk absent",
        )
    if not _column_exists(conn, table, "visible_at"):
        return RuleResult(
            code="PIT_008",
            level="FATAL",
            status="fail",
            detail="document_chunk missing visible_at column",
            affected_count=1,
            affected_keys=["visible_at"],
        )

    null_n = conn.execute(
        text("SELECT COUNT(*) FROM document_chunk WHERE visible_at IS NULL")
    ).scalar_one()
    keys: list[str] = []
    if int(null_n) > 0:
        keys.append(f"visible_at_null:{int(null_n)}")

    ingest_col = None
    if _column_exists(conn, table, "ingested_at"):
        ingest_col = "ingested_at"
    elif _column_exists(conn, table, "created_at"):
        ingest_col = "created_at"

    if ingest_col is not None:
        late_n = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM document_chunk
                WHERE visible_at IS NOT NULL
                  AND {ingest_col} IS NOT NULL
                  AND visible_at > {ingest_col}
                """
            )
        ).scalar_one()
        if int(late_n) > 0:
            keys.append(f"visible_at_after_{ingest_col}:{int(late_n)}")

    return RuleResult(
        code="PIT_008",
        level="FATAL",
        status="fail" if keys else "pass",
        detail="visible_at invalid vs ingest" if keys else "ok",
        affected_count=len(keys),
        affected_keys=keys,
    )


def run_pit_checks(
    conn: Connection,
    *,
    check_date: date | None = None,
    rebalance_dates: list[date] | None = None,
) -> ValidationReport:
    """Run PIT_001/002/003/005/006/007/008 against the live database."""
    results = [
        rule_pit_001_announced_before_ingested(conn),
        rule_pit_002_announced_at_required(conn),
        rule_pit_003_no_interval_overlap(conn),
        rule_pit_005_snapshot_on_rebalance(conn, rebalance_dates=rebalance_dates),
        rule_pit_006_no_price_after_delist(conn),
        rule_pit_007_delisted_security_retained(conn),
        rule_pit_008_document_chunk_visible_at(conn),
    ]
    return ValidationReport(
        dataset="pit_integrity",
        check_date=check_date or date.today(),
        results=results,
    )


def compare_adjust_factors(
    *,
    factor_a: float,
    factor_b: float,
    threshold: float = 0.001,
) -> RuleResult:
    """C3 helper: dual-source adjust-factor divergence."""
    if factor_a == 0:
        rel = abs(factor_b)
    else:
        rel = abs(factor_a - factor_b) / abs(factor_a)
    failed = rel > threshold
    return RuleResult(
        code="ADJ_DUAL",
        level="WARN",
        status="warn" if failed else "pass",
        detail=f"adj factor rel diff={rel:.4%}" if failed else "ok",
        affected_count=1 if failed else 0,
        expected={"threshold": threshold},
        actual={"factor_a": factor_a, "factor_b": factor_b, "rel": rel},
    )

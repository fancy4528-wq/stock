-- P0 PIT query functions (as_of semantics).

CREATE OR REPLACE FUNCTION get_financials_as_of(
    p_security_ids BIGINT[],
    p_as_of        TIMESTAMPTZ,
    p_periods      INT DEFAULT 8
) RETURNS SETOF financial_statement AS $$
    WITH visible AS (
        SELECT DISTINCT ON (security_id, period_end, period_type) *
        FROM financial_statement
        WHERE security_id = ANY(p_security_ids)
          AND announced_at <= p_as_of
        ORDER BY security_id, period_end, period_type, revision DESC
    ),
    ranked AS (
        SELECT
            visible.*,
            ROW_NUMBER() OVER (
                PARTITION BY security_id
                ORDER BY period_end DESC, period_type
            ) AS rn
        FROM visible
    )
    SELECT
        security_id, period_end, period_type, revision, announced_at, report_type,
        revenue, operating_cost, gross_profit, operating_profit, net_profit,
        net_profit_attr, net_profit_deducted, eps,
        total_assets, total_liab, total_equity, equity_attr, cash_and_equiv,
        inventory, accounts_recv, goodwill,
        cfo, cfi, cff, capex,
        source, raw_ref, quality, ingested_at
    FROM ranked
    WHERE rn <= p_periods;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION get_industry_as_of(
    p_security_ids BIGINT[],
    p_as_of        DATE,
    p_taxonomy     TEXT DEFAULT 'sw_2021'
) RETURNS TABLE (
    security_id BIGINT,
    industry_code TEXT,
    industry_name TEXT,
    level INT
) AS $$
    SELECT si.security_id, i.code, i.name, i.level
    FROM security_industry si
    JOIN industry i ON i.industry_id = si.industry_id
    JOIN industry_taxonomy t ON t.taxonomy_id = i.taxonomy_id
    WHERE si.security_id = ANY(p_security_ids)
      AND t.code = p_taxonomy
      AND si.valid_from <= p_as_of
      AND (si.valid_to IS NULL OR si.valid_to > p_as_of);
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION get_universe_as_of(
    p_universe_code TEXT,
    p_as_of         DATE
) RETURNS TABLE (security_id BIGINT, weight NUMERIC) AS $$
    WITH latest AS (
        SELECT max(us.snapshot_date) AS d
        FROM universe_snapshot us
        JOIN universe u ON u.universe_id = us.universe_id
        WHERE u.code = p_universe_code
          AND us.snapshot_date <= p_as_of
    )
    SELECT us.security_id, us.weight
    FROM universe_snapshot us
    JOIN universe u ON u.universe_id = us.universe_id
    JOIN latest ON us.snapshot_date = latest.d
    WHERE u.code = p_universe_code;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION get_prices_as_of(
    p_security_ids BIGINT[],
    p_start        DATE,
    p_end          DATE,
    p_as_of        TIMESTAMPTZ,
    p_adjust       TEXT DEFAULT 'qfq'
) RETURNS TABLE (
    security_id BIGINT,
    trade_date DATE,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    prev_close NUMERIC,
    volume BIGINT,
    amount NUMERIC,
    turnover_rate NUMERIC,
    is_limit_up BOOLEAN,
    is_limit_down BOOLEAN,
    is_suspended BOOLEAN
) AS $$
    WITH af AS (
        SELECT DISTINCT ON (security_id, trade_date)
               security_id,
               trade_date,
               factor_qfq,
               factor_hfq
        FROM adjust_factor
        WHERE security_id = ANY(p_security_ids)
          AND announced_at <= p_as_of
        ORDER BY security_id, trade_date, revision DESC
    )
    SELECT
        p.security_id,
        p.trade_date,
        p.open  * COALESCE(
            CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
        ),
        p.high  * COALESCE(
            CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
        ),
        p.low   * COALESCE(
            CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
        ),
        p.close * COALESCE(
            CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
        ),
        p.prev_close * COALESCE(
            CASE WHEN p_adjust = 'hfq' THEN f.factor_hfq ELSE f.factor_qfq END, 1
        ),
        p.volume,
        p.amount,
        p.turnover_rate,
        p.is_limit_up,
        p.is_limit_down,
        p.is_suspended
    FROM price_daily p
    LEFT JOIN af f USING (security_id, trade_date)
    WHERE p.security_id = ANY(p_security_ids)
      AND p.trade_date BETWEEN p_start AND p_end
      AND p.trade_date <= p_as_of::date
    ORDER BY p.security_id, p.trade_date;
$$ LANGUAGE sql STABLE;

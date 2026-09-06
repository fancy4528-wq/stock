-- Extend get_prices_as_of with liquidity / prev_close columns for factors + reports.
-- Caller must DROP the old signature first when changing OUT columns.

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

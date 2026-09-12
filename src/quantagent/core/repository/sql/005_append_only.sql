-- Append-only shadow_day journal + reusable guard trigger function.

CREATE OR REPLACE FUNCTION prevent_update_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'append-only: % on % forbidden', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS shadow_day (
    portfolio    TEXT        NOT NULL,
    as_of        DATE        NOT NULL,
    run_id       TEXT        NOT NULL,
    nav          NUMERIC     NOT NULL,
    cash         NUMERIC     NOT NULL,
    ret_1d       NUMERIC     NOT NULL,
    ret_cum      NUMERIC     NOT NULL,
    max_drawdown NUMERIC     NOT NULL,
    n_positions  INT         NOT NULL,
    weights      JSONB       NOT NULL DEFAULT '{}',
    unfilled     JSONB       NOT NULL DEFAULT '[]',
    notes        JSONB       NOT NULL DEFAULT '[]',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (portfolio, as_of, run_id)
);

DROP TRIGGER IF EXISTS shadow_day_append_only ON shadow_day;
CREATE TRIGGER shadow_day_append_only
    BEFORE UPDATE OR DELETE ON shadow_day
    FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();

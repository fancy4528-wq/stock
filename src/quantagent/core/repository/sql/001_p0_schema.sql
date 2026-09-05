-- P0 schema: extensions, enums, core PIT tables, hypertables.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TYPE market_code AS ENUM ('CN', 'HK', 'US');
CREATE TYPE listing_status AS ENUM ('listed', 'suspended', 'delisted', 'pre_ipo');
CREATE TYPE board_type AS ENUM ('main', 'star', 'gem', 'bse', 'nasdaq', 'nyse', 'amex');
CREATE TYPE data_quality AS ENUM ('ok', 'suspect', 'corrected', 'missing');

CREATE TABLE security (
    security_id   BIGSERIAL PRIMARY KEY,
    market        market_code NOT NULL,
    symbol        TEXT        NOT NULL,
    raw_symbol    TEXT        NOT NULL,
    name          TEXT        NOT NULL,
    name_en       TEXT,
    board         board_type,
    list_date     DATE,
    delist_date   DATE,
    currency      CHAR(3)     NOT NULL DEFAULT 'CNY',
    isin          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (market, symbol)
);

COMMENT ON COLUMN security.delist_date IS
  '退市股票必须保留，用于避免生存者偏差。禁止 DELETE。';

CREATE INDEX idx_security_market_symbol ON security (market, symbol);
CREATE INDEX idx_security_delist ON security (delist_date)
    WHERE delist_date IS NOT NULL;

CREATE TABLE security_status_history (
    security_id   BIGINT      NOT NULL REFERENCES security(security_id),
    valid_from    DATE        NOT NULL,
    valid_to      DATE,
    name          TEXT        NOT NULL,
    status        listing_status NOT NULL,
    is_st         BOOLEAN     NOT NULL DEFAULT FALSE,
    st_reason     TEXT,
    source        TEXT        NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, valid_from)
);

COMMENT ON TABLE security_status_history IS
  'ST 状态影响涨跌停幅度(±5%)，必须按时点查询。';

CREATE INDEX idx_sec_status_range ON security_status_history
    (security_id, valid_from, valid_to);

CREATE TABLE industry_taxonomy (
    taxonomy_id   SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    market        market_code NOT NULL,
    levels        INT  NOT NULL
);

CREATE TABLE industry (
    industry_id   BIGSERIAL PRIMARY KEY,
    taxonomy_id   INT  NOT NULL REFERENCES industry_taxonomy(taxonomy_id),
    code          TEXT NOT NULL,
    name          TEXT NOT NULL,
    level         INT  NOT NULL,
    parent_code   TEXT,
    UNIQUE (taxonomy_id, code)
);

CREATE TABLE security_industry (
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    industry_id   BIGINT NOT NULL REFERENCES industry(industry_id),
    valid_from    DATE   NOT NULL,
    valid_to      DATE,
    source        TEXT   NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, industry_id, valid_from)
);

CREATE INDEX idx_sec_ind_lookup ON security_industry
    (security_id, valid_from, valid_to);
CREATE INDEX idx_sec_ind_reverse ON security_industry
    (industry_id, valid_from, valid_to);

CREATE TABLE universe (
    universe_id   SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    market        market_code NOT NULL,
    rule          JSONB,
    description   TEXT
);

CREATE TABLE universe_snapshot (
    universe_id   INT    NOT NULL REFERENCES universe(universe_id),
    snapshot_date DATE   NOT NULL,
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    weight        NUMERIC(10,8),
    PRIMARY KEY (universe_id, snapshot_date, security_id)
);

COMMENT ON TABLE universe_snapshot IS
  '按日或按调仓日记录成分。回测必须查 snapshot_date <= as_of 的最近一期，'
  '禁止用当前成分回溯历史。';

CREATE INDEX idx_universe_snap ON universe_snapshot (universe_id, snapshot_date);

CREATE TABLE price_daily (
    security_id     BIGINT      NOT NULL REFERENCES security(security_id),
    trade_date      DATE        NOT NULL,
    open            NUMERIC(18,4),
    high            NUMERIC(18,4),
    low             NUMERIC(18,4),
    close           NUMERIC(18,4),
    prev_close      NUMERIC(18,4),
    volume          BIGINT,
    amount          NUMERIC(20,2),
    limit_up_px     NUMERIC(18,4),
    limit_down_px   NUMERIC(18,4),
    is_limit_up     BOOLEAN,
    is_limit_down   BOOLEAN,
    is_suspended    BOOLEAN NOT NULL DEFAULT FALSE,
    turnover_rate   NUMERIC(10,6),
    source          TEXT        NOT NULL,
    quality         data_quality NOT NULL DEFAULT 'ok',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, trade_date)
);

SELECT create_hypertable('price_daily', 'trade_date',
                          chunk_time_interval => INTERVAL '1 year');

COMMENT ON COLUMN price_daily.is_limit_up IS
  '回测撮合必须检查：涨停时买单不可成交，跌停时卖单不可成交。';

CREATE INDEX idx_price_daily_date ON price_daily (trade_date, security_id);

CREATE TABLE adjust_factor (
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    trade_date    DATE   NOT NULL,
    revision      INT    NOT NULL DEFAULT 1,
    announced_at  TIMESTAMPTZ NOT NULL,
    factor_qfq    NUMERIC(18,8) NOT NULL,
    factor_hfq    NUMERIC(18,8) NOT NULL,
    source        TEXT   NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, trade_date, revision)
);

COMMENT ON TABLE adjust_factor IS
  '存未复权价 + 因子，而非直接存复权价。因为前复权价会随每次除权变化，'
  '直接存复权价会导致历史数据被静默改写。';

CREATE TABLE trading_calendar (
    market        market_code NOT NULL,
    trade_date    DATE        NOT NULL,
    is_open       BOOLEAN     NOT NULL,
    prev_trade_date DATE,
    next_trade_date DATE,
    note          TEXT,
    PRIMARY KEY (market, trade_date)
);

CREATE TABLE financial_statement (
    security_id     BIGINT NOT NULL REFERENCES security(security_id),
    period_end      DATE   NOT NULL,
    period_type     TEXT   NOT NULL,
    revision        INT    NOT NULL DEFAULT 1,
    announced_at    TIMESTAMPTZ NOT NULL,
    report_type     TEXT   NOT NULL,

    revenue         NUMERIC(20,2),
    operating_cost  NUMERIC(20,2),
    gross_profit    NUMERIC(20,2),
    operating_profit NUMERIC(20,2),
    net_profit      NUMERIC(20,2),
    net_profit_attr NUMERIC(20,2),
    net_profit_deducted NUMERIC(20,2),
    eps             NUMERIC(12,6),

    total_assets    NUMERIC(20,2),
    total_liab      NUMERIC(20,2),
    total_equity    NUMERIC(20,2),
    equity_attr     NUMERIC(20,2),
    cash_and_equiv  NUMERIC(20,2),
    inventory       NUMERIC(20,2),
    accounts_recv   NUMERIC(20,2),
    goodwill        NUMERIC(20,2),

    cfo             NUMERIC(20,2),
    cfi             NUMERIC(20,2),
    cff             NUMERIC(20,2),
    capex           NUMERIC(20,2),

    source          TEXT   NOT NULL,
    raw_ref         TEXT,
    quality         data_quality NOT NULL DEFAULT 'ok',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (security_id, period_end, period_type, revision)
);

CREATE INDEX idx_fin_pit ON financial_statement
    (security_id, announced_at DESC, period_end DESC);

COMMENT ON TABLE financial_statement IS
  'PIT 查询：WHERE announced_at <= as_of，取每个 period 的最大 revision。'
  '禁止 UPDATE 已有行，修订必须 INSERT 新 revision。';

CREATE TABLE financial_indicator (
    security_id     BIGINT NOT NULL REFERENCES security(security_id),
    period_end      DATE   NOT NULL,
    revision        INT    NOT NULL DEFAULT 1,
    announced_at    TIMESTAMPTZ NOT NULL,
    roe             NUMERIC(12,6),
    roa             NUMERIC(12,6),
    gross_margin    NUMERIC(12,6),
    net_margin      NUMERIC(12,6),
    debt_to_asset   NUMERIC(12,6),
    current_ratio   NUMERIC(12,6),
    revenue_yoy     NUMERIC(12,6),
    profit_yoy      NUMERIC(12,6),
    ocf_to_profit   NUMERIC(12,6),
    source          TEXT   NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, period_end, revision)
);

CREATE TABLE valuation_daily (
    security_id     BIGINT NOT NULL REFERENCES security(security_id),
    trade_date      DATE   NOT NULL,
    market_cap      NUMERIC(20,2),
    circ_market_cap NUMERIC(20,2),
    pe_ttm          NUMERIC(14,4),
    pe_lyr          NUMERIC(14,4),
    pb              NUMERIC(14,4),
    ps_ttm          NUMERIC(14,4),
    dividend_yield  NUMERIC(10,6),
    source          TEXT   NOT NULL,
    PRIMARY KEY (security_id, trade_date)
);

SELECT create_hypertable('valuation_daily', 'trade_date',
                          chunk_time_interval => INTERVAL '1 year');

# 03 — 数据模型

## 1. 核心原则：Point-in-Time

### 1.1 问题

金融数据会被追溯修改：

| 数据 | 修改情形 |
|---|---|
| 财务报表 | 会计差错更正、追溯重述、审计调整 |
| 行业分类 | 申万定期调整分类标准与个股归属 |
| 指数成分 | 定期调仓，成分股增删 |
| 股票状态 | ST/退市/更名 |
| 复权因子 | 除权除息后历史价格全部变化 |

如果回测查询"当前版本"的数据，等于让策略看到了未来。这是量化项目最常见也最致命的错误，且**症状是回测漂亮、实盘失效**，极难事后诊断。

### 1.2 解决方案：双时间轴

每条可变记录都有两个时间维度：

| 维度 | 字段 | 含义 |
|---|---|---|
| **事件时间** | `period` / `trade_date` | 数据描述的是哪个时期 |
| **知晓时间** | `announced_at` | 这个数据什么时候可以被知道 |

查询规则：

```sql
-- 取 as_of 时点可见的最新版本
SELECT DISTINCT ON (symbol, period) *
FROM financial_statement
WHERE symbol = ANY($symbols)
  AND announced_at <= $as_of      -- ★ 核心过滤
ORDER BY symbol, period, revision DESC;
```

### 1.3 三种数据的处理策略

| 类型 | 例子 | 策略 |
|---|---|---|
| **不可变** | 日线 OHLCV（未复权） | 单版本，只需 `trade_date` |
| **可修订** | 财报、复权因子 | 多版本，`(key, revision)` + `announced_at` |
| **区间有效** | 行业归属、指数成分、ST 状态 | 区间表，`valid_from` / `valid_to` |

## 2. 完整 DDL

### 2.1 扩展与枚举

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- 中文模糊搜索辅助

-- ─────────────────────────────────────────────
-- 枚举类型
-- ─────────────────────────────────────────────
CREATE TYPE market_code   AS ENUM ('CN', 'HK', 'US');
CREATE TYPE listing_status AS ENUM ('listed', 'suspended', 'delisted', 'pre_ipo');
CREATE TYPE board_type    AS ENUM ('main', 'star', 'gem', 'bse', 'nasdaq', 'nyse', 'amex');
CREATE TYPE order_side    AS ENUM ('buy', 'sell');
CREATE TYPE order_type    AS ENUM ('market', 'limit');
CREATE TYPE order_status  AS ENUM (
    'proposed', 'risk_approved', 'risk_rejected',
    'submitted', 'partial', 'filled', 'cancelled', 'rejected', 'expired'
);
CREATE TYPE risk_decision AS ENUM ('approve', 'modify', 'reject');
CREATE TYPE agent_kind    AS ENUM ('chief', 'macro', 'industry', 'theme', 'stock', 'news');
CREATE TYPE data_quality  AS ENUM ('ok', 'suspect', 'corrected', 'missing');
```

### 2.2 标的主数据

```sql
-- ─────────────────────────────────────────────
-- 证券主表（不可变基础信息）
-- ─────────────────────────────────────────────
CREATE TABLE security (
    security_id   BIGSERIAL PRIMARY KEY,
    market        market_code NOT NULL,
    symbol        TEXT        NOT NULL,   -- 归一化代码，如 '600519.SH' / 'AAPL'
    raw_symbol    TEXT        NOT NULL,   -- 数据源原始代码
    name          TEXT        NOT NULL,
    name_en       TEXT,
    board         board_type,
    list_date     DATE,
    delist_date   DATE,                   -- NULL 表示仍上市
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

-- ─────────────────────────────────────────────
-- 证券名称/状态变更历史（区间有效）
-- ─────────────────────────────────────────────
CREATE TABLE security_status_history (
    security_id   BIGINT      NOT NULL REFERENCES security(security_id),
    valid_from    DATE        NOT NULL,
    valid_to      DATE,                   -- NULL = 至今
    name          TEXT        NOT NULL,
    status        listing_status NOT NULL,
    is_st         BOOLEAN     NOT NULL DEFAULT FALSE,   -- ST/*ST 标记
    st_reason     TEXT,
    source        TEXT        NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, valid_from)
);

COMMENT ON TABLE security_status_history IS
  'ST 状态影响涨跌停幅度(±5%)，必须按时点查询。';

CREATE INDEX idx_sec_status_range ON security_status_history
    (security_id, valid_from, valid_to);

-- ─────────────────────────────────────────────
-- 行业分类体系
-- ─────────────────────────────────────────────
CREATE TABLE industry_taxonomy (
    taxonomy_id   SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,   -- 'sw_2021' | 'gics' | 'citic'
    name          TEXT NOT NULL,
    market        market_code NOT NULL,
    levels        INT  NOT NULL           -- 层级数
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

-- ─────────────────────────────────────────────
-- 个股行业归属（区间有效 — 分类会调整）
-- ─────────────────────────────────────────────
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

-- ─────────────────────────────────────────────
-- 概念/题材板块（A 股特有，成分变化频繁）
-- ─────────────────────────────────────────────
CREATE TABLE theme (
    theme_id      BIGSERIAL PRIMARY KEY,
    market        market_code NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT NOT NULL,
    source        TEXT NOT NULL,          -- 'em' (东财) | 'ths' (同花顺)
    first_seen    DATE NOT NULL,
    description   TEXT,
    UNIQUE (market, source, code)
);

CREATE TABLE theme_member (
    theme_id      BIGINT NOT NULL REFERENCES theme(theme_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    valid_from    DATE   NOT NULL,
    valid_to      DATE,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (theme_id, security_id, valid_from)
);

CREATE INDEX idx_theme_member_lookup ON theme_member
    (theme_id, valid_from, valid_to);
```

### 2.3 股票池（时点快照）

```sql
-- ─────────────────────────────────────────────
-- 股票池定义
-- ─────────────────────────────────────────────
CREATE TABLE universe (
    universe_id   SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,   -- 'mvp_cn_50' | 'csi300' | 'sp500'
    name          TEXT NOT NULL,
    market        market_code NOT NULL,
    rule          JSONB,                  -- 若为规则生成，记录规则
    description   TEXT
);

-- ─────────────────────────────────────────────
-- 股票池成分快照 —— ★ 防生存者偏差的关键表
-- ─────────────────────────────────────────────
CREATE TABLE universe_snapshot (
    universe_id   INT    NOT NULL REFERENCES universe(universe_id),
    snapshot_date DATE   NOT NULL,
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    weight        NUMERIC(10,8),          -- 指数权重，若适用
    PRIMARY KEY (universe_id, snapshot_date, security_id)
);

COMMENT ON TABLE universe_snapshot IS
  '按日或按调仓日记录成分。回测必须查 snapshot_date <= as_of 的最近一期，'
  '禁止用当前成分回溯历史。';

CREATE INDEX idx_universe_snap ON universe_snapshot (universe_id, snapshot_date);
```

### 2.4 行情数据（TimescaleDB）

```sql
-- ─────────────────────────────────────────────
-- 日线（未复权原值 + 复权因子分离存储）
-- ─────────────────────────────────────────────
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
    -- A 股特有的成交约束标记
    limit_up_px     NUMERIC(18,4),        -- 当日涨停价
    limit_down_px   NUMERIC(18,4),        -- 当日跌停价
    is_limit_up     BOOLEAN,              -- 收盘是否封涨停
    is_limit_down   BOOLEAN,
    is_suspended    BOOLEAN NOT NULL DEFAULT FALSE,
    turnover_rate   NUMERIC(10,6),
    -- 质量与溯源
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

-- ─────────────────────────────────────────────
-- 复权因子（可修订 —— 除权除息会新增，历史因子也可能被数据源修正）
-- ─────────────────────────────────────────────
CREATE TABLE adjust_factor (
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    trade_date    DATE   NOT NULL,
    revision      INT    NOT NULL DEFAULT 1,
    announced_at  TIMESTAMPTZ NOT NULL,
    factor_qfq    NUMERIC(18,8) NOT NULL,   -- 前复权因子
    factor_hfq    NUMERIC(18,8) NOT NULL,   -- 后复权因子
    source        TEXT   NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, trade_date, revision)
);

COMMENT ON TABLE adjust_factor IS
  '存未复权价 + 因子，而非直接存复权价。因为前复权价会随每次除权变化，'
  '直接存复权价会导致历史数据被静默改写。';

-- ─────────────────────────────────────────────
-- 分钟线（按需，MVP 不用）
-- ─────────────────────────────────────────────
CREATE TABLE price_minute (
    security_id   BIGINT      NOT NULL REFERENCES security(security_id),
    ts            TIMESTAMPTZ NOT NULL,
    open          NUMERIC(18,4),
    high          NUMERIC(18,4),
    low           NUMERIC(18,4),
    close         NUMERIC(18,4),
    volume        BIGINT,
    amount        NUMERIC(20,2),
    source        TEXT        NOT NULL,
    PRIMARY KEY (security_id, ts)
);

SELECT create_hypertable('price_minute', 'ts',
                          chunk_time_interval => INTERVAL '1 month');

-- ─────────────────────────────────────────────
-- 资金流（A 股特色数据）
-- ─────────────────────────────────────────────
CREATE TABLE money_flow_daily (
    security_id       BIGINT NOT NULL REFERENCES security(security_id),
    trade_date        DATE   NOT NULL,
    main_net_inflow   NUMERIC(20,2),      -- 主力净流入
    super_large_net   NUMERIC(20,2),      -- 超大单
    large_net         NUMERIC(20,2),
    medium_net        NUMERIC(20,2),
    small_net         NUMERIC(20,2),
    northbound_hold   NUMERIC(20,2),      -- 北向持股（若适用）
    source            TEXT   NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_id, trade_date)
);

SELECT create_hypertable('money_flow_daily', 'trade_date',
                          chunk_time_interval => INTERVAL '1 year');

-- ─────────────────────────────────────────────
-- 交易日历（多市场）
-- ─────────────────────────────────────────────
CREATE TABLE trading_calendar (
    market        market_code NOT NULL,
    trade_date    DATE        NOT NULL,
    is_open       BOOLEAN     NOT NULL,
    prev_trade_date DATE,
    next_trade_date DATE,
    note          TEXT,
    PRIMARY KEY (market, trade_date)
);
```

### 2.5 财务数据（可修订）

```sql
-- ─────────────────────────────────────────────
-- 财务报表 —— ★ PIT 的典型场景
-- ─────────────────────────────────────────────
CREATE TABLE financial_statement (
    security_id     BIGINT NOT NULL REFERENCES security(security_id),
    period_end      DATE   NOT NULL,      -- 报告期末，如 2024-03-31
    period_type     TEXT   NOT NULL,      -- 'Q1'|'H1'|'Q3'|'FY'
    revision        INT    NOT NULL DEFAULT 1,
    announced_at    TIMESTAMPTZ NOT NULL, -- ★ 公告时间 = 可见时点
    report_type     TEXT   NOT NULL,      -- 'original'|'restated'|'audited'

    -- 利润表
    revenue         NUMERIC(20,2),
    operating_cost  NUMERIC(20,2),
    gross_profit    NUMERIC(20,2),
    operating_profit NUMERIC(20,2),
    net_profit      NUMERIC(20,2),
    net_profit_attr NUMERIC(20,2),        -- 归母净利润
    net_profit_deducted NUMERIC(20,2),    -- 扣非净利润
    eps             NUMERIC(12,6),

    -- 资产负债表
    total_assets    NUMERIC(20,2),
    total_liab      NUMERIC(20,2),
    total_equity    NUMERIC(20,2),
    equity_attr     NUMERIC(20,2),
    cash_and_equiv  NUMERIC(20,2),
    inventory       NUMERIC(20,2),
    accounts_recv   NUMERIC(20,2),
    goodwill        NUMERIC(20,2),

    -- 现金流量表
    cfo             NUMERIC(20,2),        -- 经营活动现金流
    cfi             NUMERIC(20,2),
    cff             NUMERIC(20,2),
    capex           NUMERIC(20,2),

    -- 溯源
    source          TEXT   NOT NULL,
    raw_ref         TEXT,                 -- 原始文件路径
    quality         data_quality NOT NULL DEFAULT 'ok',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (security_id, period_end, period_type, revision)
);

CREATE INDEX idx_fin_pit ON financial_statement
    (security_id, announced_at DESC, period_end DESC);

COMMENT ON TABLE financial_statement IS
  'PIT 查询：WHERE announced_at <= as_of，取每个 period 的最大 revision。'
  '禁止 UPDATE 已有行，修订必须 INSERT 新 revision。';

-- ─────────────────────────────────────────────
-- 财务指标（派生，但同样需要 PIT）
-- ─────────────────────────────────────────────
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

-- ─────────────────────────────────────────────
-- 估值（每日，基于当日价格 + 当时可见财务）
-- ─────────────────────────────────────────────
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

-- ─────────────────────────────────────────────
-- 宏观指标（多为可修订：初值/修正值）
-- ─────────────────────────────────────────────
CREATE TABLE macro_series (
    series_id     TEXT   PRIMARY KEY,     -- 'CN_CPI_YOY' | 'US_FEDFUNDS'
    name          TEXT   NOT NULL,
    region        TEXT   NOT NULL,
    frequency     TEXT   NOT NULL,        -- 'D'|'W'|'M'|'Q'|'A'
    unit          TEXT,
    source        TEXT   NOT NULL
);

CREATE TABLE macro_observation (
    series_id     TEXT   NOT NULL REFERENCES macro_series(series_id),
    period        DATE   NOT NULL,
    revision      INT    NOT NULL DEFAULT 1,
    announced_at  TIMESTAMPTZ NOT NULL,   -- ★ 发布时间，非期间
    value         NUMERIC(20,6),
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, period, revision)
);

COMMENT ON TABLE macro_observation IS
  'CPI 等指标 announced_at 通常滞后 period 一个月以上，'
  '回测中若用 period 过滤会引入未来函数。';
```

### 2.6 新闻与事件

```sql
-- ─────────────────────────────────────────────
-- 新闻原文
-- ─────────────────────────────────────────────
CREATE TABLE news (
    news_id       BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,   -- 'cls' | 'em' | 'sse_announce'
    source_id     TEXT,                   -- 源站唯一 ID，用于去重
    url           TEXT,
    title         TEXT        NOT NULL,
    body          TEXT,
    published_at  TIMESTAMPTZ NOT NULL,   -- ★ 可见时点
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    lang          CHAR(2)     NOT NULL DEFAULT 'zh',
    content_hash  TEXT        NOT NULL,   -- 正文哈希，用于去重
    raw_ref       TEXT,                   -- 原始归档路径
    UNIQUE (source, source_id)
);

CREATE INDEX idx_news_published ON news (published_at DESC);
CREATE INDEX idx_news_hash ON news (content_hash);
CREATE INDEX idx_news_title_trgm ON news USING gin (title gin_trgm_ops);

-- ─────────────────────────────────────────────
-- 新闻聚类（同一事件的多篇报道）
-- ─────────────────────────────────────────────
CREATE TABLE news_cluster (
    cluster_id    BIGSERIAL PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL,
    canonical_news_id BIGINT REFERENCES news(news_id),
    member_count  INT NOT NULL DEFAULT 1
);

CREATE TABLE news_cluster_member (
    cluster_id    BIGINT NOT NULL REFERENCES news_cluster(cluster_id),
    news_id       BIGINT NOT NULL REFERENCES news(news_id),
    similarity    NUMERIC(6,4),
    PRIMARY KEY (cluster_id, news_id)
);

-- ─────────────────────────────────────────────
-- 结构化事件（LLM 抽取产物）
-- ─────────────────────────────────────────────
CREATE TABLE event (
    event_id      BIGSERIAL PRIMARY KEY,
    news_id       BIGINT      REFERENCES news(news_id),
    cluster_id    BIGINT      REFERENCES news_cluster(cluster_id),
    occurred_at   TIMESTAMPTZ NOT NULL,   -- 事件发生时间
    visible_at    TIMESTAMPTZ NOT NULL,   -- ★ 可被系统知晓的时间
    event_type    TEXT        NOT NULL,   -- 'earnings'|'policy'|'product'|...
    summary       TEXT        NOT NULL,
    direction     TEXT,                   -- 'positive'|'negative'|'neutral'
    impact        NUMERIC(4,3),           -- 0-1
    horizon       TEXT,                   -- 'short'|'medium'|'long'
    confidence    NUMERIC(4,3),
    -- 抽取溯源
    extractor_model   TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    extracted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_visible ON event (visible_at DESC);
CREATE INDEX idx_event_type ON event (event_type, visible_at DESC);

COMMENT ON COLUMN event.visible_at IS
  '通常等于 news.published_at。回测过滤必须用此列，不可用 occurred_at。';

-- 事件 → 标的
CREATE TABLE event_security (
    event_id      BIGINT NOT NULL REFERENCES event(event_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    relation      TEXT   NOT NULL,        -- 'subject'|'supplier'|'customer'|'competitor'
    impact        NUMERIC(4,3),
    PRIMARY KEY (event_id, security_id, relation)
);

-- 事件 → 行业/主题
CREATE TABLE event_sector (
    event_id      BIGINT NOT NULL REFERENCES event(event_id),
    industry_id   BIGINT REFERENCES industry(industry_id),
    theme_id      BIGINT REFERENCES theme(theme_id),
    impact        NUMERIC(4,3),
    CHECK (industry_id IS NOT NULL OR theme_id IS NOT NULL)
);

-- ─────────────────────────────────────────────
-- 向量检索
-- ─────────────────────────────────────────────
CREATE TABLE document_chunk (
    chunk_id      BIGSERIAL PRIMARY KEY,
    doc_type      TEXT        NOT NULL,
    doc_ref       TEXT        NOT NULL,   -- 关联 ID
    security_id   BIGINT      REFERENCES security(security_id),
    chunk_index   INT         NOT NULL,
    content       TEXT        NOT NULL,
    visible_at    TIMESTAMPTZ NOT NULL,   -- ★ RAG 检索也必须 PIT 过滤
    expires_at    TIMESTAMPTZ,            -- ★ 知识类文档的失效时间
    embedding     vector(1024),
    embed_model   TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_doc_type CHECK (doc_type IN (
        'news', 'announcement', 'report', 'research',
        'knowledge', 'thesis', 'lesson'
    ))
);

CREATE INDEX idx_chunk_embedding ON document_chunk
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chunk_visible ON document_chunk (visible_at DESC);
CREATE INDEX idx_chunk_security ON document_chunk (security_id, visible_at DESC);

COMMENT ON TABLE document_chunk IS
  'RAG 检索必须加 WHERE visible_at <= as_of。否则回测中 Agent 会读到未来新闻。';
COMMENT ON COLUMN document_chunk.expires_at IS
  '知识类文档的失效时间（如已废止的监管规则）。检索需加 '
  '(expires_at IS NULL OR expires_at > :as_of)。'
  '否则回测历史时期会检索到当时尚未生效的规则 —— 隐蔽的未来函数。';
COMMENT ON COLUMN document_chunk.doc_type IS
  'thesis / lesson 为自有知识资产（P4），见 17-knowledge-base。'
  '注意 thesis 片段的 visible_at 是结果确认时间，非 thesis 写下时间。';
```

各 `doc_type` 的 `visible_at` 语义：

| doc_type | `visible_at` 取值 | 陷阱 |
|---|---|---|
| `announcement` | 公告披露时间 | 盘后披露的归属日 |
| `report`（年报） | **年报披露日，非报告期末** | 2025 年报在 2026-04 才可见 |
| `news` | 新闻发布时间 | 转载稿用原发时间 |
| `research` | 研报发布日 | |
| `knowledge` | 规则生效日 | 配 `expires_at` |
| `thesis` | **结果确认时间** | 片段含结果，写下时不可知 |
| `lesson` | 归因分析完成时间 | 不可被更早的回测检索到 |

### 2.7 因子与预测

```sql
-- ─────────────────────────────────────────────
-- 因子定义
-- ─────────────────────────────────────────────
CREATE TABLE factor_def (
    factor_id     SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,          -- 'momentum'|'value'|'quality'|'volatility'|'flow'
    formula       TEXT,                   -- 可读公式描述
    lookback_days INT,
    version       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────
-- 因子值（宽表存储在 Parquet，PG 只存元数据与小规模验证集）
-- ─────────────────────────────────────────────
CREATE TABLE factor_value (
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    trade_date    DATE   NOT NULL,
    factor_id     INT    NOT NULL REFERENCES factor_def(factor_id),
    raw_value     NUMERIC(20,8),
    zscore        NUMERIC(20,8),          -- 截面标准化
    rank_pct      NUMERIC(10,8),          -- 截面分位
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    code_version  TEXT NOT NULL,          -- 计算代码版本
    PRIMARY KEY (security_id, trade_date, factor_id)
);

SELECT create_hypertable('factor_value', 'trade_date',
                          chunk_time_interval => INTERVAL '1 year');

-- ─────────────────────────────────────────────
-- 模型注册
-- ─────────────────────────────────────────────
CREATE TABLE model_version (
    model_id      BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,          -- 'baseline'|'lightgbm'|...
    target        TEXT NOT NULL,          -- 'prob_up_5d'|'ret_20d'
    train_start   DATE NOT NULL,
    train_end     DATE NOT NULL,          -- ★ 用于校验预测不早于训练期
    feature_set   JSONB NOT NULL,
    hyperparams   JSONB NOT NULL,
    metrics       JSONB,                  -- 训练/验证指标
    artifact_path TEXT NOT NULL,
    code_version  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, train_end, code_version)
);

COMMENT ON COLUMN model_version.train_end IS
  '★ 回测校验规则：预测日期必须 > train_end，否则是数据泄漏。';

-- ─────────────────────────────────────────────
-- 预测输出
-- ─────────────────────────────────────────────
CREATE TABLE prediction (
    prediction_id BIGSERIAL PRIMARY KEY,
    model_id      BIGINT NOT NULL REFERENCES model_version(model_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    as_of_date    DATE   NOT NULL,        -- 预测基准日
    horizon       TEXT   NOT NULL,        -- '1d'|'5d'|'20d'
    prob_up       NUMERIC(6,5),
    expected_ret  NUMERIC(12,8),
    expected_vol  NUMERIC(12,8),
    quantiles     JSONB,                  -- {"p10": -0.05, "p50": 0.01, "p90": 0.08}
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model_id, security_id, as_of_date, horizon)
);

CREATE INDEX idx_pred_lookup ON prediction (as_of_date, horizon, security_id);

-- ─────────────────────────────────────────────
-- 预测实现值（事后回填，用于评估）
-- ─────────────────────────────────────────────
CREATE TABLE prediction_outcome (
    prediction_id BIGINT PRIMARY KEY REFERENCES prediction(prediction_id),
    actual_ret    NUMERIC(12,8),
    actual_vol    NUMERIC(12,8),
    hit           BOOLEAN,                -- 方向是否正确
    filled_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.8 Agent 输出与追溯

```sql
-- ─────────────────────────────────────────────
-- Agent 运行批次
-- ─────────────────────────────────────────────
CREATE TABLE agent_run (
    run_id        TEXT PRIMARY KEY,       -- '20260831-cn-daily'
    market        market_code NOT NULL,
    as_of_date    DATE NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL,          -- 'running'|'success'|'failed'|'aborted'
    total_tokens_in  BIGINT DEFAULT 0,
    total_tokens_out BIGINT DEFAULT 0,
    total_cost_usd   NUMERIC(12,6) DEFAULT 0,
    error         TEXT,
    config_hash   TEXT NOT NULL           -- 配置快照哈希
);

-- ─────────────────────────────────────────────
-- Agent 调用追踪（每次 LLM 调用一行）
-- ─────────────────────────────────────────────
CREATE TABLE agent_trace (
    trace_id      BIGSERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES agent_run(run_id),
    seq           INT  NOT NULL,
    agent_name    TEXT NOT NULL,
    agent_kind    agent_kind NOT NULL,
    tier          TEXT NOT NULL,
    model         TEXT NOT NULL,
    prompt_hash   TEXT NOT NULL,
    prompt_ref    TEXT,                   -- 完整 prompt 归档路径
    tool_calls    JSONB,                  -- 工具调用序列
    output        JSONB,                  -- 结构化输出
    tokens_in     INT NOT NULL,
    tokens_out    INT NOT NULL,
    cost_usd      NUMERIC(12,6),
    latency_ms    INT,
    schema_valid  BOOLEAN NOT NULL,
    retry_count   INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_trace_run ON agent_trace (run_id, seq);
CREATE INDEX idx_trace_agent ON agent_trace (agent_name, created_at DESC);

-- ─────────────────────────────────────────────
-- 成本控制相关列（见 16-token-economics）
-- ─────────────────────────────────────────────
ALTER TABLE agent_trace ADD COLUMN allocation TEXT;
    -- 预算分项: 'daily_research'|'monitoring'|'news_extraction'|'adhoc'
ALTER TABLE agent_trace ADD COLUMN cache_hit BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agent_trace ADD COLUMN batch_size INT NOT NULL DEFAULT 1;
ALTER TABLE agent_trace ADD COLUMN estimated_cost_without_cache NUMERIC(12,6);
ALTER TABLE agent_trace ADD COLUMN degraded BOOLEAN NOT NULL DEFAULT FALSE;
    -- 本次调用是否处于降级状态（如大模型降级为中模型）

CREATE INDEX idx_trace_allocation ON agent_trace (allocation, created_at DESC);

COMMENT ON COLUMN agent_trace.allocation IS
  '预算分项。各分项独立，互不挪用。用于成本归因。';
COMMENT ON COLUMN agent_trace.batch_size IS
  '批处理大小。>1 表示一次调用处理了多条输入，用于评估批处理效果。';

-- ─────────────────────────────────────────────
-- Agent 观点输出（结构化，供 Fusion 消费）
-- ─────────────────────────────────────────────
CREATE TABLE agent_view (
    view_id       BIGSERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES agent_run(run_id),
    trace_id      BIGINT REFERENCES agent_trace(trace_id),
    agent_kind    agent_kind NOT NULL,
    as_of_date    DATE NOT NULL,
    -- 目标：三者之一非空
    security_id   BIGINT REFERENCES security(security_id),
    industry_id   BIGINT REFERENCES industry(industry_id),
    theme_id      BIGINT REFERENCES theme(theme_id),
    -- 观点
    score         NUMERIC(5,4) NOT NULL,  -- 0-1
    confidence    NUMERIC(5,4) NOT NULL,
    horizon       TEXT NOT NULL,
    thesis        TEXT NOT NULL,
    signals       JSONB,                  -- 分维度评分
    bull_case     JSONB,
    bear_case     JSONB,
    risks         JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_view_lookup ON agent_view (as_of_date, agent_kind);

-- ─────────────────────────────────────────────
-- 证据引用 —— ★ 可追溯性的核心
-- ─────────────────────────────────────────────
CREATE TABLE agent_evidence (
    evidence_id   BIGSERIAL PRIMARY KEY,
    view_id       BIGINT NOT NULL REFERENCES agent_view(view_id),
    kind          TEXT NOT NULL,          -- 'news'|'event'|'financial'|'factor'|'price'
    ref_table     TEXT NOT NULL,
    ref_id        TEXT NOT NULL,
    excerpt       TEXT,
    visible_at    TIMESTAMPTZ NOT NULL,   -- 该证据的可见时点
    weight        NUMERIC(5,4)
);

CREATE INDEX idx_evidence_view ON agent_evidence (view_id);

COMMENT ON TABLE agent_evidence IS
  '校验规则：所有 evidence 的 visible_at 必须 <= agent_view.as_of_date 的收盘时刻。'
  '违反即为未来函数，该 view 作废。';
```

### 2.9 组合、风控、订单

```sql
-- ─────────────────────────────────────────────
-- 信号融合结果
-- ─────────────────────────────────────────────
CREATE TABLE fused_signal (
    run_id        TEXT   NOT NULL REFERENCES agent_run(run_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    as_of_date    DATE   NOT NULL,
    final_score   NUMERIC(6,5) NOT NULL,
    components    JSONB  NOT NULL,        -- {"quant":0.68,"news":0.88,...}
    weights       JSONB  NOT NULL,        -- 融合权重快照
    fusion_version TEXT  NOT NULL,
    PRIMARY KEY (run_id, security_id)
);

-- ─────────────────────────────────────────────
-- 目标组合
-- ─────────────────────────────────────────────
CREATE TABLE target_portfolio (
    run_id        TEXT   NOT NULL REFERENCES agent_run(run_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    as_of_date    DATE   NOT NULL,
    target_weight NUMERIC(8,6) NOT NULL,
    pre_risk_weight NUMERIC(8,6) NOT NULL, -- 风控前的原始权重
    reason        JSONB,
    PRIMARY KEY (run_id, security_id)
);

-- ─────────────────────────────────────────────
-- 风控审计
-- ─────────────────────────────────────────────
CREATE TABLE risk_audit (
    audit_id      BIGSERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES agent_run(run_id),
    as_of_date    DATE NOT NULL,
    decision      risk_decision NOT NULL,
    rule_config_hash TEXT NOT NULL,       -- 风控参数快照
    violations    JSONB NOT NULL,         -- 全部触发的规则，即使 approve
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_violation (
    audit_id      BIGINT NOT NULL REFERENCES risk_audit(audit_id),
    rule_code     TEXT   NOT NULL,
    severity      TEXT   NOT NULL,        -- 'hard'|'soft'
    security_id   BIGINT REFERENCES security(security_id),
    detail        JSONB  NOT NULL,
    action_taken  TEXT   NOT NULL         -- 'rejected'|'clipped'|'warned'
);

-- ─────────────────────────────────────────────
-- 账户与持仓
-- ─────────────────────────────────────────────
CREATE TABLE account (
    account_id    BIGSERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,   -- 'shadow_cn'|'paper_us'|'live_us'
    market        market_code NOT NULL,
    broker        TEXT NOT NULL,          -- 'simulated'|'alpaca'|'ibkr'|'qmt'
    is_live       BOOLEAN NOT NULL DEFAULT FALSE,
    base_currency CHAR(3) NOT NULL,
    initial_cash  NUMERIC(20,2) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE position (
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    as_of_date    DATE   NOT NULL,
    quantity      NUMERIC(20,4) NOT NULL,
    avg_cost      NUMERIC(18,6) NOT NULL,
    market_value  NUMERIC(20,2),
    unrealized_pnl NUMERIC(20,2),
    -- A 股 T+1 支持
    sellable_qty  NUMERIC(20,4) NOT NULL, -- 可卖数量（T+1 下当日买入不可卖）
    frozen_qty    NUMERIC(20,4) NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, security_id, as_of_date)
);

COMMENT ON COLUMN position.sellable_qty IS
  'A 股 T+1：当日买入部分不计入 sellable_qty。Risk Engine 必须校验。';

CREATE TABLE account_snapshot (
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    as_of_date    DATE   NOT NULL,
    total_value   NUMERIC(20,2) NOT NULL,
    cash          NUMERIC(20,2) NOT NULL,
    position_value NUMERIC(20,2) NOT NULL,
    daily_pnl     NUMERIC(20,2),
    cum_pnl       NUMERIC(20,2),
    drawdown      NUMERIC(10,6),
    PRIMARY KEY (account_id, as_of_date)
);

-- ─────────────────────────────────────────────
-- 订单
-- ─────────────────────────────────────────────
CREATE TABLE order_proposal (
    proposal_id   BIGSERIAL PRIMARY KEY,
    run_id        TEXT   NOT NULL REFERENCES agent_run(run_id),
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    as_of_date    DATE   NOT NULL,
    side          order_side NOT NULL,
    target_weight NUMERIC(8,6),
    quantity      NUMERIC(20,4),
    order_type    order_type NOT NULL,
    limit_price   NUMERIC(18,4),
    reason        JSONB  NOT NULL,
    confidence    NUMERIC(5,4),
    risk_audit_id BIGINT REFERENCES risk_audit(audit_id),
    status        order_status NOT NULL DEFAULT 'proposed',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE broker_order (
    order_id      BIGSERIAL PRIMARY KEY,
    proposal_id   BIGINT NOT NULL REFERENCES order_proposal(proposal_id),
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    client_order_id TEXT NOT NULL UNIQUE, -- ★ 幂等键
    broker_order_id TEXT,
    side          order_side NOT NULL,
    quantity      NUMERIC(20,4) NOT NULL,
    order_type    order_type NOT NULL,
    limit_price   NUMERIC(18,4),
    status        order_status NOT NULL,
    filled_qty    NUMERIC(20,4) NOT NULL DEFAULT 0,
    avg_fill_price NUMERIC(18,6),
    submitted_at  TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reject_reason TEXT
);

COMMENT ON COLUMN broker_order.client_order_id IS
  '幂等键，防止重复下单。格式: {run_id}-{security}-{side}-{seq}';

CREATE TABLE fill (
    fill_id       BIGSERIAL PRIMARY KEY,
    order_id      BIGINT NOT NULL REFERENCES broker_order(order_id),
    broker_fill_id TEXT,
    quantity      NUMERIC(20,4) NOT NULL,
    price         NUMERIC(18,6) NOT NULL,
    commission    NUMERIC(18,6) NOT NULL DEFAULT 0,
    tax           NUMERIC(18,6) NOT NULL DEFAULT 0,   -- 印花税等
    other_fees    NUMERIC(18,6) NOT NULL DEFAULT 0,
    filled_at     TIMESTAMPTZ NOT NULL,
    UNIQUE (order_id, broker_fill_id)
);

-- ─────────────────────────────────────────────
-- 对账
-- ─────────────────────────────────────────────
CREATE TABLE reconciliation (
    recon_id      BIGSERIAL PRIMARY KEY,
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    as_of_date    DATE   NOT NULL,
    status        TEXT   NOT NULL,        -- 'matched'|'mismatch'
    local_snapshot  JSONB NOT NULL,
    broker_snapshot JSONB NOT NULL,
    diffs         JSONB,
    resolved      BOOLEAN NOT NULL DEFAULT FALSE,
    resolution    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 2.10 决策日志与评估

```sql
-- ─────────────────────────────────────────────
-- 决策日志 —— ★ append-only，禁止 UPDATE/DELETE
-- ─────────────────────────────────────────────
CREATE TABLE decision_journal (
    decision_id   BIGSERIAL PRIMARY KEY,
    run_id        TEXT   NOT NULL REFERENCES agent_run(run_id),
    as_of_date    DATE   NOT NULL,
    security_id   BIGINT REFERENCES security(security_id),
    industry_id   BIGINT REFERENCES industry(industry_id),
    theme_id      BIGINT REFERENCES theme(theme_id),

    -- 决策内容
    action        TEXT   NOT NULL,        -- 'buy'|'sell'|'hold'|'watch'
    target_weight NUMERIC(8,6),
    prev_weight   NUMERIC(8,6),

    -- 决策时的上下文快照
    market_regime TEXT,
    fused_score   NUMERIC(6,5),
    signal_components JSONB,
    prediction    JSONB,
    thesis        TEXT,
    evidence_ids  BIGINT[],

    -- 版本溯源
    model_ids     BIGINT[],
    agent_versions JSONB,
    fusion_version TEXT,
    risk_config_hash TEXT,
    code_version  TEXT NOT NULL,

    -- 预期
    expected_ret_5d  NUMERIC(12,8),
    expected_ret_20d NUMERIC(12,8),
    confidence    NUMERIC(5,4),

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_journal_date ON decision_journal (as_of_date DESC);
CREATE INDEX idx_journal_security ON decision_journal (security_id, as_of_date DESC);

-- 禁止修改的触发器
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_journal_no_update
    BEFORE UPDATE OR DELETE ON decision_journal
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ─────────────────────────────────────────────
-- 决策结果回填（独立表，因为 journal 不可改）
-- ─────────────────────────────────────────────
CREATE TABLE decision_outcome (
    decision_id   BIGINT PRIMARY KEY REFERENCES decision_journal(decision_id),
    ret_1d        NUMERIC(12,8),
    ret_5d        NUMERIC(12,8),
    ret_20d       NUMERIC(12,8),
    ret_60d       NUMERIC(12,8),
    excess_ret_5d NUMERIC(12,8),          -- 相对基准
    excess_ret_20d NUMERIC(12,8),
    max_dd_20d    NUMERIC(12,8),
    hit_5d        BOOLEAN,
    hit_20d       BOOLEAN,
    filled_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────
-- 历史判断的可检索视图（P4，见 17-knowledge-base）
-- ─────────────────────────────────────────────
CREATE VIEW v_thesis_with_outcome AS
SELECT
    j.decision_id,
    j.as_of_date,
    j.security_id,
    j.action,
    j.thesis,
    j.confidence,
    j.expected_ret_20d,
    o.ret_20d           AS actual_ret_20d,
    o.excess_ret_20d,
    o.hit_20d,
    CASE
        WHEN o.hit_20d IS NULL                   THEN 'pending'
        WHEN o.hit_20d AND j.confidence > 0.7    THEN 'confident_correct'
        WHEN o.hit_20d                           THEN 'correct'
        WHEN NOT o.hit_20d AND j.confidence > 0.7 THEN 'confident_wrong'
        ELSE 'wrong'
    END AS quality_label
FROM decision_journal j
LEFT JOIN decision_outcome o USING (decision_id)
WHERE j.thesis IS NOT NULL;

COMMENT ON VIEW v_thesis_with_outcome IS
  'confident_wrong 是最有学习价值的样本：高信心但判断错误，'
  '说明当时的推理链有系统性缺陷。'
  '入 document_chunk 时 visible_at 必须用结果确认时间，非 as_of_date。';

-- ─────────────────────────────────────────────
-- 回测运行记录
-- ─────────────────────────────────────────────
CREATE TABLE backtest_run (
    backtest_id   BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    strategy_code TEXT NOT NULL,
    universe_id   INT  NOT NULL REFERENCES universe(universe_id),
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    market_config_hash TEXT NOT NULL,
    params        JSONB NOT NULL,
    code_version  TEXT NOT NULL,
    -- 结果
    metrics       JSONB,
    -- ★ 过拟合防护
    param_search_count INT NOT NULL DEFAULT 1,  -- 本次调参累计次数
    used_holdout  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN backtest_run.param_search_count IS
  '记录同一策略累计尝试的参数组合数。数值越大，回测结果的可信度越低。';
COMMENT ON COLUMN backtest_run.used_holdout IS
  '是否动用了封存期数据。封存期原则上只能用一次。';

-- ─────────────────────────────────────────────
-- 撮合假设校准记录（P7b-1，见 ADR-0012）
-- ★ append-only
-- ─────────────────────────────────────────────
CREATE TABLE matching_calibration (
    calibration_id BIGSERIAL PRIMARY KEY,
    calibrated_at  DATE   NOT NULL,
    broker         TEXT   NOT NULL,        -- 'qmt_sim'|'ptrade_sim'
    n_orders       INT    NOT NULL,

    -- 逐项假设的验证结果（NULL = 该场景未覆盖）
    limit_up_rejected     BOOLEAN,
    limit_down_rejected   BOOLEAN,
    suspended_rejected    BOOLEAN,
    partial_fill_match    BOOLEAN,

    -- 数值偏差
    fill_price_mae        NUMERIC(10,6),   -- 成交价平均绝对误差
    fill_qty_match_rate   NUMERIC(5,4),    -- 成交量一致率

    -- 诚实记录
    uncovered_scenarios   TEXT[] NOT NULL DEFAULT '{}',
    notes                 TEXT,

    -- 后续动作
    simulator_fixed       BOOLEAN NOT NULL DEFAULT FALSE,
    backtests_rerun       BOOLEAN NOT NULL DEFAULT FALSE,
    conclusions_changed   BOOLEAN,         -- ★ 结论是否翻转
    code_version          TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_calibration_no_update
    BEFORE UPDATE OR DELETE ON matching_calibration
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

COMMENT ON TABLE matching_calibration IS
  '撮合假设校准记录。SimulatedBroker 的涨跌停/成交量/集合竞价规则都是假设，'
  '而全部回测结论建立在其上。本表记录假设与真实撮合的对比结果。'
  '★ 偏差不设通过门槛 —— 目的是知道偏差多大，不是让它变小。'
  '设门槛然后调参数满足，等于把校准变成过拟合。';
COMMENT ON COLUMN matching_calibration.conclusions_changed IS
  'TRUE 表示修正假设后历史回测结论翻转，此前评估作废。'
  '触发 12-roadmap 第 6 节退出条件。';
COMMENT ON COLUMN matching_calibration.uncovered_scenarios IS
  '未覆盖的场景（如停牌订单无机会尝试）。诚实记录比假装全覆盖重要。';

-- ─────────────────────────────────────────────
-- 数据质量监控
-- ─────────────────────────────────────────────
CREATE TABLE data_quality_check (
    check_id      BIGSERIAL PRIMARY KEY,
    check_date    DATE NOT NULL,
    dataset       TEXT NOT NULL,
    rule_code     TEXT NOT NULL,
    status        TEXT NOT NULL,          -- 'pass'|'warn'|'fail'
    expected      JSONB,
    actual        JSONB,
    affected_count INT,
    detail        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_dq_date ON data_quality_check (check_date DESC, status);

-- ─────────────────────────────────────────────
-- 采集批次记录（可重放的基础）
-- ─────────────────────────────────────────────
CREATE TABLE ingest_batch (
    batch_id      BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    dataset       TEXT NOT NULL,
    target_date   DATE,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL,
    row_count     INT,
    raw_path      TEXT,                   -- Parquet 归档路径
    error         TEXT,
    retry_of      BIGINT REFERENCES ingest_batch(batch_id)
);
```

### 2.11 监控与推送（P2a）

```sql
-- ─────────────────────────────────────────────
-- 手动维护的持仓（A 股阶段，无 API）
-- ─────────────────────────────────────────────
CREATE TABLE manual_position (
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    quantity      NUMERIC(20,4) NOT NULL,
    avg_cost      NUMERIC(18,6) NOT NULL,
    entry_date    DATE NOT NULL,
    -- 用于止损/回撤类触发器
    entry_high    NUMERIC(18,4),          -- 建仓后最高价（滚动更新）
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by    TEXT NOT NULL,          -- 'manual'|'import'|'cli'|'bot'
    PRIMARY KEY (account_id, security_id)
);

COMMENT ON COLUMN manual_position.updated_at IS
  '持仓时效性检查依据。超 5 个交易日未更新则推送提醒。';

-- ─────────────────────────────────────────────
-- 关注列表（非持仓但需监控）
-- ─────────────────────────────────────────────
CREATE TABLE watchlist (
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason        TEXT,
    target_price  NUMERIC(18,4),          -- 可选：期望买入价
    PRIMARY KEY (account_id, security_id)
);

-- ─────────────────────────────────────────────
-- 实时行情快照（盘中，仅持仓 + 关注列表）
-- ─────────────────────────────────────────────
CREATE TABLE price_snapshot (
    security_id     BIGINT      NOT NULL REFERENCES security(security_id),
    ts              TIMESTAMPTZ NOT NULL,
    last            NUMERIC(18,4),
    open            NUMERIC(18,4),
    high            NUMERIC(18,4),
    low             NUMERIC(18,4),
    prev_close      NUMERIC(18,4),
    volume          BIGINT,
    amount          NUMERIC(20,2),
    -- 触发器判断所需
    is_limit_up     BOOLEAN,
    is_limit_down   BOOLEAN,
    is_suspended    BOOLEAN NOT NULL DEFAULT FALSE,
    source          TEXT        NOT NULL,
    PRIMARY KEY (security_id, ts)
);

SELECT create_hypertable('price_snapshot', 'ts',
                          chunk_time_interval => INTERVAL '1 week');

-- 快照数据保留期短（仅用于盘中触发判断）
SELECT add_retention_policy('price_snapshot', INTERVAL '30 days');

COMMENT ON TABLE price_snapshot IS
  '盘中快照，仅覆盖持仓+关注列表。保留 30 天后自动清理。'
  '不作为历史数据来源（历史用 price_daily）。';

-- ─────────────────────────────────────────────
-- 推送告警 —— ★ 监控层核心表
-- ─────────────────────────────────────────────
CREATE TABLE alert (
    alert_id       TEXT PRIMARY KEY,      -- 确定性生成，见下
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    account_id     BIGINT REFERENCES account(account_id),
    severity       TEXT NOT NULL,         -- 'critical'|'high'|'medium'|'info'

    -- 内容
    title          TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    current_state  TEXT NOT NULL,
    suggestion     TEXT,

    -- 关联
    symbols        TEXT[] NOT NULL,
    trigger_codes  TEXT[] NOT NULL,
    evidence_refs  TEXT[],
    run_id         TEXT REFERENCES agent_run(run_id),

    -- ★ 成本透明
    analysis_level TEXT NOT NULL,         -- 'L1'|'L2'|'L3'
    cost_usd       NUMERIC(12,6) NOT NULL DEFAULT 0,

    -- 投递
    channels       TEXT[] NOT NULL,
    delivered_at   TIMESTAMPTZ,
    delivery_error TEXT,
    retry_count    INT NOT NULL DEFAULT 0,

    -- 反馈（用于评估推送质量）
    feedback       TEXT,                  -- 'useful'|'not_useful'|'ignored'
    feedback_at    TIMESTAMPTZ
);

CREATE INDEX idx_alert_created ON alert (created_at DESC);
CREATE INDEX idx_alert_trigger ON alert USING gin (trigger_codes);
CREATE INDEX idx_alert_symbols ON alert USING gin (symbols);
CREATE INDEX idx_alert_severity ON alert (severity, created_at DESC);

COMMENT ON COLUMN alert.alert_id IS
  '确定性生成: {date}-{trigger_code}-{symbol}-{seq}。'
  '配合冷却期实现幂等，防止重复推送。';
COMMENT ON COLUMN alert.cost_usd IS
  'L1 触发为 0。用于计算「单条有用推送成本」这一质量指标。';

-- ─────────────────────────────────────────────
-- 触发器抑制状态（冷却期跟踪）
-- ─────────────────────────────────────────────
CREATE TABLE trigger_cooldown (
    account_id    BIGINT NOT NULL REFERENCES account(account_id),
    trigger_code  TEXT   NOT NULL,
    security_id   BIGINT REFERENCES security(security_id),
    last_fired_at TIMESTAMPTZ NOT NULL,
    fire_count_today INT NOT NULL DEFAULT 1,
    muted_until   TIMESTAMPTZ,            -- 用户手动静音
    PRIMARY KEY (account_id, trigger_code, security_id)
);

-- ─────────────────────────────────────────────
-- 触发器质量统计（评估与淘汰依据）
-- ─────────────────────────────────────────────
CREATE VIEW v_trigger_quality AS
SELECT
    unnest(trigger_codes)              AS trigger_code,
    count(*)                           AS n_alerts,
    sum(cost_usd)                      AS total_cost,
    count(feedback)                    AS n_feedback,
    avg(CASE WHEN feedback = 'useful'     THEN 1.0
             WHEN feedback = 'not_useful' THEN 0.0 END) AS useful_rate,
    -- ★ 单位价值：每条有用推送的成本
    sum(cost_usd) / nullif(count(*) FILTER (WHERE feedback = 'useful'), 0)
                                       AS cost_per_useful
FROM alert
WHERE created_at > now() - interval '90 days'
GROUP BY 1
ORDER BY n_alerts DESC;

COMMENT ON VIEW v_trigger_quality IS
  'useful_rate < 0.20 的触发器应考虑关闭或提高阈值。'
  'cost_per_useful > 0.30 说明该触发器成本效益差。';

-- ─────────────────────────────────────────────
-- 预算使用跟踪（按日按分项）
-- ─────────────────────────────────────────────
CREATE TABLE budget_usage (
    usage_date    DATE   NOT NULL,
    allocation    TEXT   NOT NULL,        -- 预算分项
    spent_usd     NUMERIC(12,6) NOT NULL DEFAULT 0,
    limit_usd     NUMERIC(12,6) NOT NULL,
    call_count    INT    NOT NULL DEFAULT 0,
    degraded_count INT   NOT NULL DEFAULT 0,
    exceeded_at   TIMESTAMPTZ,            -- 首次超限时间
    PRIMARY KEY (usage_date, allocation)
);

COMMENT ON TABLE budget_usage IS
  '各分项独立，互不挪用。exceeded_at 非空表示当日曾触发降级。';
```

### 2.12 建仓推荐（P5，见 09 文档第 8 节）

```sql
-- ─────────────────────────────────────────────
-- 建仓推荐 —— ★ append-only，对抗 R-21 选择性记忆
-- ─────────────────────────────────────────────
CREATE TABLE recommendation (
    rec_id         BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date     DATE   NOT NULL,
    account_id     BIGINT REFERENCES account(account_id),
    run_id         TEXT   REFERENCES agent_run(run_id),

    -- 输入参数（决定了推荐内容，必须记录）
    capital        NUMERIC(20,2) NOT NULL,   -- 账户总额（仅记录）
    investable     NUMERIC(20,2) NOT NULL,   -- ★ 用户本次投入，组合的唯一资金基准
    stance         TEXT   NOT NULL,        -- ChiefAgent 的 allocation_stance
    target_exposure NUMERIC(5,4) NOT NULL, -- stance 映射后的总仓位
    tradable_boards TEXT[] NOT NULL,       -- ★ 生成时用户可交易的板块，影响候选范围，必须记录才能复现

    -- 结论
    action         TEXT   NOT NULL,        -- 'build'|'no_position'
    n_items        INT    NOT NULL DEFAULT 0,
    highest_score  NUMERIC(6,5),           -- ★ no_position 时必填，告知差多少
    min_score_cfg  NUMERIC(6,5) NOT NULL,
    next_review_date DATE,

    -- 分批计划
    tranches       INT    NOT NULL DEFAULT 1,
    interval_days  INT,

    -- 整手取整结果
    residual_cash  NUMERIC(20,2),
    max_weight_deviation NUMERIC(6,5),     -- 目标 vs 实际的最大偏差

    -- 时效
    expires_at     TIMESTAMPTZ NOT NULL,

    -- 溯源
    portfolio_config_hash TEXT NOT NULL,
    risk_config_hash      TEXT NOT NULL,
    code_version   TEXT   NOT NULL
);

CREATE TRIGGER trg_rec_no_update
    BEFORE UPDATE OR DELETE ON recommendation
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE INDEX idx_rec_date ON recommendation (as_of_date DESC);

COMMENT ON TABLE recommendation IS
  'append-only。R-21（建议模式自欺）的工程缓解：让全部推荐都无法被事后删改，'
  '避免只记住对的那些。';
COMMENT ON COLUMN recommendation.capital IS
  '账户总额，仅供展示投入比例。组合计算不用它。';
COMMENT ON COLUMN recommendation.investable IS
  '★ 用户本次愿意投入的金额，是 top_n、整手取整、单票上限的唯一基准。'
  '用户只投一部分时，用 investable 重算组合，而非按 capital 算完打折 —— '
  '打折会让某些标的达不到一手，破坏整手可行性。';
COMMENT ON COLUMN recommendation.highest_score IS
  'action = no_position 时必填。用户需知道最高分距门槛差多少。';

-- ─────────────────────────────────────────────
-- 推荐明细
-- ─────────────────────────────────────────────
CREATE TABLE recommendation_item (
    rec_id         BIGINT NOT NULL REFERENCES recommendation(rec_id),
    security_id    BIGINT NOT NULL REFERENCES security(security_id),

    -- 目标
    target_weight  NUMERIC(8,6) NOT NULL,
    actual_weight  NUMERIC(8,6) NOT NULL,  -- 整手取整后
    total_lots     INT    NOT NULL,        -- 全部批次合计手数
    ref_price      NUMERIC(18,4) NOT NULL,
    limit_price_low  NUMERIC(18,4),
    limit_price_high NUMERIC(18,4),

    -- 依据
    fused_score    NUMERIC(6,5) NOT NULL,
    rationale      TEXT,
    evidence_ids   BIGINT[],

    PRIMARY KEY (rec_id, security_id)
);

-- ─────────────────────────────────────────────
-- 因资金量被排除的标的（★ 必须记录并展示）
-- ─────────────────────────────────────────────
CREATE TABLE recommendation_excluded (
    rec_id         BIGINT NOT NULL REFERENCES recommendation(rec_id),
    security_id    BIGINT NOT NULL REFERENCES security(security_id),
    fused_score    NUMERIC(6,5) NOT NULL,
    exclusion_code TEXT   NOT NULL,        -- 'CAPITAL_LOT'|'BOARD_NOT_ELIGIBLE'|'SUSPENDED'|'ST'|...
    detail         JSONB,                  -- CAPITAL_LOT: {lot_value:33600, cap:10000}
                                           -- BOARD_NOT_ELIGIBLE: {board:'star', req:'50万+24月'}
    PRIMARY KEY (rec_id, security_id)
);

COMMENT ON TABLE recommendation_excluded IS
  '分数不低但无法买入的标的，按原因分类：'
  'CAPITAL_LOT（资金量不足一手）、BOARD_NOT_ELIGIBLE（未开通板块权限）等。'
  '必须在输出中按原因分别展示 —— 让用户知道错过了什么，以及加资金/开权限能解锁什么。';

-- ─────────────────────────────────────────────
-- 分批建仓计划与执行
-- ─────────────────────────────────────────────
CREATE TABLE scale_in_tranche (
    rec_id         BIGINT NOT NULL REFERENCES recommendation(rec_id),
    tranche_no     INT    NOT NULL,
    ratio          NUMERIC(5,4) NOT NULL,  -- 本批占计划比例
    planned_date   DATE   NOT NULL,

    -- ★ 每批当时的市场判断（exposure 逐批可能不同，归因需要）
    stance_at_tranche TEXT,                -- 该批执行时的 allocation_stance
    target_exposure   NUMERIC(5,4),        -- 该批对应的目标仓位（investable 内）

    -- 执行状态
    status         TEXT   NOT NULL DEFAULT 'planned',
                   -- 'planned'|'executed'|'skipped'|'aborted'
    executed_date  DATE,
    decision       TEXT,                   -- ScaleInDecision.action
    decision_reason TEXT,
    PRIMARY KEY (rec_id, tranche_no)
);

COMMENT ON COLUMN scale_in_tranche.decision IS
  'proceed | skip_this_tranche | abort_remaining | replace | increase_exposure。'
  '★ abort_remaining 只停止后续加仓，不卖出已建仓部分。'
  'increase_exposure：stance 转好时在 investable 上限内追加，永不动用未投入资金。'
  '卖出决策一律走正常调仓流程与风控，不由建仓计划决定。';
COMMENT ON COLUMN scale_in_tranche.target_exposure IS
  '受 recommendation.investable 硬约束：任何批次的累计投入不得超过 investable。'
  '未投入资金（investable 之外）永不被分批计划触碰。';

-- ─────────────────────────────────────────────
-- 执行反馈（用户实际买了多少）
-- ─────────────────────────────────────────────
CREATE TABLE recommendation_execution (
    rec_id         BIGINT NOT NULL REFERENCES recommendation(rec_id),
    security_id    BIGINT NOT NULL REFERENCES security(security_id),
    executed_lots  INT    NOT NULL DEFAULT 0,
    executed_price NUMERIC(18,4),
    executed_at    TIMESTAMPTZ,
    not_executed_reason TEXT,              -- '涨停'|'改主意'|'资金不足'|...
    PRIMARY KEY (rec_id, security_id)
);

-- ─────────────────────────────────────────────
-- 执行率与推荐质量（对抗选择性记忆）
-- ─────────────────────────────────────────────
CREATE VIEW v_recommendation_quality AS
SELECT
    r.rec_id,
    r.as_of_date,
    r.action,
    r.n_items,
    count(e.security_id) FILTER (WHERE e.executed_lots > 0) AS n_executed,
    CASE WHEN r.n_items > 0
         THEN count(e.security_id) FILTER (WHERE e.executed_lots > 0)::numeric
              / r.n_items
    END AS execution_rate,
    -- ★ 归因用 shadow，不用用户实际执行
    avg(o.excess_ret_20d) AS avg_excess_ret_20d_shadow
FROM recommendation r
LEFT JOIN recommendation_item i USING (rec_id)
LEFT JOIN recommendation_execution e USING (rec_id, security_id)
LEFT JOIN decision_journal j
       ON j.security_id = i.security_id AND j.as_of_date = r.as_of_date
LEFT JOIN decision_outcome o USING (decision_id)
GROUP BY r.rec_id, r.as_of_date, r.action, r.n_items;

COMMENT ON VIEW v_recommendation_quality IS
  '★ 归因必须用 shadow portfolio 的结果（avg_excess_ret_20d_shadow），'
  '不能用用户实际执行的部分 —— 否则「只买了涨的那几只」会让统计失真。'
  'execution_rate 持续偏低说明推荐不可执行（资金/整手/涨停），需调整参数。';

-- ─────────────────────────────────────────────
-- 止盈止损建议触发记录（P5，见 09 文档 4.2a）
-- ─────────────────────────────────────────────
CREATE TABLE exit_signal (
    exit_signal_id BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    account_id     BIGINT REFERENCES account(account_id),
    security_id    BIGINT NOT NULL REFERENCES security(security_id),

    kind           TEXT   NOT NULL,        -- 'stop_loss'|'trailing_stop'|'take_profit'|'target_price'
    trigger_price  NUMERIC(18,4) NOT NULL,
    holding_return NUMERIC(8,5),           -- 触发时相对成本的浮盈亏
    suggested_action TEXT NOT NULL,        -- 'sell_all'|'reduce_33'|'reduce_50'|...

    -- ★ 触发时的策略快照，否则无法复盘"当时为什么建议卖"
    policy_snapshot JSONB NOT NULL,        -- 用户 exit_policy 的当时值

    -- 用户处理
    user_action    TEXT,                   -- 'followed'|'ignored'|'partial'|null(未响应)
    resolved_at    TIMESTAMPTZ
);

CREATE INDEX idx_exit_signal_acct ON exit_signal (account_id, created_at DESC);

COMMENT ON TABLE exit_signal IS
  '止盈止损是建议不是自动执行（A 股阶段）。policy_snapshot 记录触发时用户的阈值配置，'
  '因为阈值可被用户随时修改，不快照就无法复盘。user_action 用于分析用户是否遵守自己的纪律。';
COMMENT ON COLUMN exit_signal.policy_snapshot IS
  '注意：这是用户配置的止盈止损，不是 DD_005 系统兜底。系统兜底走 risk_audit。';
```

## 3. PIT 查询模式

### 3.1 标准查询模板

```sql
-- ① 可修订数据：取 as_of 时可见的最新版本
CREATE OR REPLACE VIEW v_financial_pit AS
SELECT * FROM financial_statement;   -- 由函数封装，见下

CREATE OR REPLACE FUNCTION get_financials_as_of(
    p_security_ids BIGINT[],
    p_as_of        TIMESTAMPTZ,
    p_periods      INT DEFAULT 8
) RETURNS SETOF financial_statement AS $$
    SELECT DISTINCT ON (security_id, period_end, period_type) *
    FROM financial_statement
    WHERE security_id = ANY(p_security_ids)
      AND announced_at <= p_as_of          -- ★ PIT 过滤
    ORDER BY security_id, period_end DESC, period_type, revision DESC
    LIMIT p_periods * array_length(p_security_ids, 1);
$$ LANGUAGE sql STABLE;

-- ② 区间有效数据：取 as_of 落在区间内的记录
CREATE OR REPLACE FUNCTION get_industry_as_of(
    p_security_ids BIGINT[],
    p_as_of        DATE,
    p_taxonomy     TEXT DEFAULT 'sw_2021'
) RETURNS TABLE (security_id BIGINT, industry_code TEXT, industry_name TEXT, level INT) AS $$
    SELECT si.security_id, i.code, i.name, i.level
    FROM security_industry si
    JOIN industry i ON i.industry_id = si.industry_id
    JOIN industry_taxonomy t ON t.taxonomy_id = i.taxonomy_id
    WHERE si.security_id = ANY(p_security_ids)
      AND t.code = p_taxonomy
      AND si.valid_from <= p_as_of
      AND (si.valid_to IS NULL OR si.valid_to > p_as_of);   -- ★ 区间过滤
$$ LANGUAGE sql STABLE;

-- ③ 股票池：取 as_of 之前最近一次快照
CREATE OR REPLACE FUNCTION get_universe_as_of(
    p_universe_code TEXT,
    p_as_of         DATE
) RETURNS TABLE (security_id BIGINT, weight NUMERIC) AS $$
    WITH latest AS (
        SELECT max(us.snapshot_date) AS d
        FROM universe_snapshot us
        JOIN universe u ON u.universe_id = us.universe_id
        WHERE u.code = p_universe_code
          AND us.snapshot_date <= p_as_of        -- ★
    )
    SELECT us.security_id, us.weight
    FROM universe_snapshot us
    JOIN universe u ON u.universe_id = us.universe_id
    JOIN latest ON us.snapshot_date = latest.d
    WHERE u.code = p_universe_code;
$$ LANGUAGE sql STABLE;

-- ④ 复权价：未复权价 × as_of 时可见的复权因子
CREATE OR REPLACE FUNCTION get_prices_as_of(
    p_security_ids BIGINT[],
    p_start        DATE,
    p_end          DATE,
    p_as_of        TIMESTAMPTZ,
    p_adjust       TEXT DEFAULT 'qfq'
) RETURNS TABLE (
    security_id BIGINT, trade_date DATE,
    open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
    volume BIGINT, is_limit_up BOOLEAN, is_limit_down BOOLEAN, is_suspended BOOLEAN
) AS $$
    WITH af AS (
        SELECT DISTINCT ON (security_id, trade_date)
               security_id, trade_date, factor_qfq, factor_hfq
        FROM adjust_factor
        WHERE security_id = ANY(p_security_ids)
          AND announced_at <= p_as_of                -- ★ 因子也要 PIT
        ORDER BY security_id, trade_date, revision DESC
    )
    SELECT p.security_id, p.trade_date,
           p.open  * COALESCE(f.factor_qfq, 1),
           p.high  * COALESCE(f.factor_qfq, 1),
           p.low   * COALESCE(f.factor_qfq, 1),
           p.close * COALESCE(f.factor_qfq, 1),
           p.volume, p.is_limit_up, p.is_limit_down, p.is_suspended
    FROM price_daily p
    LEFT JOIN af f USING (security_id, trade_date)
    WHERE p.security_id = ANY(p_security_ids)
      AND p.trade_date BETWEEN p_start AND p_end
      AND p.trade_date <= p_as_of::date               -- ★
    ORDER BY p.security_id, p.trade_date;
$$ LANGUAGE sql STABLE;

-- ⑤ RAG 检索：向量相似 + PIT 过滤
CREATE OR REPLACE FUNCTION search_chunks_as_of(
    p_embedding vector(1024),
    p_as_of     TIMESTAMPTZ,
    p_limit     INT DEFAULT 10,
    p_security_id BIGINT DEFAULT NULL
) RETURNS TABLE (chunk_id BIGINT, content TEXT, distance FLOAT) AS $$
    SELECT c.chunk_id, c.content, c.embedding <=> p_embedding
    FROM document_chunk c
    WHERE c.visible_at <= p_as_of                     -- ★ 必须
      AND (p_security_id IS NULL OR c.security_id = p_security_id)
    ORDER BY c.embedding <=> p_embedding
    LIMIT p_limit;
$$ LANGUAGE sql STABLE;
```

### 3.2 Repository 层封装

```python
class PITRepository:
    """所有 as_of 逻辑封装在此，业务代码不写 SQL。"""

    def get_financials(
        self, symbols: list[str], *, as_of: date, periods: int = 8
    ) -> pl.DataFrame:
        sec_ids = self._resolve(symbols)
        rows = self._conn.execute(
            "SELECT * FROM get_financials_as_of(%s, %s, %s)",
            (sec_ids, self._eod(as_of), periods),
        ).fetchall()
        return pl.DataFrame(rows).with_columns(
            pl.lit(as_of).alias("_as_of"),      # 携带溯源信息
        )

    @staticmethod
    def _eod(d: date) -> datetime:
        """as_of 日期转为该日收盘时刻。
        决策在收盘后做，所以当日收盘数据可见，但次日数据不可见。"""
        return datetime.combine(d, time(15, 0), tzinfo=CN_TZ)
```

## 4. 防未来函数的工程手段

单靠 schema 设计不够，需要多层防护。

### 4.1 静态检查

```python
# tools/lint_pit.py — 加入 CI
FORBIDDEN_PATTERNS = [
    # 研究/回测代码中直接写 SQL
    (r"(quant|portfolio|risk|agents)/.*\.py", r"(SELECT|select)\s+.*\s+FROM"),
    # 不带 as_of 调用 repository
    (r".*\.py", r"repo\.get_\w+\([^)]*\)(?!.*as_of)"),
    # 直接读 price_daily 表
    (r"(quant|agents)/.*\.py", r"price_daily"),
]
```

### 4.2 运行时断言

```python
def assert_no_lookahead(df: pl.DataFrame, as_of: date, time_col: str) -> None:
    """所有数据行的时间戳必须 <= as_of。"""
    if df.is_empty():
        return
    max_ts = df[time_col].max()
    if max_ts > as_of:
        raise LookaheadError(
            f"Data contains {time_col}={max_ts} > as_of={as_of}"
        )

# Repository 每个方法返回前调用
# 回测引擎每步循环后调用
# Agent evidence 落库前调用
```

### 4.3 Evidence 时点校验

```python
def validate_evidence(view: AgentView, as_of: date) -> None:
    """Agent 引用的证据不能来自未来。"""
    cutoff = eod(as_of)
    for ev in view.evidence:
        if ev.visible_at > cutoff:
            raise LookaheadError(
                f"Agent {view.agent} cited future evidence: "
                f"{ev.ref_id} visible_at={ev.visible_at} > {cutoff}"
            )
```

### 4.4 模型训练期校验

```python
def validate_prediction(pred: Prediction, model: ModelVersion) -> None:
    """预测日必须晚于训练结束日。"""
    if pred.as_of_date <= model.train_end:
        raise LookaheadError(
            f"Model {model.name} trained until {model.train_end} "
            f"cannot predict {pred.as_of_date}"
        )
```

### 4.5 回测专用哨兵测试

```python
def test_backtest_is_pit_clean():
    """向未来日期注入极端假数据，回测结果不应变化。
    这是检测未来函数最有效的测试。"""
    baseline = run_backtest(start="2023-01-01", end="2023-06-30")

    # 在 2023-07 之后插入荒谬数据
    inject_fake_data(date_from="2023-07-01", multiplier=100)

    after = run_backtest(start="2023-01-01", end="2023-06-30")

    assert baseline.metrics == after.metrics, "未来数据影响了历史回测 → 存在未来函数"
```

这个测试应该在 P0 就写好，作为 Gate 1 的验收项。

## 5. 数据分区与生命周期

| 表 | 分区策略 | 保留期 |
|---|---|---|
| `price_daily` | TimescaleDB，1 年/chunk | 永久 |
| `price_minute` | TimescaleDB，1 月/chunk | 2 年后压缩 |
| `price_snapshot` | TimescaleDB，1 周/chunk | **30 天自动清理** |
| `factor_value` | TimescaleDB，1 年/chunk | 永久 |
| `news` | 无分区（量小） | 永久 |
| `document_chunk` | 无分区 | 永久 |
| `agent_trace` | 按月手动归档 | 明细 1 年，之后仅保留聚合 |
| `alert` | 无分区 | 永久（质量评估需要长期数据） |
| `trigger_cooldown` | 无分区 | 仅当前状态，无历史 |
| `budget_usage` | 无分区 | 永久（量极小） |
| `decision_journal` | 无 | 永久，append-only |
| `recommendation` | 无 | 永久，append-only（对抗选择性记忆） |
| `matching_calibration` | 无 | 永久，append-only（量极小） |

压缩配置：

```sql
ALTER TABLE price_minute SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'security_id'
);
SELECT add_compression_policy('price_minute', INTERVAL '2 years');
```

## 6. 迁移管理

使用 Alembic，约定：

| 约定 | 说明 |
|---|---|
| 一个变更一个迁移 | 不合并多个逻辑变更 |
| 必须可回滚 | 每个 migration 写 `downgrade()` |
| 数据迁移与结构迁移分离 | 结构变更快速，数据回填单独脚本 |
| 禁止破坏历史 | 不 DROP 含数据的列，先标记废弃 |

```
migrations/
├── versions/
│   ├── 0001_initial_security_master.py
│   ├── 0002_price_hypertables.py
│   ├── 0003_financial_pit.py
│   ├── 0004_news_and_events.py
│   ├── 0005_factor_and_model.py
│   ├── 0006_agent_trace.py
│   ├── 0007_portfolio_risk_order.py
│   ├── 0008_decision_journal.py
│   ├── 0009_monitor_positions.py       # P2a: manual_position, watchlist
│   ├── 0010_price_snapshot.py          # P2a: 盘中快照
│   ├── 0011_alerts.py                  # P2a: alert, trigger_cooldown
│   ├── 0012_cost_tracking.py           # P2: agent_trace 增补列, budget_usage
│   ├── 0013_knowledge_expiry.py        # P2: document_chunk.expires_at, doc_type 约束
│   ├── 0014_recommendation.py          # P5: recommendation 系列表 + exit_signal + 视图
│   └── 0015_matching_calibration.py    # P7b-1: 撮合假设校准记录
```

## 7. 数据模型检查清单

P0 验收时逐项确认：

- [ ] 所有可修订表有 `announced_at` + `revision`
- [ ] 所有区间表有 `valid_from` / `valid_to`
- [ ] 退市股票保留在 `security`，有 `delist_date`
- [ ] `universe_snapshot` 有历史成分，不是当前成分
- [ ] 存未复权价 + 复权因子，不存复权价
- [ ] `price_daily` 有 `is_limit_up/down`、`is_suspended`
- [ ] `position` 有 `sellable_qty`（T+1）
- [ ] `document_chunk` 有 `visible_at` 且 RAG 查询强制过滤
- [ ] `decision_journal` 有 append-only 触发器
- [ ] `broker_order` 有 `client_order_id` 唯一约束（幂等）
- [ ] `model_version` 有 `train_end` 且预测时校验
- [ ] 所有 PIT 查询封装为 SQL 函数或 Repository 方法
- [ ] 未来函数哨兵测试通过

P2/P2a 追加：

- [ ] `agent_trace` 有 `allocation` / `cache_hit` / `batch_size` 列
- [ ] `budget_usage` 按日按分项记录
- [ ] `alert.alert_id` 确定性生成（配合冷却期实现幂等）
- [ ] `alert.cost_usd` 记录（L1 为 0）
- [ ] `v_trigger_quality` 视图可查
- [ ] `price_snapshot` 有 30 天保留策略
- [ ] `manual_position.updated_at` 用于时效性检查
- [ ] `trigger_cooldown` 支持手动静音（`muted_until`）
- [ ] `document_chunk.expires_at` 存在，检索双向过滤
- [ ] 年报 chunk 的 `visible_at` = 披露日（非报告期末）
- [ ] `v_thesis_with_outcome` 视图可查（P4）
- [ ] thesis chunk 的 `visible_at` = 结果确认时间（P4，有测试）

P5 追加：

- [ ] `recommendation` append-only 触发器生效
- [ ] `recommendation.capital` 记录（推荐结果可复现）
- [ ] `recommendation_excluded` 记录因资金量/板块权限排除的标的
- [ ] `recommendation.tradable_boards` 记录（板块权限影响候选，需可复现）
- [ ] `recommendation.investable` 记录（组合基于可投入资金而非账户总额）
- [ ] `exit_signal.policy_snapshot` 记录触发时的用户阈值配置
- [ ] `scale_in_tranche` 分批状态可跟踪
- [ ] `v_recommendation_quality` 的归因用 shadow 而非用户实际执行

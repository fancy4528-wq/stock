-- P2: news originals + structured events (visible_at is the PIT key).

CREATE TABLE news (
    news_id       BIGSERIAL PRIMARY KEY,
    source        TEXT        NOT NULL,   -- 'cls' | 'em' | 'em_announce'
    source_id     TEXT,                   -- vendor unique id (nullable for hash-only rows)
    url           TEXT,
    title         TEXT        NOT NULL,
    body          TEXT,
    published_at  TIMESTAMPTZ NOT NULL,   -- ★ visible time
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    lang          CHAR(2)     NOT NULL DEFAULT 'zh',
    content_hash  TEXT        NOT NULL,
    raw_ref       TEXT,
    UNIQUE (source, source_id)
);

CREATE INDEX idx_news_published ON news (published_at DESC);
CREATE INDEX idx_news_hash ON news (source, content_hash);

COMMENT ON COLUMN news.published_at IS
  'News/announcement publish time = system-visible as_of for PIT reads.';

CREATE TABLE event (
    event_id      BIGSERIAL PRIMARY KEY,
    news_id       BIGINT      REFERENCES news(news_id),
    occurred_at   TIMESTAMPTZ NOT NULL,
    visible_at    TIMESTAMPTZ NOT NULL,   -- ★ PIT filter (usually = news.published_at)
    event_type    TEXT        NOT NULL,
    summary       TEXT        NOT NULL,
    direction     TEXT,                   -- positive|negative|neutral|unclear
    impact        NUMERIC(4,3),
    horizon       TEXT,                   -- immediate|short|medium|long
    confidence    NUMERIC(4,3),
    figures       JSONB       NOT NULL DEFAULT '[]'::jsonb,
    extractor_model   TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    extracted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_visible ON event (visible_at DESC);
CREATE INDEX idx_event_type ON event (event_type, visible_at DESC);
CREATE INDEX idx_event_news ON event (news_id);

COMMENT ON COLUMN event.visible_at IS
  'Usually equals news.published_at. Backtests must filter on this, not occurred_at.';

CREATE TABLE event_security (
    event_id      BIGINT NOT NULL REFERENCES event(event_id) ON DELETE CASCADE,
    security_id   BIGINT NOT NULL REFERENCES security(security_id),
    relation      TEXT   NOT NULL,        -- subject|supplier|customer|competitor|peer
    impact        NUMERIC(4,3),
    PRIMARY KEY (event_id, security_id, relation)
);

CREATE INDEX idx_event_security_sec ON event_security (security_id);

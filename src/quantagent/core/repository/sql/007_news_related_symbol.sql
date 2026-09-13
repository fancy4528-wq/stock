-- Persist announcement stock code / type hints for rule_v1 extraction.

ALTER TABLE news
    ADD COLUMN IF NOT EXISTS related_symbol TEXT,
    ADD COLUMN IF NOT EXISTS announce_type TEXT;

CREATE INDEX IF NOT EXISTS idx_news_related_symbol
    ON news (related_symbol)
    WHERE related_symbol IS NOT NULL;

COMMENT ON COLUMN news.related_symbol IS
  'Optional CN ticker (e.g. 600519.SH) from announcement 代码; used as extract hint.';
COMMENT ON COLUMN news.announce_type IS
  'Optional East Money announcement type label for event_type mapping.';

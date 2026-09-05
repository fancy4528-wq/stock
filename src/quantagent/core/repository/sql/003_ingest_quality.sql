-- W3: ingest batch tracking + data quality check persistence.

CREATE TABLE IF NOT EXISTS data_quality_check (
    check_id       BIGSERIAL PRIMARY KEY,
    check_date     DATE NOT NULL,
    dataset        TEXT NOT NULL,
    rule_code      TEXT NOT NULL,
    status         TEXT NOT NULL,          -- 'pass'|'warn'|'fail'
    expected       JSONB,
    actual         JSONB,
    affected_count INT,
    detail         TEXT,
    batch_id       BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dq_date ON data_quality_check (check_date DESC, status);
CREATE INDEX IF NOT EXISTS idx_dq_batch ON data_quality_check (batch_id);

CREATE TABLE IF NOT EXISTS ingest_batch (
    batch_id      BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    dataset       TEXT NOT NULL,
    target_date   DATE,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL,          -- 'running'|'success'|'failed'|'partial'
    row_count     INT,
    raw_path      TEXT,
    error         TEXT,
    retry_of      BIGINT REFERENCES ingest_batch(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_batch_dataset
    ON ingest_batch (dataset, target_date DESC);

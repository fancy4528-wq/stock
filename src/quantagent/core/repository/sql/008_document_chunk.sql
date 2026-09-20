-- P2 RAG: document_chunk + PIT-filtered search (pgvector).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_chunk (
    chunk_id      BIGSERIAL PRIMARY KEY,
    doc_type      TEXT        NOT NULL,
    doc_ref       TEXT        NOT NULL,   -- e.g. news:12345
    security_id   BIGINT      REFERENCES security(security_id),
    chunk_index   INT         NOT NULL,
    content       TEXT        NOT NULL,
    visible_at    TIMESTAMPTZ NOT NULL,   -- ★ RAG retrieval PIT filter
    expires_at    TIMESTAMPTZ,            -- ★ knowledge expiry (ADR-0011)
    embedding     vector(1024),
    embed_model   TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_doc_type CHECK (doc_type IN (
        'news', 'announcement', 'report', 'research',
        'knowledge', 'thesis', 'lesson'
    )),
    CONSTRAINT uq_document_chunk_ref_index UNIQUE (doc_ref, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunk_embedding ON document_chunk
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunk_visible ON document_chunk (visible_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunk_security ON document_chunk (security_id, visible_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunk_doc_ref ON document_chunk (doc_ref);

COMMENT ON TABLE document_chunk IS
  'RAG retrieval must filter WHERE visible_at <= as_of. '
  'Also (expires_at IS NULL OR expires_at > as_of).';
COMMENT ON COLUMN document_chunk.expires_at IS
  'Knowledge expiry. Without this filter, backtests can retrieve rules '
  'that were not yet in force — a subtle lookahead.';
COMMENT ON COLUMN document_chunk.doc_type IS
  'thesis / lesson are own-knowledge assets (P4). '
  'announcement / news / report are K2 (P2).';

-- ★ Unique RAG entrypoint: cosine distance + bidirectional time filter.
CREATE OR REPLACE FUNCTION search_chunks_as_of(
    p_embedding   vector(1024),
    p_as_of       TIMESTAMPTZ,
    p_limit       INT DEFAULT 10,
    p_security_id BIGINT DEFAULT NULL
) RETURNS TABLE (
    chunk_id    BIGINT,
    content     TEXT,
    doc_type    TEXT,
    doc_ref     TEXT,
    security_id BIGINT,
    visible_at  TIMESTAMPTZ,
    distance    FLOAT
) AS $$
    SELECT
        c.chunk_id,
        c.content,
        c.doc_type,
        c.doc_ref,
        c.security_id,
        c.visible_at,
        (c.embedding <=> p_embedding)::FLOAT AS distance
    FROM document_chunk c
    WHERE c.embedding IS NOT NULL
      AND c.visible_at <= p_as_of
      AND (c.expires_at IS NULL OR c.expires_at > p_as_of)
      AND (p_security_id IS NULL OR c.security_id = p_security_id)
    ORDER BY c.embedding <=> p_embedding
    LIMIT p_limit;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION search_chunks_as_of IS
  'Sole RAG search entry. Enforces visible_at <= as_of and expires_at > as_of.';

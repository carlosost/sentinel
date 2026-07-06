-- Sentinel database schema (ADR-010, ADR-024)
-- Run once against the Postgres instance before `make ingest`.
-- Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS vector;

-- Documents table: one row per ingested corpus chunk.
-- embedding dimension (1536) must match sentinel-embedding's output dimension
-- (text-embedding-3-small). If you swap the primary embedding model, you must
-- drop and recreate this table AND re-run `make ingest` — see docs/SWAPPING_MODELS.md.
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,           -- SHA-256 content hash (idempotent upsert key)
    corpus      TEXT NOT NULL,              -- "runbooks" | "postmortems" | "infra_code_docs"
    content     TEXT NOT NULL,
    embedding   vector(1536) NOT NULL,
    metadata    JSONB
);

-- ivfflat index for approximate cosine-similarity search.
-- lists=100 is a reasonable default for corpora up to ~1M rows;
-- tune with `SET ivfflat.probes` at query time for recall vs. speed tradeoff.
CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Index on corpus for the WHERE corpus = %s filter applied before the ANN search.
CREATE INDEX IF NOT EXISTS documents_corpus_idx ON documents (corpus);

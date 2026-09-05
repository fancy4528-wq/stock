-- Drop W3 ingest / quality tables (run before 900_drop_p0 core tables).

DROP TABLE IF EXISTS data_quality_check CASCADE;
DROP TABLE IF EXISTS ingest_batch CASCADE;

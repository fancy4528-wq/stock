# Research validation log (Gate 2)

Append-only live / smoke research DAG outcomes (schema / evidence / PIT / untraceable / cost).

| UTC | run_id | as_of | mode | agents | fatal | warn | untraceable | llm_calls | schema_fails | schema_pass | usd | overall |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2026-10-11T08:04:36.850166+00:00 | 20260930-cn-daily | 2026-09-30 | heuristic | 14 | 0 | 0 | 0 | 0 | 0 | 100.0% | $0.0000 | FAIL |
| 2026-10-11T08:29:07.706635+00:00 | 20260930-cn-daily | 2026-09-30 | llm | 14 | 0 | 0 | 0 | 22 | 0 | 100.0% | $0.0122 | PASS |
| 2026-10-11T08:34:46.892391+00:00 | 20260930-cn-daily | 2026-09-30 | llm_partial | 14 | 0 | 0 | 0 | 22 | 1 | 95.5% | $0.0218 | PASS |

# LLM cost log

Append-only notes from ReporterAgent / later Agents
(allocation = ADR-0010 budget pool: daily_research | monitoring | news_extraction | adhoc).

| UTC | run_id | agent | allocation | model | mode | prompt | completion | USD |
|---|---|---|---|---|---|---:|---:|---:|
| 2026-09-12T07:21:14.027836+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T07:23:32.586709+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T07:23:54.266410+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T07:24:38.549589+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T07:25:05.215330+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T08:32:00.488366+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T08:34:56.747448+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-12T09:34:10.117767+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-13T05:13:26.093696+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-13T05:13:55.831922+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-13T05:14:55.315786+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-13T05:25:19.556067+00:00 | 20260904-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-13T05:25:21.810047+00:00 | 20260904-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-14T14:40:31.715573+00:00 | 20260914-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-14T14:46:07.104581+00:00 | 20260914-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-15T10:15:58.380617+00:00 | 20260915-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-16T10:18:42.081783+00:00 | 20260916-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-17T10:18:36.067385+00:00 | 20260917-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-18T10:18:45.328317+00:00 | 20260918-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-20T07:02:23.602625+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-21T10:26:08.710598+00:00 | 20260921-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-22T11:28:44.952524+00:00 | 20260922-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-23T10:16:42.356557+00:00 | 20260923-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-24T10:19:20.531613+00:00 | 20260924-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-28T10:18:56.888516+00:00 | 20260928-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-29T11:40:05.339505+00:00 | 20260929-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-30T10:07:17.696507+00:00 | 20260930-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |
| 2026-09-30T10:13:07.336493+00:00 | 20260930-cn-daily | reporter | daily_research | deterministic | deterministic | 0 | 0 | 0.0000 |

## Gate 2b funnel replay (2026-10-03)

Window: 2026-09-02 ... 2026-09-30 (20 CN sessions). Holdings: `600519.SH, 000858.SZ, 300750.SZ`. Mode: **heuristic**. Cutoff 18:00 Asia/Shanghai, flash lookback 24h.

| Gate 2b | Actual | Threshold | Result |
|---|---|---|---|
| L1 pass rate | 0.00% | < 5% | PASS |
| L2 → L3 rate | n/a | < 25% | n/a |
| L3 max / day | 0 | ≤ 10 | PASS |
| Monitor USD / day | $0.0000 | < $0.30 | PASS |
| L2 cache hit rate | n/a (heuristic L2 not cached) | > 15% | n/a |

Totals: scanned=2504 L1_pass=0 L2_rel=0 L2_deep=0 L3=0 USD=$0.0000 ($0.0000/day).

| as_of | scanned | L1 pass | L1 rate | L2 rel | L2 drop | L2 deep | L3 | ANN hits | cache hit/miss | USD | L2 mode | L3 mode |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| 2026-09-02 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-03 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 2 | 0/0 | $0.0000 | - | - |
| 2026-09-04 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 2 | 0/0 | $0.0000 | - | - |
| 2026-09-07 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-08 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-09 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-10 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-11 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 1 | 0/0 | $0.0000 | - | - |
| 2026-09-14 | 57 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-15 | 346 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-16 | 212 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-17 | 217 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-18 | 207 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-21 | 201 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-22 | 171 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-23 | 260 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-24 | 201 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-28 | 181 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-29 | 178 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-09-30 | 273 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |

- D-class corpus = news.source in (cls, em); em_announce is C-class and excluded from L1.
- Fetch window is PIT-closed: published_at in (cutoff-lookback, cutoff]; cls/em flash ingest in this DB starts 2026-09-12.
- One cycle per session (not 3-minute polling). Heuristic L2 does not write the analysis cache (LLM-only).
- L1 requires entity match AND keyword severity >= medium; holding-name mentions without keywords do not pass.
- Sessions=20; days with D-class flash=12.

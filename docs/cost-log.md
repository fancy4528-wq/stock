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

## Gate 2 research-live (2026-09-30)

run_id=`20260930-cn-daily` mode=`heuristic` overall=FAIL

| Gate 2 | Actual | Threshold | Result |
|---|---|---|---|
| schema_pass_rate | 100.0% | >= 95% | PASS |
| evidence_coverage | 100% | 100% | PASS |
| pit_violations | 0 | 0 | PASS |
| avg_untraceable_per_agent | 0.00 | < 1 | PASS |
| daily_research_usd | $0.0000 | <= $0.80 | PASS |
| total_usd_vs_daily_cap | $0.0000 | <= $1.50 | PASS |
| llm_path | heuristic | llm (not heuristic) | FAIL |

| 2026-10-11T08:28:46.279090+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 998 | 750 | 0.0003 |
| 2026-10-11T08:28:47.212661+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1100 | 1061 | 0.0005 |
| 2026-10-11T08:28:47.751096+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1059 | 1190 | 0.0005 |
| 2026-10-11T08:28:47.970401+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1004 | 1160 | 0.0005 |
| 2026-10-11T08:28:48.006479+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 998 | 1101 | 0.0004 |
| 2026-10-11T08:28:48.500942+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 1965 | 719 | 0.0005 |
| 2026-10-11T08:28:50.429660+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2619 | 1052 | 0.0007 |
| 2026-10-11T08:28:51.325539+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2560 | 1092 | 0.0007 |
| 2026-10-11T08:28:51.514079+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2695 | 1205 | 0.0007 |
| 2026-10-11T08:28:51.610857+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2619 | 1151 | 0.0007 |
| 2026-10-11T08:28:55.330058+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1121 | 0.0005 |
| 2026-10-11T08:28:55.585795+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1167 | 0.0005 |
| 2026-10-11T08:28:55.667982+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1214 | 0.0005 |
| 2026-10-11T08:28:55.694422+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1102 | 0.0005 |
| 2026-10-11T08:28:58.874470+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2595 | 1112 | 0.0007 |
| 2026-10-11T08:28:59.129336+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2674 | 1205 | 0.0007 |
| 2026-10-11T08:28:59.814527+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1196 | 0.0005 |
| 2026-10-11T08:28:59.892309+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1245 | 0.0005 |
| 2026-10-11T08:29:02.463572+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1140 | 0.0005 |
| 2026-10-11T08:29:03.967077+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1071 | 1556 | 0.0006 |
| 2026-10-11T08:29:06.389938+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2628 | 1131 | 0.0007 |
| 2026-10-11T08:29:07.695851+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2877 | 1287 | 0.0008 |
| 2026-10-11T08:29:07.698976+00:00 | 20260930-cn-daily | chief | daily_research | budget_skip | budget_skip | 0 | 0 | 0.0000 |

## Gate 2 research-live (2026-09-30)

run_id=`20260930-cn-daily` mode=`llm` overall=PASS

| Gate 2 | Actual | Threshold | Result |
|---|---|---|---|
| schema_pass_rate | 100.0% | >= 95% | PASS |
| evidence_coverage | 100% | 100% | PASS |
| pit_violations | 0 | 0 | PASS |
| avg_untraceable_per_agent | 0.00 | < 1 | PASS |
| daily_research_usd | $0.0122 | <= $0.80 | PASS |
| total_usd_vs_daily_cap | $0.0122 | <= $1.50 | PASS |
| llm_path | llm | llm (not heuristic) | PASS |

| 2026-10-11T08:34:11.608135+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 998 | 794 | 0.0004 |
| 2026-10-11T08:34:12.295893+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 998 | 950 | 0.0004 |
| 2026-10-11T08:34:12.410253+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1059 | 1010 | 0.0004 |
| 2026-10-11T08:34:12.447123+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1100 | 1046 | 0.0004 |
| 2026-10-11T08:34:12.534181+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1004 | 989 | 0.0004 |
| 2026-10-11T08:34:14.253592+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 2310 | 750 | 0.0005 |
| 2026-10-11T08:34:15.356120+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2423 | 941 | 0.0006 |
| 2026-10-11T08:34:15.694037+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2468 | 980 | 0.0006 |
| 2026-10-11T08:34:19.069294+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1053 | 0.0004 |
| 2026-10-11T08:34:19.231204+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1116 | 0.0005 |
| 2026-10-11T08:34:19.517621+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1146 | 0.0005 |
| 2026-10-11T08:34:19.561662+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1125 | 0.0005 |
| 2026-10-11T08:34:22.957277+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2599 | 1116 | 0.0007 |
| 2026-10-11T08:34:23.219287+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1255 | 0.0005 |
| 2026-10-11T08:34:23.489554+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1201 | 0.0005 |
| 2026-10-11T08:34:23.581952+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1200 | 0.0005 |
| 2026-10-11T08:34:26.824412+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2731 | 1246 | 0.0007 |
| 2026-10-11T08:34:26.829566+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2680 | 1191 | 0.0007 |
| 2026-10-11T08:34:27.068770+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2681 | 1192 | 0.0007 |
| 2026-10-11T08:34:27.875517+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1071 | 1559 | 0.0006 |
| 2026-10-11T08:34:31.563345+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2841 | 1355 | 0.0008 |
| 2026-10-11T08:34:46.884279+00:00 | 20260930-cn-daily | chief | daily_research | deepseek-flash | llm | 2686 | 4096 | 0.0104 |

## Gate 2 research-live (2026-09-30)

run_id=`20260930-cn-daily` mode=`llm_partial` overall=PASS

| Gate 2 | Actual | Threshold | Result |
|---|---|---|---|
| schema_pass_rate | 95.5% | >= 95% | PASS |
| evidence_coverage | 100% | 100% | PASS |
| pit_violations | 0 | 0 | PASS |
| avg_untraceable_per_agent | 0.00 | < 1 | PASS |
| daily_research_usd | $0.0218 | <= $0.80 | PASS |
| total_usd_vs_daily_cap | $0.0218 | <= $1.50 | PASS |
| llm_path | llm_partial | llm (not heuristic) | PASS |


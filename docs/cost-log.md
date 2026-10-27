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

| 2026-10-11T08:57:10.650617+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1004 | 832 | 0.0004 |
| 2026-10-11T08:57:10.786573+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 998 | 710 | 0.0003 |
| 2026-10-11T08:57:11.345137+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 998 | 1002 | 0.0004 |
| 2026-10-11T08:57:11.378683+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1059 | 1019 | 0.0004 |
| 2026-10-11T08:57:11.558092+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1100 | 1054 | 0.0004 |
| 2026-10-11T08:57:13.339199+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2320 | 823 | 0.0006 |
| 2026-10-11T08:57:14.844126+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2475 | 993 | 0.0006 |
| 2026-10-11T08:57:14.863305+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2612 | 1045 | 0.0007 |
| 2026-10-11T08:57:18.232868+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 882 | 0.0004 |
| 2026-10-11T08:57:18.993653+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1132 | 0.0005 |
| 2026-10-11T08:57:19.180327+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1156 | 0.0005 |
| 2026-10-11T08:57:20.961840+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2382 | 887 | 0.0006 |
| 2026-10-11T08:57:21.015581+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1812 | 0.0007 |
| 2026-10-11T08:57:22.909088+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2630 | 1147 | 0.0007 |
| 2026-10-11T08:57:23.255927+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1134 | 0.0005 |
| 2026-10-11T08:57:24.901808+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1102 | 0.0005 |
| 2026-10-11T08:57:25.253352+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 3071 | 1312 | 0.0008 |
| 2026-10-11T08:57:26.978678+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1201 | 0.0005 |
| 2026-10-11T08:57:27.132001+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2618 | 1125 | 0.0007 |
| 2026-10-11T08:57:29.925312+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1071 | 1494 | 0.0006 |
| 2026-10-11T08:57:30.772263+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2681 | 1213 | 0.0007 |
| 2026-10-11T08:57:33.857880+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2776 | 1290 | 0.0007 |
| 2026-10-11T08:57:49.880093+00:00 | 20260930-cn-daily | chief | daily_research | deepseek-flash | llm | 2157 | 3562 | 0.0090 |
| 2026-10-11T08:58:07.062325+00:00 | 20260930-cn-daily | chief | daily_research | deepseek-flash | llm | 4239 | 4096 | 0.0113 |

## Gate 2 research-live (2026-09-30)

run_id=`20260930-cn-daily` mode=`llm_partial` overall=PASS

| Gate 2 | Actual | Threshold | Result |
|---|---|---|---|
| schema_pass_rate | 95.8% | >= 95% | PASS |
| evidence_coverage | 100% | 100% | PASS |
| pit_violations | 0 | 0 | PASS |
| avg_untraceable_per_agent | 0.00 | < 1 | PASS |
| daily_research_usd | $0.0323 | <= $0.80 | PASS |
| total_usd_vs_daily_cap | $0.0323 | <= $1.50 | PASS |
| llm_path | llm_partial | llm (not heuristic) | PASS |

| 2026-10-11T09:00:05.290646+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 998 | 826 | 0.0004 |
| 2026-10-11T09:00:05.500876+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 998 | 750 | 0.0003 |
| 2026-10-11T09:00:05.936948+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1059 | 1007 | 0.0004 |
| 2026-10-11T09:00:06.481543+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1100 | 1076 | 0.0005 |
| 2026-10-11T09:00:06.966563+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 1004 | 1137 | 0.0005 |
| 2026-10-11T09:00:07.858153+00:00 | 20260930-cn-daily | macro | daily_research | deepseek-flash | llm | 1825 | 706 | 0.0005 |
| 2026-10-11T09:00:08.099052+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2121 | 817 | 0.0005 |
| 2026-10-11T09:00:10.406926+00:00 | 20260930-cn-daily | industry | daily_research | deepseek-flash | llm | 2151 | 993 | 0.0006 |
| 2026-10-11T09:00:14.488567+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1062 | 0.0004 |
| 2026-10-11T09:00:14.652263+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1104 | 0.0005 |
| 2026-10-11T09:00:14.723399+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1056 | 1230 | 0.0005 |
| 2026-10-11T09:00:14.888899+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1203 | 0.0005 |
| 2026-10-11T09:00:18.604669+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2170 | 1151 | 0.0006 |
| 2026-10-11T09:00:18.941843+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1066 | 1167 | 0.0005 |
| 2026-10-11T09:00:19.089285+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1219 | 0.0005 |
| 2026-10-11T09:00:19.249804+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1070 | 1165 | 0.0005 |
| 2026-10-11T09:00:22.558537+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 1071 | 1202 | 0.0005 |
| 2026-10-11T09:00:23.259161+00:00 | 20260930-cn-daily | stock | daily_research | deepseek-flash | llm | 2185 | 1142 | 0.0006 |
| 2026-10-11T09:00:25.996573+00:00 | 20260930-cn-daily | chief | daily_research | deepseek-flash | llm | 2332 | 566 | 0.0005 |

## Gate 2 research-live (2026-09-30)

run_id=`20260930-cn-daily` mode=`llm` overall=PASS

| Gate 2 | Actual | Threshold | Result |
|---|---|---|---|
| schema_pass_rate | 100.0% | >= 95% | PASS |
| evidence_coverage | 100% | 100% | PASS |
| pit_violations | 0 | 0 | PASS |
| avg_untraceable_per_agent | 0.00 | < 1 | PASS |
| daily_research_usd | $0.0092 | <= $0.80 | PASS |
| total_usd_vs_daily_cap | $0.0092 | <= $1.50 | PASS |
| llm_path | llm | llm (not heuristic) | PASS |

| 2026-10-12T11:51:23.627899+00:00 | 20261012-cn-daily | reporter | daily_research | deepseek-flash | llm | 1958 | 1086 | 0.0006 |
| 2026-10-12T11:51:23.628905+00:00 | 20261012-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-13T10:01:34.471962+00:00 | 20261013-cn-daily | reporter | daily_research | deepseek-flash | llm | 1968 | 1223 | 0.0006 |
| 2026-10-13T10:01:34.471962+00:00 | 20261013-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-14T14:17:23.099972+00:00 | 20261014-cn-daily | reporter | daily_research | deepseek-flash | llm | 1958 | 1194 | 0.0006 |
| 2026-10-14T14:17:23.100980+00:00 | 20261014-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-15T10:01:30.809224+00:00 | 20261015-cn-daily | reporter | daily_research | deepseek-flash | llm | 1956 | 1184 | 0.0006 |
| 2026-10-15T10:01:30.815682+00:00 | 20261015-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-15T14:07:58.094157+00:00 | 20260901-cn-daily | reporter | daily_research | deepseek-flash | llm | 1283 | 1138 | 0.0005 |
| 2026-10-15T14:07:58.094157+00:00 | 20260901-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-15T14:13:11.118162+00:00 | 20261015-cn-daily | reporter | daily_research | deepseek-flash | llm | 2016 | 1009 | 0.0006 |
| 2026-10-15T14:13:11.119155+00:00 | 20261015-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-16T10:02:25.320260+00:00 | 20261016-cn-daily | reporter | daily_research | deepseek-flash | llm | 2026 | 1238 | 0.0006 |
| 2026-10-16T10:02:25.320260+00:00 | 20261016-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |

| 2026-10-19T10:03:01.350882+00:00 | 20261019-cn-daily | reporter | daily_research | deepseek-flash | llm | 2029 | 1183 | 0.0006 |
| 2026-10-19T10:03:01.351880+00:00 | 20261019-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-20T10:02:27.896189+00:00 | 20261020-cn-daily | reporter | daily_research | deepseek-flash | llm | 2027 | 1074 | 0.0006 |
| 2026-10-20T10:02:27.900205+00:00 | 20261020-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |
| 2026-10-21T10:01:31.356244+00:00 | 20261021-cn-daily | reporter | daily_research | deepseek-flash | llm | 2024 | 1022 | 0.0006 |
| 2026-10-21T10:01:31.359894+00:00 | 20261021-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |

## Gate 2b funnel replay (2026-10-26)

Window: 2026-10-22 ... 2026-10-26 (3 CN sessions). Holdings: `600519.SH, 000858.SZ, 300750.SZ`. Mode: **heuristic**. Cutoff 18:00 Asia/Shanghai, flash lookback 24h.

| Gate 2b | Actual | Threshold | Result |
|---|---|---|---|
| L1 pass rate | 0.00% | < 5% | PASS |
| L2 → L3 rate | n/a | < 25% | n/a |
| L3 max / day | 0 | ≤ 10 | PASS |
| Monitor USD / day | $0.0000 | < $0.30 | PASS |
| L2 cache hit rate | n/a (heuristic L2 not cached) | > 15% | n/a |

Totals: scanned=47 L1_pass=0 L2_rel=0 L2_deep=0 L3=0 USD=$0.0000 ($0.0000/day).

| as_of | scanned | L1 pass | L1 rate | L2 rel | L2 drop | L2 deep | L3 | ANN hits | cache hit/miss | USD | L2 mode | L3 mode |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---|
| 2026-10-22 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-10-23 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |
| 2026-10-26 | 47 | 0 | 0.00% | 0 | 0 | 0 | 0 | 0 | 0/0 | $0.0000 | - | - |

- D-class corpus = news.source in (cls, em); em_announce is C-class and excluded from L1.
- Fetch window is PIT-closed: published_at in (cutoff-lookback, cutoff]; cls/em flash ingest in this DB starts 2026-09-12.
- One cycle per session (not 3-minute polling). Heuristic L2 does not write the analysis cache (LLM-only).
- L1 requires entity match AND keyword severity >= medium; holding-name mentions without keywords do not pass.
- Sessions=3; days with D-class flash=1.
- Note: 2026-10-22/23/26 reporter USD rows were truncated by a prior funnel append bug and not reconstructed; see reporter-validation-log.
| 2026-10-27T10:03:09.243405+00:00 | 20261027-cn-daily | reporter | daily_research | deepseek-flash | llm | 2020 | 1093 | 0.0006 |
| 2026-10-27T10:03:09.244400+00:00 | 20261027-cn-daily | reporter | daily_research | deterministic | llm_schema_fail | 0 | 0 | 0.0000 |

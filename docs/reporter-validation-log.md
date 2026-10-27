# Reporter validation log

Append-only schema validation outcomes (Gate 1 fail-rate evidence).

| UTC | run_id | as_of | agent | mode | ok | error_type | detail |
|---|---|---|---|---|---|---|---|
| 2026-09-12T09:34:10.117767+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | deterministic | true |  |  |
| 2026-09-13T05:13:26.093696+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | deterministic | true |  |  |
| 2026-09-13T05:13:55.831922+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | deterministic | true |  |  |
| 2026-09-13T05:14:55.315786+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | deterministic | true |  |  |
| 2026-09-13T05:25:19.556067+00:00 | 20260904-cn-daily | 2026-09-04 | reporter | deterministic | true |  |  |
| 2026-09-13T05:25:21.810047+00:00 | 20260904-cn-daily | 2026-09-04 | reporter | deterministic | true |  |  |
| 2026-09-14T14:40:31.715573+00:00 | 20260914-cn-daily | 2026-09-14 | reporter | deterministic | true |  |  |
| 2026-09-14T14:46:07.104581+00:00 | 20260914-cn-daily | 2026-09-14 | reporter | deterministic | true |  |  |
| 2026-09-15T10:15:58.380617+00:00 | 20260915-cn-daily | 2026-09-15 | reporter | deterministic | true |  |  |
| 2026-09-16T10:18:42.081783+00:00 | 20260916-cn-daily | 2026-09-16 | reporter | deterministic | true |  |  |
| 2026-09-17T10:18:36.067385+00:00 | 20260917-cn-daily | 2026-09-17 | reporter | deterministic | true |  |  |
| 2026-09-18T10:18:45.328317+00:00 | 20260918-cn-daily | 2026-09-18 | reporter | deterministic | true |  |  |
| 2026-09-20T07:02:23.602625+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | deterministic | true |  |  |
| 2026-09-21T10:26:08.710598+00:00 | 20260921-cn-daily | 2026-09-21 | reporter | deterministic | true |  |  |
| 2026-09-22T11:28:44.952524+00:00 | 20260922-cn-daily | 2026-09-22 | reporter | deterministic | true |  |  |
| 2026-09-23T10:16:42.356557+00:00 | 20260923-cn-daily | 2026-09-23 | reporter | deterministic | true |  |  |
| 2026-09-24T10:19:20.531613+00:00 | 20260924-cn-daily | 2026-09-24 | reporter | deterministic | true |  |  |
| 2026-09-28T10:18:56.888516+00:00 | 20260928-cn-daily | 2026-09-28 | reporter | deterministic | true |  |  |
| 2026-09-29T11:40:05.339505+00:00 | 20260929-cn-daily | 2026-09-29 | reporter | deterministic | true |  |  |
| 2026-09-30T10:07:17.696507+00:00 | 20260930-cn-daily | 2026-09-30 | reporter | deterministic | true |  |  |
| 2026-09-30T10:13:07.336493+00:00 | 20260930-cn-daily | 2026-09-30 | reporter | deterministic | true |  |  |
| 2026-10-12T11:51:23.627899+00:00 | 20261012-cn-daily | 2026-10-12 | reporter | llm | false | SchemaValidationError | 6 validation errors for DailyReport sector_summary   String should have at most 400 characters [type=string_too_long, in |
| 2026-10-12T11:51:23.628905+00:00 | 20261012-cn-daily | 2026-10-12 | reporter | deterministic | true |  |  |
| 2026-10-13T10:01:34.471962+00:00 | 20261013-cn-daily | 2026-10-13 | reporter | llm | false | SchemaValidationError | 7 validation errors for DailyReport sector_summary   String should have at most 400 characters [type=string_too_long, in |
| 2026-10-13T10:01:34.471962+00:00 | 20261013-cn-daily | 2026-10-13 | reporter | deterministic | true |  |  |
| 2026-10-14T14:17:23.100980+00:00 | 20261014-cn-daily | 2026-10-14 | reporter | llm | false | SchemaValidationError | 6 validation errors for DailyReport sector_summary   String should have at most 400 characters [type=string_too_long, in |
| 2026-10-14T14:17:23.100980+00:00 | 20261014-cn-daily | 2026-10-14 | reporter | deterministic | true |  |  |
| 2026-10-15T10:01:30.811682+00:00 | 20261015-cn-daily | 2026-10-15 | reporter | llm | false | SchemaValidationError | 7 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-15T10:01:30.815682+00:00 | 20261015-cn-daily | 2026-10-15 | reporter | deterministic | true |  |  |
| 2026-10-15T14:07:58.094157+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | llm | false | SchemaValidationError | 7 validation errors for DailyReport factor_summary   String should have at most 300 characters [type=string_too_long, in |
| 2026-10-15T14:07:58.094157+00:00 | 20260901-cn-daily | 2026-09-01 | reporter | deterministic | true |  |  |
| 2026-10-15T14:13:11.118162+00:00 | 20261015-cn-daily | 2026-10-15 | reporter | llm | false | SchemaValidationError | 5 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-15T14:13:11.119155+00:00 | 20261015-cn-daily | 2026-10-15 | reporter | deterministic | true |  |  |
| 2026-10-16T10:02:25.320260+00:00 | 20261016-cn-daily | 2026-10-16 | reporter | llm | false | SchemaValidationError | 6 validation errors for DailyReport sector_summary   String should have at most 400 characters [type=string_too_long, in |
| 2026-10-16T10:02:25.320260+00:00 | 20261016-cn-daily | 2026-10-16 | reporter | deterministic | true |  |  |
| 2026-10-19T10:03:01.350882+00:00 | 20261019-cn-daily | 2026-10-19 | reporter | llm | false | SchemaValidationError | 8 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-19T10:03:01.351880+00:00 | 20261019-cn-daily | 2026-10-19 | reporter | deterministic | true |  |  |
| 2026-10-20T10:02:27.897193+00:00 | 20261020-cn-daily | 2026-10-20 | reporter | llm | false | SchemaValidationError | 5 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-20T10:02:27.900205+00:00 | 20261020-cn-daily | 2026-10-20 | reporter | deterministic | true |  |  |
| 2026-10-21T10:01:31.357317+00:00 | 20261021-cn-daily | 2026-10-21 | reporter | llm | false | SchemaValidationError | 6 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-21T10:01:31.359894+00:00 | 20261021-cn-daily | 2026-10-21 | reporter | deterministic | true |  |  |
| 2026-10-26T12:47:06.111484+00:00 | 20261022-cn-daily | 2026-10-22 | reporter | llm | false | SchemaValidationError | 9 validation errors for DailyReport sector_summary   String should have at most 400 characters [type=string_too_long, in |
| 2026-10-26T12:47:06.112484+00:00 | 20261022-cn-daily | 2026-10-22 | reporter | deterministic | true |  |  |
| 2026-10-26T12:47:18.316872+00:00 | 20261023-cn-daily | 2026-10-23 | reporter | llm | false | SchemaValidationError | 5 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-26T12:47:18.316872+00:00 | 20261023-cn-daily | 2026-10-23 | reporter | deterministic | true |  |  |
| 2026-10-26T12:47:28.777152+00:00 | 20261026-cn-daily | 2026-10-26 | reporter | llm | false | SchemaValidationError | 7 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-26T12:47:28.777152+00:00 | 20261026-cn-daily | 2026-10-26 | reporter | deterministic | true |  |  |
| 2026-10-27T10:03:09.244400+00:00 | 20261027-cn-daily | 2026-10-27 | reporter | llm | false | SchemaValidationError | 8 validation errors for DailyReport notable_observations.0.statement   Field required [type=missing, input_value={'metri |
| 2026-10-27T10:03:09.244400+00:00 | 20261027-cn-daily | 2026-10-27 | reporter | deterministic | true |  |  |

# Data Access Log

Record interface changes, outages, and workarounds for external data sources.
See [04-data-sources](04-data-sources.md).

**Currency rule (2026-09+):** 接口字段、单位、版本号、示例日期区间必须以**当日可复现的实测**为准；文档数字不得长期停留在设计稿或旧锁定版本。每次核实在本表记一行。

| Date | Interface | Event | Action |
|---|---|---|---|
| 2026-09-05 | akshare | 本机安装版本 `1.18.94`（文档曾写 1.15.30，已过时） | 更新 `docs/01-tech-stack.md`；`pyproject` 仍用 `akshare` 不锁死小版本，以 lock/实测为准 |
| 2026-09-05 | akshare.stock_zh_a_hist | W2 collector；列：日期/开盘/收盘/最高/最低/成交量/成交额/换手率等；volume=手，amount=元，换手率=% | PriceNormalizer：volume×100、turnover/100 |
| 2026-09-05 | baostock.query_history_k_data_plus | W2 校验源；adjustflag=3；volume=股；**现窗 2026-08-20～2026-09-05 拉取成功**（600519.SH，12 行） | 双源校验用；与 akshare 量有手/股舍入差 |
| 2026-09-05 | akshare.stock_zh_a_hist | 同日近窗拉取偶发 `RemoteDisconnected`（东财不稳定） | tenacity 重试 + `COLLECTOR_DISABLE_SYSTEM_PROXY`；失败不静默 |
| 2026-09-05 | (network) | Windows 系统代理 `127.0.0.1:7897`（Clash 未开）→ ProxyError | `COLLECTOR_DISABLE_SYSTEM_PROXY=true`：清 proxy env + `NO_PROXY=*` + 空 `getproxies` |
| 2026-09-05 | (diag) | 代理已关：裸 `requests` 打 kline API 与裸 `akshare` 均 `RemoteDisconnected`；`push2his` 根路径 404 可达；baostock 正常 | **判定为东财源/链路问题，非本仓库 Collector 逻辑**；环境变量勿用 `*_PROXY` 后缀（已改名） |
| 2026-09-05 | W3 Loader | `price_daily` UPSERT + `ingest_batch` / `data_quality_check`；CLI `--load` | PX_001/002/003/005 ERROR，PX_008 WARN；日历/双源规则留后续 |
| 2026-09-05 | akshare.stock_*_sheet_by_report_em | W4 财务三表；单位元；`NOTICE_DATE`/`UPDATE_DATE`→`announced_at`；symbol=`SH600519` | FinancialNormalizer 合并 profit/balance/cashflow；无 tushare token 时以 akshare 为主源 |
| 2026-09-05 | akshare.stock_zh_index_daily | 沪深300 `sh000300`；列 date/OHLCV；**现窗至 2026-09-04 可拉**（5986 行历史） | Index collector 归档完整 `000300.SH`（勿只存 6 位，否则会被当成 SZ）；Buy&Hold 基线 |
| 2026-09-06 | baostock.query_history_k_data_plus | A2：已采字段 `tradestatus`/`isST`/`preclose` 写入 `is_suspended`/`is_limit_*`/`limit_*_px`（按 cn.yaml 板块/ST 幅度，收盘价封板判定） | PriceNormalizer enrichment + PriceLoader UPSERT；akshare 用涨跌幅推 prev_close、volume=0→停牌 |
| 2026-09-06 | akshare.tool_trade_date_hist_sina / baostock.query_trade_dates | A3：交易日历入库；调度按日历跳过非交易日；`default_as_of` 用最近开市日 | `TradingCalendar` + `make ingest-calendar`；`--dual-check` 对比双源开市日 |
| 2026-09-06 | baostock prices + akshare index | A4：live 调度链 ingest 增量→seed→report；默认 baostock 拉宇宙、akshare 拉 000300 | `make schedule-live` / `schedule-live-hang`；`ingest-daily` |

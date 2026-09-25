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
| 2026-09-06 | baostock.query_history_k_data_plus | A5：`mvp_cn_50` 全 50 只 2025-01-02～2026-09-04 日线入库（约 407 交易日/只，20350 行） | `ingest --universe mvp_cn_50 --start 2025-01-01 --end 2026-09-05 --load --source baostock` |
| 2026-09-06 | akshare SW industry + index | A5 配套：行业归属 50/50；沪深300 同步拉长至同窗（407 行） | `ingest --dataset security_industry --universe mvp_cn_50 --load`；`ingest --dataset index --symbols 000300.SH ...` |
| 2026-09-12 | akshare calendar dual-check | Gate1 10y：日历 2015-01-01～2027-09-12；open_days=2916（窗内至 2026-09-12 为 2843） | `ingest --dataset trading_calendar --dual-check` |
| 2026-09-12 | baostock.query_history_k_data_plus | Gate1 10y：`mvp_cn_50` 全 50 只 2015-01-05～2026-09-11 日线；134507 行；上市后缺失率 **0.00%** | `scripts/backfill_prices_10y.py`；审计 `scripts/audit_price_completeness.py` |
| 2026-09-12 | akshare.stock_zh_index_daily | 沪深300 同窗 2843 行入库 | `ingest --dataset index --symbols 000300.SH --start 2015-01-01 --end 2026-09-12 --load` |
| 2026-09-12 | baostock.query_adjust_factor | 50 只复权因子 711 行（除权日稀疏） | `scripts/backfill_adjust_10y.py` |
| 2026-09-12 | seed + industry | `mvp_cn_50` snapshot n=50 missing=0；行业 50/50 | `seed-universe` + industry ingest |
| 2026-09-13 | akshare.stock_info_global_cls / stock_info_global_em | P2 快讯：列 标题/内容|摘要/发布日期|时间/链接；CLS 约 20 条滚动窗 | `make ingest-news` → `news` 表；source=`cls`/`em` |
| 2026-09-13 | akshare.stock_notice_report | P2 公告：代码/名称/公告标题/类型/日期/网址；按日 `YYYYMMDD` | `make ingest-announcements` → source=`em_announce` |
| 2026-09-13 | eastmoney np-anotice-stock | 周日 `total_hits=0` 时 akshare 抛 `KeyError: 代码` | 自研 `fetch_em_notice_report` + 向前回退最多 7 天 |
| 2026-09-13 | rule_v1 NewsExtractor | 事件表 `event`/`event_security`；数字金标 30 条 soft=100% | `make extract-news` / `make extraction-eval` |
| 2026-09-13 | figures_gold ≥100 | 入库新闻摘录为主（db≈68 + synthetic 模板）；soft=100% | `scripts/build_figures_gold.py` + `make extraction-eval` |
| 2026-09-13 | daily_live_pipeline | 挂载 news/announce/extract（软失败 degraded） | `refresh_daily_news_events`；`--skip-news` 可关 |
| 2026-09-13 | em_announce backfill | 2026-09-02～11 共 8 个交易日，入库 11379 条；抽取事件约 4.7k | `scripts/backfill_announcements_and_rereport.py` |
| 2026-09-13 | daily report | 新增「二、重要事件」；已重写 09-02～11 交易日日报 | `load_events_for_as_of` + `make rereport-with-events` |
| 2026-09-13 | news.related_symbol | 公告代码未落库 → 事件标的全空 | migration `0006` + extract hint；URL 回填 `make relink-event-symbols` |
| 2026-09-13 | security_industry | 重跑日报时申万归属表为空 | `make ingest-industry` 后 `rereport-with-events` |
| 2026-09-13 | LLMClient / TokenBudget | P2 基建：OpenAI-compatible HTTP + ADR-0010 调用前预留；cost-log 增加 allocation | `config/llm.yaml`；`LLM_API_KEY` 空则 Null/$0；`make` 日报写 `docs/cost-log.md` |
| 2026-09-20 | document_chunk + pgvector | P2 RAG 地基：`search_chunks_as_of`（visible_at + expires_at）；默认 HashEmbedder；可选 fastembed | migration `0007`；`make ingest-chunks` / `rag-smoke`；`EMBEDDING_BACKEND` |
| 2026-09-20 | fastembed | `BAAI/bge-large-zh-v1.5` **不在** TextEmbedding 支持列表；中文 BGE 仅 `bge-small-zh`@512 | 默认改 `intfloat/multilingual-e5-large`@1024；可用 `EMBEDDING_MODEL` 覆盖 |
| 2026-09-20 | K2 report_pack | 年报/半年报 MD&A+风险因素：本地 JSONL pack（全文 PDF OCR 后接）；`visible_at`=disclose_date | `make ingest-reports`；fixture `tests/fixtures/reports/k2_packs.jsonl` |
| 2026-09-20 | research DB tools | Agent 工具：价格/财务/估值/新闻/事件/行业/广度经 PIT；宏观/北向/资金流 stub | `agents/tools/research_db.py`；`build_default_tool_registry(include_db=True)` |
| 2026-09-20 | research-live | PIT 组装 ResearchFacts；Macro/Industry/Stock 调 DB 工具；fixture smoke 仍离线 | `make research-live`；`facts_builder.py` |
| 2026-09-20 | research LLM path | Macro/Sector/Stock/Chief：`complete_with_budget` + scaffold refinement；预算/解析失败回退启发式；cost-log | `agents/llm/structured.py`；`LLM_API_KEY` / `--no-llm` |
| 2026-09-20 | Agent output validation | Gate 2：evidence 非空/refs 可解析/PIT；figures WARN；Orchestrator 绑定 `AgentTrace` | `agents/validation.py`；`make research-smoke` 打印 untraceable |
| 2026-09-20 | shadow_agent | Gate 2：第三 shadow；信号=`MarketBrief.stock_ranking`；live 日报软跑启发式 research；按组合幂等追赶 | `evaluation/shadow/`；`data/shadow/shadow_agent.jsonl` |
| 2026-09-20 | P2a positions + price triggers | YAML 持仓书 + 时效性；A 类价格触发骨架（止损/止盈/涨跌停/停牌/放量/MA60）；零 LLM | `positions/`；`monitor/triggers/price.py`；`make positions-check` / `monitor-once` |
| 2026-09-20 | P2a spot + suppress + TG + risk | 东财 ulist 定向快照（akshare 全表兜底）；冷却/日上限/静默；Telegram；B 类风控含 DD_005 | `collectors/akshare/spot.py`；`monitor/{suppression,engine,triggers/risk}.py`；`notify/`；`TELEGRAM_*` |


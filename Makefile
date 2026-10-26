.PHONY: help install db-init db-migrate ingest ingest-universe backfill-10y backfill-adjust-10y backfill-valuation-10y backfill-universe-monthly build-csi300 features evaluate evaluate-real evaluate-synthetic evaluate-l2 evaluate-l3 evaluate-l4 portfolio backtest backtest-baseline backtest-l2-report test-sentinel test-edge report report-live schedule schedule-live schedule-live-hang seed-universe ensure-survivorship sync-delist-dates check-survivorship reporter-validation ingest-industry ingest-calendar ingest-daily ingest-news ingest-announcements extract-news extraction-eval backfill-announcements relink-event-symbols rereport-with-events ingest-chunks ingest-reports rag-smoke research-smoke research-live research-live-accept positions-check monitor-once monitor-loop monitor-funnel-replay test lint smoke

# Cross-platform YYYY-MM-DD (Windows PowerShell has no GNU ``date +%F``).
TODAY := $(shell uv run python -c "from datetime import date; print(date.today().isoformat())")
TODAY_PLUS_1Y := $(shell uv run python -c "from datetime import date,timedelta; print((date.today()+timedelta(days=365)).isoformat())")

# Override for CSI300 L1: ``make backfill-10y UNIVERSE=csi300 SYMBOLS_FILE=data/universes/csi300_hist_union.txt``
UNIVERSE ?= mvp_cn_50
SYMBOLS_FILE ?=
FROM_INDEX ?=
OUT_DIR ?= docs/factor-reports
PANEL_OUT ?= data/panels/l1_$(UNIVERSE).parquet
START ?= 2021-10-14
L2_UNIVERSE ?= csi300
L2_OUT ?= docs/factor-reports-csi300-5y-l2
L3_UNIVERSE ?= csi300
L3_OUT ?= docs/factor-reports-csi300-5y-l3
L4_UNIVERSE ?= csi300
L4_OUT ?= docs/factor-reports-csi300-5y-l4
SYMBOLS_FILE_FLAG := $(if $(SYMBOLS_FILE),--symbols-file $(SYMBOLS_FILE),)
FROM_INDEX_FLAG := $(if $(FROM_INDEX),--from-index $(FROM_INDEX),)

help:           ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:        ## 安装依赖
	uv sync --all-groups

up:             ## 启动基础设施
	docker compose up -d
	@echo "等待数据库就绪..."
	@until docker compose exec -T postgres pg_isready -U quantagent; do sleep 1; done

db-init:        ## 初始化数据库
	uv run alembic upgrade head
	uv run python -m quantagent.cli init-reference-data

db-migrate:     ## 生成迁移
	uv run alembic revision --autogenerate -m "$(MSG)"

ingest: ingest-universe ## 拉取 MVP 股票池（ingest-universe 别名）

ingest-universe: ## 拉取股票池数据并入库（bootstrap；CSI300 用 UNIVERSE=csi300）
	uv run python -m quantagent.cli ingest --universe $(UNIVERSE) --start 2015-01-01 --end $(TODAY) --load --source baostock

build-csi300: ## 拉 HS300 当前+历史成分 → csi300.yaml + hist union
	uv run python -u scripts/build_csi300_universe.py --start 2015-01-01 --end $(TODAY)

backfill-10y: ## 逐标的回填 10 年日线（可断点续跑）+ 完整性审计
	uv run python -u scripts/backfill_prices_10y.py --universe $(UNIVERSE) --start 2015-01-01 --end $(TODAY) $(SYMBOLS_FILE_FLAG)
	uv run python -u scripts/audit_price_completeness.py --universe $(UNIVERSE) --start 2015-01-01 --end $(TODAY) $(SYMBOLS_FILE_FLAG)

backfill-adjust-10y: ## P3：回填复权因子（baostock query_adjust_factor）
	uv run python -u scripts/backfill_adjust_10y.py --universe $(UNIVERSE) --start 2015-01-01 --end $(TODAY) $(SYMBOLS_FILE_FLAG)

backfill-valuation-10y: ## P3：回填估值 pe/pb/ps（baostock 日线字段）
	uv run python -u scripts/backfill_valuation_10y.py --universe $(UNIVERSE) --start 2015-01-01 --end $(TODAY) $(SYMBOLS_FILE_FLAG)

backfill-universe-monthly: ## 月度 universe_snapshot（CSI300: FROM_INDEX=hs300）
	uv run python -u scripts/backfill_universe_snapshots.py --universe $(UNIVERSE) --start 2015-01-01 --end $(TODAY) --force $(FROM_INDEX_FLAG) $(SYMBOLS_FILE_FLAG)

seed-universe: ## 写入 universe_snapshot（需 security 已有标的）
	uv run python -m quantagent.cli seed-universe --universe $(UNIVERSE) --as-of $(TODAY)

ensure-survivorship: ## 写入退市探针 security + status_history（不进 bootstrap）
	uv run python -m quantagent.cli ensure-survivorship --universe $(UNIVERSE)

sync-delist-dates: ## 为已离开指数、且行情已停的历史成分补退市日
	uv run python -m quantagent.cli sync-delist-dates --universe $(L2_UNIVERSE)

check-survivorship: ## Gate 4：历史快照必须含后来退市的股票
	uv run python -m quantagent.cli check-survivorship --universe $(L2_UNIVERSE) --as-of 2018-01-31 --until $(TODAY)

reporter-validation: ## Reporter 校验失败率汇总（Gate 1 <5%）
	uv run python scripts/reporter_validation_summary.py --path docs/reporter-validation-log.md

ingest-daily:   ## 每日增量：宇宙行情+沪深300 + seed snapshot（A4）
	uv run python -m quantagent.cli ingest-daily --universe $(UNIVERSE) --source baostock

ingest-industry: ## 申万行业 taxonomy + 全市场 L1 归属（勿按 universe 过滤，避免漏历史并集）
	uv run python -m quantagent.cli ingest --dataset security_industry --load --source akshare

ingest-calendar: ## A 股交易日历入库（akshare 主源；加 --dual-check 对比 baostock；end 默认 today+1y）
	uv run python -m quantagent.cli ingest --dataset trading_calendar --source akshare --load --dual-check --start 2015-01-01 --end $(TODAY_PLUS_1Y)

ingest-news: ## P2：财联社+东财快讯采集并入库
	uv run python -m quantagent.cli ingest --dataset news --news-feed cls --load --daily
	uv run python -m quantagent.cli ingest --dataset news --news-feed em --load --daily

ingest-announcements: ## P2：东财公告列表（按日）采集并入库
	uv run python -m quantagent.cli ingest --dataset announcement --news-feed em_announce --load --end $(TODAY)

extract-news: ## P2：rule_v1 抽取未处理新闻 → event / event_security
	uv run python -m quantagent.cli extract-news --limit 200 --load

extraction-eval: ## P2：数字提取金标基线 → docs/extraction-eval.md（≥100 条）
	uv run python scripts/build_figures_gold.py --target 100
	uv run python scripts/extraction_eval.py --gold tests/fixtures/extraction/figures_gold.jsonl --min-n 100

backfill-announcements: ## P2：按日回填东财公告并抽取（默认 2026-09-02～12）
	uv run python -u scripts/backfill_announcements_and_rereport.py --start 2026-09-02 --end 2026-09-12

relink-event-symbols: ## P2：从公告 URL 回填 related_symbol 并补 event_security 标的
	uv run python -u scripts/backfill_announcements_and_rereport.py --skip-announce --skip-extract --relink

rereport-with-events: ## P2：回填公告+抽取后，重写已有日报（含重要事件节）
	uv run python -u scripts/backfill_announcements_and_rereport.py --start 2026-09-02 --end 2026-09-12 --skip-announce --skip-extract --relink --rereport

ingest-chunks: ## P2 RAG：新闻/公告切片入库 document_chunk（默认 hash embed）
	uv run python -m quantagent.cli ingest-chunks --limit 200 --load

ingest-reports: ## P2 K2：年报/半年报 MD&A+风险因素切片入库（默认 fixture pack）
	uv run python -m quantagent.cli ingest-reports --load --archive

rag-smoke: ## P2 RAG：查询 smoke（需先 ingest-chunks/ingest-reports + db migrate）
	uv run python -m quantagent.cli rag-smoke --query "管理层讨论 风险因素" --as-of $(TODAY) --top-k 5

research-smoke: ## P2 多 Agent 骨架：Orchestrator → MarketBrief（fixture，不连库）
	uv run python -m quantagent.cli research-smoke --max-stocks 10

research-live: ## P2 研究 DAG：PIT + DB 工具；有 LLM_API_KEY 则走 complete_with_budget
	uv run python -m quantagent.cli research-live --max-stocks 10 --max-industries 5 --no-knowledge

research-live-accept: ## Gate 2：强制 LLM research-live + 验收落盘（需 .env LLM_API_KEY）
	uv run python -m quantagent.cli research-live --as-of 2026-09-30 --max-stocks 8 --max-industries 4 --no-knowledge --require-llm

positions-check: ## P2a：持仓 YAML 时效性检查（默认 example_cn.yaml）
	uv run python -m quantagent.cli positions check --file data/positions/example_cn.yaml

monitor-once: ## P2a：价格+风控+公告触发 → 抑制 → 推送（demo；真实快照加 --live-spot）
	uv run python -m quantagent.cli monitor-once --positions data/positions/example_cn.yaml --demo

monitor-loop: ## P2a：常驻轮询（默认 demo + 2 轮；盘中加 --live-spot）
	uv run python -m quantagent.cli monitor-loop --positions data/positions/example_cn.yaml --demo --interval 2 --max-cycles 2 --ignore-sessions

monitor-funnel-replay: ## Gate 2b：历史交易日回放 L1/L2/L3 漏斗并写入 cost-log
	uv run python -m quantagent.cli monitor-funnel-replay --start 2026-09-02 --end 2026-09-30 --write-cost-log

features:       ## 列出 MVP 因子
	uv run python -m quantagent.cli features --market CN

evaluate: evaluate-real ## L1 因子准入（默认真实 DB 面板 → docs/factor-reports）

evaluate-real:  ## Gate3：从 Postgres 拉行情跑 L1（CSI300: UNIVERSE=csi300 OUT_DIR=docs/factor-reports-csi300）
	uv run python -m quantagent.cli evaluate --from-db --universe $(UNIVERSE) --start 2015-01-01 --out $(OUT_DIR) --export-panel $(PANEL_OUT)

evaluate-synthetic: ## L1 合成面板（无 DB，CI / 离线）
	uv run python -m quantagent.cli evaluate --synthetic --out docs/factor-reports-synthetic

evaluate-l2:    ## Gate3 L2：等权 / IC 加权（默认 CSI300 5y + 7 个准入因子）
	uv run python -m quantagent.cli evaluate-l2 --from-db --universe $(L2_UNIVERSE) --start $(START) --out $(L2_OUT)

evaluate-l3:    ## Gate3 L3：Walk-forward Ridge / Logistic（默认 CSI300 5y）
	uv run python -m quantagent.cli evaluate-l3 --from-db --universe $(L3_UNIVERSE) --start $(START) --out $(L3_OUT)

evaluate-l4:    ## Gate3 L4：Walk-forward LightGBM（默认 CSI300 5y；对照 L2 OOS）
	uv run python -m quantagent.cli evaluate-l4 --from-db --universe $(L4_UNIVERSE) --start $(START) --out $(L4_OUT)

portfolio:      ## 等权 Top-N + 风控 demo（synthetic，无 DB）
	uv run python -m quantagent.cli portfolio --market CN

backtest-baseline: ## 跑沪深300 Buy&Hold 基线并写入 docs/baseline-results.md
	uv run python -m quantagent.cli backtest --strategy buy_and_hold --symbol 000300.SH --start 2015-01-01 --write-baseline docs/baseline-results.md

backtest-l2-report: ## Gate4：L2 Top-N 合成回测 + §9.2 报告（含撮合假设未验证）
	uv run python -m quantagent.cli backtest --strategy l2_equal_topn --write-report docs/backtest-reports/l2_equal_topn-synthetic.md

backtest:       ## 跑指定策略回测
	uv run python -m quantagent.cli backtest --strategy $(STRATEGY)

test-sentinel:  ## 跑未来函数哨兵（集成）
	uv run pytest tests/integration/test_pit_sentinel.py tests/integration/test_backtest_sentinel.py -v

test-edge:      ## MVP 边角清单验证（排除 H/D3/D4 留给 20 天观察）
	uv run pytest tests/unit/mvp/test_edge_case_checklist.py tests/integration/test_edge_case_pit.py tests/integration/test_pit_sentinel.py -v

report:         ## 生成日报（默认 synthetic；真实数据用 make report-live）
	uv run python -m quantagent.cli report --market CN --synthetic --out docs/daily-reports

report-live:    ## 生成真实数据日报（PIT + Shadow）
	uv run python -m quantagent.cli report --market CN --live --out docs/daily-reports --shadow-dir data/shadow

schedule:       ## 跑一次调度（synthetic demo）
	uv run python -m quantagent.cli schedule --once --synthetic

schedule-live:  ## 跑一次 live 流水线（ingest→seed→report）
	uv run python -m quantagent.cli schedule --once --live

schedule-live-hang: ## 常驻挂 live 调度（每日 18:00，交易日跑；Ctrl+C 停）
	uv run python -m quantagent.cli schedule --live

test:           ## 跑全部测试（含覆盖率；cli/sentinel 已 omit）
	uv run pytest -v --cov=src/quantagent --cov-report=term-missing:skip-covered --cov-report=json:coverage.json

test-fast:      ## 只跑单元测试（含覆盖率）
	uv run pytest tests/unit -v --cov=src/quantagent --cov-report=term-missing:skip-covered --cov-report=json:coverage.json
	uv run python scripts/cov_gate1_summary.py

smoke:          ## P0 一键 smoke（A→H，含 W3 load + W4 财务/指数/回测）
	uv run python scripts/smoke_p0.py

smoke-offline:  ## smoke 仅 A+B（不联网）
	uv run python scripts/smoke_p0.py --skip-network

lint:           ## 检查
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src
	uv run python scripts/lint_pit.py

fix:            ## 自动修复
	uv run ruff check --fix src tests
	uv run ruff format src tests

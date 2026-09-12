.PHONY: help install db-init db-migrate ingest ingest-universe backfill-10y backfill-universe-monthly features evaluate portfolio backtest backtest-baseline test-sentinel test-edge report report-live schedule schedule-live schedule-live-hang seed-universe ensure-survivorship reporter-validation ingest-industry ingest-calendar ingest-daily test lint smoke

# Cross-platform YYYY-MM-DD (Windows PowerShell has no GNU ``date +%F``).
TODAY := $(shell uv run python -c "from datetime import date; print(date.today().isoformat())")
TODAY_PLUS_1Y := $(shell uv run python -c "from datetime import date,timedelta; print((date.today()+timedelta(days=365)).isoformat())")

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

ingest-universe: ## 拉取 MVP 股票池数据并入库（bootstrap symbols）
	uv run python -m quantagent.cli ingest --universe mvp_cn_50 --start 2015-01-01 --end $(TODAY) --load --source baostock

backfill-10y: ## Gate1：逐标的回填 10 年日线（可断点续跑）+ 完整性审计
	uv run python -u scripts/backfill_prices_10y.py --universe mvp_cn_50 --start 2015-01-01 --end $(TODAY)
	uv run python -u scripts/audit_price_completeness.py --universe mvp_cn_50 --start 2015-01-01 --end $(TODAY)

backfill-universe-monthly: ## Gate1：月度 universe_snapshot 历史回填（需先有日历+行情入库）
	uv run python -u scripts/backfill_universe_snapshots.py --universe mvp_cn_50 --start 2015-01-01 --end $(TODAY) --force

seed-universe: ## 写入 mvp_cn_50 universe_snapshot（需 security 已有标的）
	uv run python -m quantagent.cli seed-universe --universe mvp_cn_50 --as-of $(TODAY)

ensure-survivorship: ## 写入退市探针 security + status_history（不进 bootstrap）
	uv run python -m quantagent.cli ensure-survivorship --universe mvp_cn_50

reporter-validation: ## Reporter 校验失败率汇总（Gate 1 <5%）
	uv run python scripts/reporter_validation_summary.py --path docs/reporter-validation-log.md

ingest-daily:   ## 每日增量：宇宙行情+沪深300 + seed snapshot（A4）
	uv run python -m quantagent.cli ingest-daily --universe mvp_cn_50 --source baostock

ingest-industry: ## 申万行业 taxonomy + L1 归属入库（可加 --universe 过滤）
	uv run python -m quantagent.cli ingest --dataset security_industry --universe mvp_cn_50 --load --source akshare

ingest-calendar: ## A 股交易日历入库（akshare 主源；加 --dual-check 对比 baostock；end 默认 today+1y）
	uv run python -m quantagent.cli ingest --dataset trading_calendar --source akshare --load --dual-check --start 2015-01-01 --end $(TODAY_PLUS_1Y)

features:       ## 列出 MVP 因子
	uv run python -m quantagent.cli features --market CN

evaluate:       ## 因子 IC/分层评估（默认 synthetic demo → docs/factor-reports）
	uv run python -m quantagent.cli evaluate --synthetic --out docs/factor-reports

portfolio:      ## 等权 Top-N + 风控 demo（synthetic，无 DB）
	uv run python -m quantagent.cli portfolio --market CN

backtest-baseline: ## 跑沪深300 Buy&Hold 基线并写入 docs/baseline-results.md
	uv run python -m quantagent.cli backtest --strategy buy_and_hold --symbol 000300.SH --start 2015-01-01 --write-baseline docs/baseline-results.md

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

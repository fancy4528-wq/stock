.PHONY: help install db-init db-migrate ingest features evaluate portfolio backtest backtest-baseline test-sentinel report report-live schedule schedule-live seed-universe test lint smoke

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

ingest-universe: ## 拉取 MVP 股票池数据并入库（bootstrap symbols）
	uv run python -m quantagent.cli ingest --universe mvp_cn_50 --start 2015-01-01 --end $$(date +%F) --load --source baostock

seed-universe: ## 写入 mvp_cn_50 universe_snapshot（需 security 已有标的）
	uv run python -m quantagent.cli seed-universe --universe mvp_cn_50 --as-of $$(date +%F)

ingest-daily:   ## 每日增量采集
	uv run python -m quantagent.cli ingest --daily

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

report:         ## 生成日报（默认 synthetic；真实数据用 make report-live）
	uv run python -m quantagent.cli report --market CN --synthetic --out docs/daily-reports

report-live:    ## 生成真实数据日报（PIT + Shadow）
	uv run python -m quantagent.cli report --market CN --live --out docs/daily-reports --shadow-dir data/shadow

schedule:       ## 跑一次调度任务（synthetic）
	uv run python -m quantagent.cli schedule --once --synthetic

schedule-live:  ## 跑一次真实数据调度任务
	uv run python -m quantagent.cli schedule --once --live

test:           ## 跑全部测试
	uv run pytest -v --cov=src/quantagent --cov-report=term-missing

test-fast:      ## 只跑单元测试
	uv run pytest tests/unit -v

smoke:          ## P0 一键 smoke（A→H，含 W3 load + W4 财务/指数/回测）
	uv run python scripts/smoke_p0.py

smoke-offline:  ## smoke 仅 A+B（不联网）
	uv run python scripts/smoke_p0.py --skip-network

lint:           ## 检查
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src

fix:            ## 自动修复
	uv run ruff check --fix src tests
	uv run ruff format src tests

.PHONY: help install db-init db-migrate ingest features backtest report test lint smoke

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

ingest-universe: ## 拉取 MVP 股票池数据
	uv run python -m quantagent.cli ingest --universe mvp_cn_50 --start 2015-01-01

ingest-daily:   ## 每日增量采集
	uv run python -m quantagent.cli ingest --daily

features:       ## 计算因子
	uv run python -m quantagent.cli features --market CN

backtest-baseline: ## 跑基准回测
	uv run python -m quantagent.cli backtest --strategy buy_and_hold

backtest:       ## 跑指定策略回测
	uv run python -m quantagent.cli backtest --strategy $(STRATEGY)

report:         ## 生成日报
	uv run python -m quantagent.cli report --market CN

test:           ## 跑全部测试
	uv run pytest -v --cov=src/quantagent --cov-report=term-missing

test-fast:      ## 只跑单元测试
	uv run pytest tests/unit -v

smoke:          ## P0+W2 一键 smoke（A→E）
	uv run python scripts/smoke_p0_w2.py

smoke-offline:  ## smoke 仅 A+B（不联网）
	uv run python scripts/smoke_p0_w2.py --skip-network

lint:           ## 检查
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src

fix:            ## 自动修复
	uv run ruff check --fix src tests
	uv run ruff format src tests

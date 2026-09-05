# ADR-0002: 使用单一 PostgreSQL 而非多数据库

- 状态: 已接受
- 日期: 2026-08-31
- 相关: [01-tech-stack](../01-tech-stack.md), [03-data-model](../03-data-model.md)

## 背景

系统需要四类存储能力：关系型（财务、订单）、时序（行情、因子）、向量（RAG）、缓存队列。

原始草案建议 PostgreSQL + pgvector + TimescaleDB + Redis 四件套。需要明确这是几个数据库进程。

## 决策

**单一 PostgreSQL 16 + TimescaleDB 扩展 + pgvector 扩展，加一个 Redis。**

即两个进程，不是四个。镜像用 `timescale/timescaledb-ha:pg16`（已含 pgvector）。

DuckDB 作为分析加速层，读 Parquet 做因子面板计算，不是主存储。

```
PostgreSQL (真相来源)
    ├── 关系表（financial_statement, order, decision_journal）
    ├── Hypertable（price_daily, factor_value）— TimescaleDB
    └── 向量列（document_chunk.embedding）— pgvector
         ↓ 定期导出
    Parquet 因子面板 → DuckDB（回测时高速读取）

Redis (缓存/队列/锁/kill switch 状态)
```

## 理由

**跨库 JOIN 是主要痛点。** 因子计算需要同时用到行情（时序）和财务（关系型）。如果分库，每次都要在应用层做 join，代价高且容易出错。

**数据量根本用不上专用数据库**：

| 数据 | 规模 |
|---|---|
| A 股全市场日线 10 年 | ~1.5 GB |
| MVP 池 50 支 10 年 | ~15 MB |
| 新闻向量 70 万条 | ~3 GB |

单机 PG 处理这个量级毫无压力。

**事务一致性天然保证。** 订单、持仓、决策日志需要一致写入，单库直接用事务。

**运维成本**：一个人的业余项目，多一个数据库就多一份备份、监控、升级负担。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| ClickHouse 存时序 | 适合 tick 级和 TB 级。我们是日线 + GB 级，用不上。且无法与关系数据 JOIN |
| InfluxDB | 不支持关系型 JOIN，财务数据无处安放 |
| Milvus / Qdrant 独立向量库 | 70 万条向量 pgvector 的 HNSW 索引完全够用。多一个服务不值 |
| MongoDB | 金融数据强 schema，文档库反而增加校验负担 |
| 全部用 DuckDB | 单文件不支持并发写入，不适合作主存储 |
| 全部用 Parquet + DuckDB | 无事务、无约束、无并发控制，订单数据不能这么存 |

## 后果

**正面**：
- 一次 SQL 就能 join 行情、财务、因子
- 事务保证
- 单一备份策略
- 本地开发简单（`docker compose up`）

**负面**：
- 时序查询性能不如专用 TSDB（但我们的量级无感）
- 向量检索性能不如专用向量库（70 万条量级无感）
- PG 成为单点（个人项目可接受）

**为什么需要 DuckDB**：因子回测需要反复全表扫描做列式聚合。PG 是行存，这类查询慢。DuckDB 读 Parquet 快 10-100 倍且零运维。它读的是从 PG 导出的数据，PG 仍是真相来源。

## 复审条件

- 若引入分钟线/tick 级数据，且数据量超过 100 GB → 重新评估 ClickHouse
- 若向量条目超过 1000 万 → 重新评估独立向量库
- 若并发查询成为瓶颈 → 考虑读副本

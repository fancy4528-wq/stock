# 16 — Token 成本控制

## 1. 为什么单列一份文档

LLM 成本不是"优化项"，而是**决定系统能否长期运行的约束**。

一个每天花 $5 的系统，一年 $1800。对个人研究项目，这个数字会直接导致项目停摆。而且成本失控通常是渐进的：加一个 Agent、多分析几只股票、上下文变长一点，每一步看起来都合理。

所以需要：**预算是硬约束，不是目标。超预算就中止或降级，不是"下次注意"。**

## 2. 成本模型

### 2.1 成本来源

| 来源 | 频率 | 主要成本因素 |
|---|---|---|
| 盘后研究流程 | 每日 1 次 | Agent 数量 × 上下文长度 |
| 盘中监控分诊 | 每日多次 | 新闻量 × 漏斗通过率 |
| 新闻事件抽取 | 每日批量 | 新闻条数 |
| Embedding | 每日批量 | 本地模型，仅算力 |
| 回测/研究临时调用 | 不定 | 需单独预算 |

### 2.2 预算分配

```yaml
# config/llm.yaml
budget:
  # 总预算
  daily_usd_limit: 1.50
  monthly_usd_limit: 40.00

  # 分项预算（各自独立，互不挪用）
  allocations:
    daily_research: 0.80        # 盘后研究流程
    monitoring: 0.30            # 盘中监控
    news_extraction: 0.30       # 新闻事件抽取
    adhoc: 0.10                 # 临时调用

  # 超限行为
  on_exceed:
    daily_research: "degrade"   # 降级：减少 StockAgent 数量
    monitoring: "l1_only"       # 降级：纯规则监控
    news_extraction: "skip"     # 跳过：当日不抽取
    adhoc: "abort"              # 中止

  # 单次调用上限（防单次爆炸）
  per_call_max_tokens_in: 30000
  per_call_max_tokens_out: 4000
```

**分项预算互不挪用**是刻意设计。否则研究流程可能吃掉监控的预算，导致监控失效——而监控的价值密度更高。

### 2.3 目标成本

| 项 | 目标 | 说明 |
|---|---|---|
| 日均总成本 | < $1.50 | 月约 $45 |
| 盘后研究 | < $0.80/日 | 主要开销 |
| 监控 | < $0.30/日 | 三级漏斗后 |
| 新闻抽取 | < $0.30/日 | 批处理 |
| 单条推送成本 | < $0.10 | 质量指标 |
| 单份日报成本 | < $0.80 | — |

这些数字是设计目标，P2 必须实测验证。若实测远超，需削减功能而非提高预算。

## 3. 分层模型策略

### 3.1 三档划分

| 档 | 用途 | 特征 | 调用量 |
|---|---|---|---|
| **小** | 新闻去重分类、L2 分诊、实体识别、粗筛 | 短输入短输出，任务简单 | 极高（每日数十到数百） |
| **中** | 板块分析、个股研究、事件影响判断 | 中等上下文，需要推理 | 中（每日十几次） |
| **大** | Chief 决策汇总、thesis 生成、L3 深度分析 | 长上下文，需要综合 | 低（每日数次） |

```yaml
tiers:
  small:
    provider: "..."
    model: "..."
    max_tokens_out: 512          # ★ 强制限制输出
    temperature: 0.0             # 分类任务用 0
  medium:
    provider: "..."
    model: "..."
    max_tokens_out: 2048
    temperature: 0.3
  large:
    provider: "..."
    model: "..."
    max_tokens_out: 4096
    temperature: 0.3
```

模型具体名称不写进文档（迭代太快），只在配置里指定。

### 3.2 档位选择原则

| 判断 | 用哪档 |
|---|---|
| 任务是分类/抽取，输出是枚举或短 JSON | 小 |
| 任务需要对比多个信息源做推理 | 中 |
| 任务需要综合大量上游输出 | 大 |
| 输出会被人直接阅读 | 中或大 |
| 输出只被程序消费 | 小 |

**最后一条最有用**：如果输出只是给程序判断（如 `is_relevant: bool`），用小模型完全够。只有要给人看的文字才需要大模型的表达能力。

### 3.3 本地模型的位置

| 任务 | 本地可行性 |
|---|---|
| Embedding | ✅ 完全本地（BGE-M3 / bge-large-zh） |
| L2 新闻分诊 | ✅ 可评估（小尺寸中文模型） |
| 实体识别 | ✅ 可用规则 + 词典替代 |
| 板块/个股分析 | ❌ 质量不足 |
| Thesis 生成 | ❌ 质量不足 |

Embedding 走本地是明确决策（01 文档）：每日 2000 条新闻的 embedding 若用 API，成本不划算，且中文表现不必然优于专门的中文模型。

L2 分诊走本地需要实测：用 API 小模型跑 500 条建立基线，本地模型对比准确率，差距 < 5% 则切换。

## 4. 上下文优化

### 4.1 Prompt 中不放数据（最重要）

这是节省成本最有效的手段。

```python
# ❌ 浪费：把数据塞进 prompt
prompt = f"""
分析以下 30 支股票：
{json.dumps(all_financials)}      # 可能 20000+ token
{json.dumps(all_prices)}
"""

# ✅ 节省：让 Agent 通过工具按需取
prompt = """
分析半导体板块。可用工具见下。请按需调用。
"""
# Agent 可能只调用 3 个工具，取 2000 token 的数据
```

好处不只省钱：
- 只取用到的数据
- 每次工具调用被记录（可追溯）
- 上下文更短，模型注意力更集中（长上下文中间内容容易被忽略）

### 4.2 工具返回值截断

```python
class Tool(BaseModel):
    max_rows: int = 100
    max_chars: int = 8000        # ★ 硬上限
```

```python
class ToolResult(BaseModel):
    data: list[dict]
    total_count: int
    truncated: bool              # ★ 明确告知被截断
    note: str | None
```

截断时明确标注，Agent 知道数据不全，可以调整策略（如缩小时间范围重新查询）。

### 4.3 摘要而非全文

| 场景 | 传什么 |
|---|---|
| L2 新闻分诊 | 标题 + 200 字 |
| L3 深度分析 | 标题 + 全文（仅此场景） |
| 财报分析 | 结构化指标，不传原文 |
| 公告判断 | 类型 + 标题，不传全文 |
| 历史新闻回顾 | 只传 summary 字段 |

`event.summary` 字段（NewsExtractor 生成的 200 字概括）在后续所有引用中替代全文。抽取一次，多次复用。

### 4.4 输出 Schema 极简化

输出 token 通常比输入 token 贵，且容易被忽略。

```python
# ❌ 字段名冗长，且有大量可选描述
class Verbose(BaseModel):
    is_relevant_to_portfolio: bool
    affected_security_symbols: list[str]
    impact_direction_assessment: str
    detailed_reasoning: str          # ★ 最贵的字段

# ✅ 批处理场景用缩写，程序侧映射回来
class Compact(BaseModel):
    rel: bool
    sym: list[str] = []
    dir: str = ""
    urg: str = ""
```

**关键：非必要不要 `reasoning` 字段。** LLM 写理由会产生大量 token。只在需要给人看的场景保留（如 L3 分析、thesis）。

L2 分诊不需要理由——它只是分诊，判断错了由 L3 纠正。

### 4.5 Prompt 前缀缓存

多数提供商支持 prompt 缓存。要点是**把固定内容放前面**：

```python
def build_prompt(news: News, holdings: Holdings) -> str:
    return (
        SYSTEM_INSTRUCTIONS      # 固定，全天不变 → 可缓存
        + KEYWORD_REFERENCE      # 固定 → 可缓存
        + holdings.compact()     # 每日变一次 → 可缓存
        + f"\n新闻：{news.title}" # 每次变 → 不缓存
    )
```

具体折扣与最小缓存长度因提供商而异，需在 P2 实测。若命中率高，可节省 30-50% 输入成本。

### 4.6 批处理

适用于同质任务（新闻分诊、事件抽取）。

```python
# 5 条新闻一次调用，系统 prompt 只算一次
BATCH_SIZE = 10   # 需实测最优值
```

权衡：批太大质量下降，批太小节省有限。P2 实测 5 / 10 / 20 三档的质量与成本。

### 4.7 两阶段筛选

见 02 文档 3.2 节。核心：**用量化粗筛代替 LLM 粗筛。**

```
全市场 5000 支 / 31 行业 / 300 概念
    ↓  量化粗筛（零 LLM 成本）
Top 5 行业 + Top 3 概念
    ↓  LLM 精研
~8 板块 + ~30 个股
```

如果让 LLM 做全市场粗筛，成本会高两个数量级，而量化指标（动量、资金流、估值分位）做粗筛效果并不差。

## 5. 缓存策略

### 5.1 三层缓存

| 层 | Key | TTL | 用途 |
|---|---|---|---|
| 结果缓存 | `内容哈希 + 持仓哈希` | 24h | 相同新闻不重复分析 |
| 工具缓存 | `工具名 + 参数 + as_of` | 当日 | 同一 run 内重复查询 |
| Prompt 缓存 | 提供商侧 | 提供商定 | 固定前缀 |

### 5.2 结果缓存实现

```python
class LLMResultCache:
    async def get_or_call(
        self, cache_key: str, call_fn: Callable, ttl: int = 86400
    ) -> tuple[Any, bool]:
        if cached := await self._redis.get(cache_key):
            self._metrics.hit()
            return json.loads(cached), True
        result = await call_fn()
        await self._redis.set(cache_key, json.dumps(result), ex=ttl)
        self._metrics.miss()
        return result, False
```

缓存 key 必须包含所有影响结果的输入。漏掉某个输入会导致返回错误的缓存结果——这类 bug 很隐蔽。

### 5.3 缓存命中率监控

```sql
SELECT
    date_trunc('day', created_at) AS day,
    count(*) AS total_calls,
    sum(CASE WHEN cache_hit THEN 1 ELSE 0 END) AS hits,
    round(100.0 * sum(CASE WHEN cache_hit THEN 1 ELSE 0 END) / count(*), 1) AS hit_rate_pct,
    sum(cost_usd) AS actual_cost,
    sum(estimated_cost_without_cache) AS would_be_cost
FROM agent_trace
GROUP BY 1 ORDER BY 1 DESC;
```

命中率过低（< 10%）说明缓存 key 设计不当或场景不适合缓存。

## 6. 预算执行机制

### 6.1 调用前检查（不是事后统计）

```python
class TokenBudget:
    async def check_and_reserve(
        self, allocation: str, estimated_tokens_in: int,
        estimated_tokens_out: int, tier: str,
    ) -> BudgetReservation:
        """★ 调用前估算并预留。超限则抛异常或降级。"""
        est_cost = self._price(tier, estimated_tokens_in, estimated_tokens_out)
        spent = await self._get_spent(allocation)
        limit = self._cfg.allocations[allocation]

        if spent + est_cost > limit:
            action = self._cfg.on_exceed[allocation]
            if action == "abort":
                raise BudgetExceeded(allocation, spent, limit, est_cost)
            if action == "degrade":
                raise BudgetDegrade(allocation, suggested_tier="small")
            if action in ("l1_only", "skip"):
                raise BudgetSkip(allocation, action)

        return BudgetReservation(allocation, est_cost)
```

**事后统计毫无用处**——钱已经花了。必须在调用前估算并拦截。

输入 token 可以精确计算（tokenizer），输出 token 用 `max_tokens_out` 作为上界估算。

### 6.2 降级路径

| 分配项 | 降级动作 | 保留能力 |
|---|---|---|
| `daily_research` | 减少 StockAgent 数量（30 → 10 → 0） | 板块分析仍在 |
| `daily_research` | 进一步降级：ChiefAgent 用中模型 | 日报仍生成 |
| `monitoring` | 降为 L1 纯规则 | **止损、跌停、停牌、风控告警仍有效** |
| `news_extraction` | 只抽取持仓相关新闻 | 关键事件仍捕获 |
| `news_extraction` | 完全跳过 | 新闻仅入库不抽取，次日补 |

降级必须**显式记录并在输出中声明**：

```python
class DegradationNote(BaseModel):
    allocation: str
    action: str
    reason: str
    impact: str        # 对输出质量的影响说明
```

日报和推送中必须显示："今日因预算限制，未分析个股层面（降级）"。用户需要知道报告是不完整的。

### 6.3 单次调用上限

```yaml
per_call_max_tokens_in: 30000
per_call_max_tokens_out: 4000
```

防止单次调用意外爆炸（如某个工具返回了超大结果集）。超限直接拒绝调用，而非截断后继续——因为截断可能导致模型看到不完整数据得出错误结论。

## 7. 成本追踪与归因

### 7.1 记录粒度

`agent_trace` 表已有的字段（03 文档）：

```sql
tokens_in     INT NOT NULL,
tokens_out    INT NOT NULL,
cost_usd      NUMERIC(12,6),
```

需增补：

```sql
ALTER TABLE agent_trace ADD COLUMN allocation TEXT;          -- 预算分项
ALTER TABLE agent_trace ADD COLUMN cache_hit BOOLEAN DEFAULT FALSE;
ALTER TABLE agent_trace ADD COLUMN batch_size INT DEFAULT 1;
ALTER TABLE agent_trace ADD COLUMN estimated_cost_without_cache NUMERIC(12,6);
ALTER TABLE agent_trace ADD COLUMN degraded BOOLEAN DEFAULT FALSE;
```

### 7.2 成本归因查询

```sql
-- 按 Agent 归因
SELECT agent_name, tier,
       count(*) AS calls,
       sum(tokens_in) AS tin, sum(tokens_out) AS tout,
       sum(cost_usd) AS cost,
       round(avg(cost_usd), 5) AS avg_cost_per_call
FROM agent_trace
WHERE created_at > now() - interval '30 days'
GROUP BY 1, 2 ORDER BY cost DESC;
```

```sql
-- 按预算分项
SELECT allocation, date_trunc('day', created_at) AS day, sum(cost_usd)
FROM agent_trace GROUP BY 1, 2 ORDER BY 2 DESC, 3 DESC;
```

```sql
-- ★ 单位价值：每条推送的成本
SELECT
    date_trunc('week', a.created_at) AS week,
    count(*) AS alerts,
    sum(a.cost_usd) AS total_cost,
    round(sum(a.cost_usd) / count(*), 4) AS cost_per_alert,
    round(100.0 * count(*) FILTER (WHERE a.feedback = 'useful')
          / nullif(count(a.feedback), 0), 1) AS useful_pct,
    -- 有用推送的单位成本
    round(sum(a.cost_usd) / nullif(count(*) FILTER (WHERE a.feedback = 'useful'), 0), 4)
        AS cost_per_useful_alert
FROM alert a
GROUP BY 1 ORDER BY 1 DESC;
```

最后一列 `cost_per_useful_alert` 是最有意义的指标：**每次真正有用的提醒花了多少钱。** 如果这个数字超过 $0.30，说明系统在为无用推送买单。

### 7.3 成本日志

维护 `docs/cost-log.md`，每月记录：

```markdown
## 2026-09 成本记录

### 汇总
| 项 | 预算 | 实际 | 占比 |
|---|---|---|---|
| 盘后研究 | $24.00 | $19.40 | 81% |
| 监控 | $9.00 | $4.20 | 47% |
| 新闻抽取 | $9.00 | $8.80 | 98% |
| 合计 | $45.00 | $32.40 | 72% |

### 按 Agent
| Agent | 调用 | 成本 | 占比 |
|---|---|---|---|
| StockAgent | 780 | $12.10 | 37% |
| IndustryAgent | 150 | $4.20 | 13% |
| ChiefAgent | 30 | $3.10 | 10% |
| NewsExtractor | 4,200 | $8.80 | 27% |
| L2 Triage | 1,400 | $2.90 | 9% |
| L3 Analysis | 180 | $1.30 | 4% |

### 优化记录
- 09-08 L2 改批处理（批大小 10），成本降 38%
- 09-15 工具返回值上限从 12000 降到 8000 字符，StockAgent 成本降 22%
- 09-22 启用 prompt 前缀缓存，输入成本降 31%

### 单位指标
- 单份日报: $0.62
- 单条推送: $0.043
- 单条有用推送: $0.081
- 缓存命中率: 24%

### 问题
- NewsExtractor 占比 27% 偏高。10 月尝试本地小模型替代。
```

## 8. 成本优化优先级

按投入产出比排序：

| # | 优化 | 节省 | 实现难度 |
|---|---|---|---|
| 1 | L1 规则前置过滤（监控） | ~99% | 低 |
| 2 | 量化粗筛替代 LLM 粗筛 | ~95% | 低 |
| 3 | Prompt 中不放数据，改用工具 | ~80% | 低（架构已如此） |
| 4 | 输出 schema 去掉 reasoning 字段 | ~70% 输出 | 低 |
| 5 | 只传标题摘要不传全文 | ~80% | 低 |
| 6 | 批处理 | ~40% | 低 |
| 7 | 模型分层 | ~60% | 低 |
| 8 | 工具返回值截断 | ~30% | 低 |
| 9 | Prompt 前缀缓存 | ~30-50% 输入 | 中 |
| 10 | 结果缓存 | 视重复率 | 中 |
| 11 | 本地小模型替代 L2 | ~100%（该部分） | 中 |
| 12 | 减少 StockAgent 数量 | 线性 | 低（但损失能力） |

前 8 项都是低难度高收益，应在 P2 一次做完。9-11 项在 P2b 视实测情况实施。

第 12 项是最后手段——它直接削减能力，只在预算实在不够时用。

### 8.1 知识库的成本结构

知识库有个反直觉的性质：**入库不花钱，取出来才花钱。**

| 环节 | 成本 |
|---|---|
| Embedding（本地 bge-m3） | **0** |
| 向量存储（pgvector） | 磁盘，可忽略 |
| 向量检索（SQL） | **0** |
| **检索结果进 prompt** | ★ 唯一成本 |

所以着力点是 `top_k` 和片段长度，不是入库量：

| 参数 | 默认 | 说明 |
|---|---|---|
| `top_k` | 3-5 | 超过 5 通常是噪声 |
| 片段长度 | ≤800 字 | 切片时控制 |
| 工具返回截断 | 2000 字符 | `Tool.max_chars` |

单次检索约 2-3k token 输入，计入 `daily_research` 分项。

**更大的节省来自不入库。** 一份 5 万字制度手册常驻 prompt 约 7 万 token/次，按每日 40 次算会吃掉整个 `daily_research` 预算——而换来的是模型本来就大致知道的内容。正确做法是把规则提取成配置参数（成本为零），Agent 只看 `is_limit_up = true` 这个算好的字段。

按途径排序的成本关系：**配置（零）< 工具（低）< RAG（中）< Prompt 常驻（高）**。选择判据见 [17-knowledge-base](17-knowledge-base.md) 1.2 节。

## 9. 反模式清单

| 反模式 | 为什么错 |
|---|---|
| 把所有数据塞进 prompt "让模型自己找" | 成本爆炸，且长上下文中间内容易被忽略 |
| 每条新闻单独调 LLM 判断相关性 | L1 规则能过滤 99%，不该花这个钱 |
| 让 LLM 输出详细 reasoning 然后丢弃 | 输出 token 是纯浪费 |
| 用大模型做分类任务 | 小模型足够 |
| 不设 `max_tokens_out` | 模型可能生成极长输出 |
| 事后统计成本 | 钱已花完，无法拦截 |
| 单一总预算，各功能共享 | 一个功能会吃掉其他功能的预算 |
| 超预算后提高预算 | 预算是约束，不是目标 |
| 让 LLM 做全市场扫描 | 量化指标做粗筛效果不差且免费 |
| 重复分析相同新闻（多源转载） | 应先去重 + 缓存 |
| 缓存 key 漏掉影响结果的输入 | 返回错误的缓存结果，隐蔽 bug |
| 静默降级不告知用户 | 用户以为报告完整，实际不完整 |
| 把金融教科书灌进知识库 | 预训练已掌握，花预算换零增益（见 ADR-0011） |
| 制度规则全文入 RAG | 应提取成配置参数，成本为零且更精确 |
| 财务数字入向量库 | 应走结构化表 + 工具，向量检索对精确事实不可靠 |
| `top_k` 设成 10+ | 超过 5 通常是噪声，且线性推高成本 |
| 用 API 做 embedding | 本地 bge-m3 质量足够，成本为零 |

## 10. 验收清单

Gate 2（P2）：

- [ ] 三档模型配置生效
- [ ] 每次调用前预算检查（不是事后统计）
- [ ] 分项预算独立，互不挪用
- [ ] 超限降级路径全部实现且有测试
- [ ] 降级在输出中显式声明
- [ ] `max_tokens_out` 全部设置
- [ ] 单次调用上限生效
- [ ] Prompt 中不含批量数据（代码审查）
- [ ] 工具返回值有 `max_chars` 上限
- [ ] 输出 schema 无冗余 reasoning 字段（除需给人看的场景）
- [ ] 批处理实现且实测最优批大小
- [ ] 结果缓存实现，命中率可查
- [ ] `agent_trace` 记录 allocation / cache_hit / batch_size
- [ ] 成本归因查询可用
- [ ] `cost-log.md` 首月数据已记录
- [ ] 日均成本 < $1.50
- [ ] 单条有用推送成本 < $0.30
- [ ] Embedding 本地跑通，API 成本为 0
- [ ] 知识库不含教科书/投资流派材料（代码审查）
- [ ] RAG `top_k` 默认 ≤ 5

Gate 2b（P2b，监控智能层）：

- [ ] L1 通过率 < 5%
- [ ] 监控层日均成本 < $0.30
- [ ] 预算耗尽时降级为 L1 且关键监控仍有效（有测试）
- [ ] 本地小模型方案已评估（采用或明确否决）

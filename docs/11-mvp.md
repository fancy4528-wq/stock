# 11 — MVP 定义

## 1. MVP 的定位

**MVP = P0 + P1**，目标是：**每天自动产出一份可信、可追溯的 A 股市场研究日报。**

不是赚钱，不是交易，不是多 Agent。是把地基和最小闭环建起来。

### 1.1 一句话验收标准

> 连续 20 个交易日，无需人工干预，每天 18:00 前自动生成一份日报；日报中每个数字都能追溯到数据库中的具体记录；且未来函数哨兵测试通过。

## 2. 范围定义

### 2.1 做什么

| 维度 | MVP 范围 |
|---|---|
| 市场 | A 股（仅） |
| 股票池 | 50 支（见 3 节的选取规则） |
| 数据 | 日线行情、复权因子、财务报表、估值、行业归属、资金流、交易日历 |
| 新闻 | 采集 + 入库 + 去重（**不做 LLM 抽取**） |
| 因子 | 8-10 个基础因子（动量、反转、波动率、换手率、估值） |
| 模型 | L0 Buy&Hold + L1 单因子排序（**不做 ML**） |
| Agent | **1 个**：日报生成 Agent（不做多 Agent 编排） |
| 组合 | 等权 Top N，无优化 |
| 风控 | 基础 hard 规则（仓位、流动性、排除类） |
| 执行 | `SimulatedBroker` only |
| 输出 | Markdown 日报 + Shadow Portfolio 记录 |
| UI | 无（CLI + 文件） |

### 2.2 明确不做什么

| 不做 | 原因 | 何时做 |
|---|---|---|
| 多 Agent 编排 | 先验证数据和管道 | P2 |
| LLM 新闻事件抽取 | 成本与效果需先评估 | P2 |
| 向量库 / RAG | 结构化数据优先 | P2 |
| **盘中监控与推送** | 需先有持仓概念和新闻数据 | P2a |
| **实时行情快照** | 同上 | P2a |
| 机器学习模型 | 需先有 baseline 和因子测试 | P3 |
| 完整回测引擎 | MVP 只需 Buy&Hold 基准 | P4 |
| Portfolio 优化 | 等权足够验证流程 | P5 |
| **冷启动建仓推荐** | 需相关性去冗余 + 完整风控 + shadow 成绩，否则会推出一篮子高相关标的 | P5 |
| **板块权限过滤 / 止盈止损策略** | 依赖组合与风控框架；MVP 阶段不给买卖建议 | P5 |
| 真实交易 | — | P6/P7 |
| Web UI | Markdown 更快更有用 | P5+ |
| 美股 | — | P6 |
| 概念板块 Agent | — | P2 |

### 2.3 为什么砍到这么小

原始草案的 MVP 是"4 板块 + 30-50 股 + 全套 Agent + LightGBM"。这仍然太大，会出现的问题：

- 数据没验证就上 Agent，Agent 的输出错误无法归因（是数据错还是 Agent 错）
- 没有 baseline 就上 ML，无法判断模型是否有价值
- 多 Agent 编排的调试成本高，会消耗掉全部时间

**MVP 的唯一目标是建立"可信"这个基础。** 一旦数据可信、管道可信，后面的迭代会快得多。

## 3. 股票池定义

### 3.1 选取规则（规则生成，非手选）

```yaml
# config/universe/mvp_cn.yaml
code: "mvp_cn_50"
name: "MVP A股50"
market: CN
rule:
  base: "csi300"                    # 从沪深300中选
  filters:
    - "list_days >= 750"            # 上市满 3 年（有足够历史）
    - "avg_amount_20d >= 100000000" # 20日均成交额 ≥ 1亿（流动性好）
    - "not is_st"
    - "not is_suspended"
  industry_coverage:
    min_industries: 10              # 至少覆盖 10 个申万一级行业
    max_per_industry: 8             # 单行业最多 8 支
  select:
    method: "top_by_market_cap"     # 每行业按市值取前 N
    total: 50
  snapshot_frequency: "monthly"     # 每月重新快照
```

### 3.2 为什么规则生成而非手选

手选会引入两个偏差：
- **选择偏差**：会不自觉选自己熟悉/看好的股票
- **生存者偏差**：会选现在表现好的股票

规则生成 + 按时点快照，保证回测时用的是当时的成分。

### 3.3 为什么 50 支

| 考虑 | 说明 |
|---|---|
| 数据量可控 | 50 支 × 10 年日线 ≈ 15 MB，本地开发快 |
| 足够做截面分析 | 因子的截面标准化需要一定样本量 |
| 覆盖多行业 | 能验证行业中性化、行业集中度风控 |
| LLM 成本可控 | 日报 Agent 一次调用即可覆盖 |

## 4. 交付物清单

### 4.1 代码交付

| 模块 | 内容 | 验收 |
|---|---|---|
| `infra/` | docker-compose + 初始化脚本 | `docker compose up -d` 一键启动 |
| `migrations/` | Alembic 迁移，含全部核心表 | `make db-init` 建库成功 |
| `data/collectors/` | akshare + baostock + tushare Collector | 原始数据归档为 Parquet |
| `data/normalizers/` | 代码归一化、单位统一 | 单元测试覆盖所有代码段 |
| `data/validators/` | 校验规则（04 文档中的规则表） | FATAL 能中止流程 |
| `data/loaders/` | PIT 写入逻辑 | 修订产生新 revision，不覆盖 |
| `core/repository/` | `PITRepository` + `as_of` SQL 函数 | 所有方法强制 `as_of` |
| `core/calendar/` | 交易日历 | 双源一致 |
| `quant/features/` | 8-10 个基础因子 | 纯函数 + 单元测试 |
| `quant/evaluation/` | IC 计算、分层测试 | 每个因子有测试报告 |
| `backtest/` | 最小回测引擎（Buy&Hold + 单因子） | 含 T+1、涨跌停、成本 |
| `portfolio/` | 等权组合构建 | — |
| `risk/` | 基础 hard 规则 | 每条规则有测试 |
| `execution/` | `BrokerAdapter` + `SimulatedBroker` | 幂等 + 状态机 |
| `agents/reporter/` | 日报生成 Agent | 结构化输出 + evidence |
| `evaluation/shadow/` | Shadow Portfolio | append-only 记录 |
| `reporting/` | Markdown 日报模板 | — |
| `scheduler/` | APScheduler 定时任务 | 每日自动运行 |

### 4.2 文档交付

| 文档 | 内容 |
|---|---|
| `docs/data-access-log.md` | 各数据源接口清单、积分等级、已知问题 |
| `docs/factor-reports/` | 每个因子的测试报告 |
| `docs/cost-log.md` | LLM token 消耗实测记录 |
| `docs/baseline-results.md` | Buy&Hold 与单因子回测基线结果（后续对比用） |

### 4.3 日报样例

```markdown
# A股市场日报 2026-09-01

> 数据截止 2026-08-31 15:00 收盘 | run_id: 20260831-cn-daily
> ⚠️ 本报告由系统自动生成，不构成投资建议

## 一、市场概况

沪深300 收于 3,842.15，涨 0.62%。50 支池内标的中 32 支上涨，
成交额合计 486 亿元，较 20 日均值 +12%。

| 指标 | 数值 | 20日分位 |
|---|---|---|
| 池内涨跌比 | 32:18 | 68% |
| 池内成交额 | 486亿 | 74% |
| 池内平均换手 | 1.82% | 61% |

## 二、行业表现（池内标的按申万一级归类）

| 行业 | 标的数 | 平均涨幅 | 5日 | 20日 |
|---|---|---|---|---|
| 电子 | 8 | +1.84% | +3.2% | +8.7% |
| 食品饮料 | 6 | -0.42% | -1.1% | -3.4% |
| ... | | | | |

## 三、因子表现

| 因子 | 今日多空收益 | 20日IC均值 |
|---|---|---|
| mom_20d | +0.31% | 0.042 |
| rev_5d | -0.18% | -0.028 |
| turnover_20d | +0.22% | 0.035 |
| ... | | |

## 四、单因子排序（mom_20d，Top 5）

| 排名 | 代码 | 名称 | 因子分位 | 20日涨幅 |
|---|---|---|---|---|
| 1 | 600xxx | XX | 0.98 | +18.2% |
| ... | | | | |

## 五、Shadow Portfolio 状态

| 组合 | 今日 | 累计 | 最大回撤 | 持仓数 |
|---|---|---|---|---|
| shadow_baseline（等权） | +0.58% | +4.2% | -3.1% | 50 |
| shadow_factor（mom_20d Top15） | +0.71% | +6.8% | -4.4% | 15 |

## 六、风控提示

- 触发 `POS_002`：电子行业权重 24.1%（上限 25%）
- 当前回撤 -4.4%（阈值 -15%）
- 未执行项：300xxx 昨日涨停，未能建仓

## 七、数据质量

| 检查 | 结果 |
|---|---|
| 行情完整性 | 50/50 ✅ |
| 双源校验 | 通过（最大差异 0.02%）✅ |
| 财务数据 | 无新增 |
| PIT 校验 | 通过 ✅ |
| 未来函数哨兵 | 通过 ✅ |

## 八、附录：数据溯源

本报告数据来源：
- 行情：akshare（主）/ baostock（校验），batch_id 12847
- 因子：code_version a3f8c21
- 全部数字可通过 `run_id=20260831-cn-daily` 在数据库中追溯
```

**注意日报中没有"买入建议"。** MVP 阶段只做事实陈述和因子排序，不做投资判断。判断能力要等 P2 的多 Agent 和 P3 的模型建立后才有基础。

## 5. MVP 中的单 Agent 设计

### 5.1 为什么只有一个 Agent

MVP 的 Agent 只做一件事：**把结构化数据转成可读的日报文字。**

它不做投资判断，不给评分，不做预测。理由：
- 先验证 LLM 集成、工具调用、结构化输出、evidence 追溯这套机制能跑通
- 先实测 token 成本
- 避免在数据未验证时就产生看似有用实则无意义的判断

### 5.2 ReporterAgent

```python
class DailyReport(BaseModel):
    as_of: date
    run_id: str

    market_summary: str = Field(max_length=400, description="事实陈述，不含判断")
    sector_summary: str = Field(max_length=400)
    factor_summary: str = Field(max_length=300)
    notable_observations: list[Observation] = Field(max_length=5)
    data_quality_note: str | None

    evidence: list[Evidence] = Field(min_length=3)

class Observation(BaseModel):
    """值得注意的现象。仅陈述，不推断原因。"""
    statement: str = Field(max_length=200)
    metric: str
    value: float
    evidence_refs: list[str] = Field(min_length=1)
```

Prompt 约束（在通用约束之外额外加）：

```
本次任务是生成事实性市场日报。额外约束：
- 只陈述数据显示的事实，不推断原因
- 不做涨跌预测
- 不给出买卖建议
- 不评价任何标的的投资价值
- 使用「数据显示」「较前值」等客观表述
- 如需提及异常，只说「偏离历史均值 N 个标准差」，不解释为什么
```

最后一条很重要：让 LLM 解释"为什么涨"会得到大量编造的因果关系。MVP 阶段明确禁止。

工具（4 个，最小集）：

| 工具 | 说明 |
|---|---|
| `get_market_overview(as_of)` | 池内涨跌统计、成交额、换手 |
| `get_sector_performance(as_of)` | 行业分组表现 |
| `get_factor_performance(as_of)` | 因子多空收益与 IC |
| `get_shadow_status(as_of)` | Shadow 组合状态 |

## 6. MVP 因子清单

只做 8 个，覆盖主要类别，都是价格/成交量派生（不依赖财务数据的复杂处理）：

| 因子 | 类别 | 选取理由 |
|---|---|---|
| `mom_20d` | 动量 | 最经典 |
| `mom_60d` | 动量 | 中期 |
| `rev_5d` | 反转 | A 股短期反转显著 |
| `vol_20d` | 波动率 | 风险维度 |
| `turnover_20d` | 流动性 | A 股换手率因子有效性较强 |
| `turnover_ratio_5_60` | 流动性 | 关注度突变 |
| `ep_ttm` | 价值 | 基础估值（依赖财务，验证 PIT） |
| `amihud_illiq_20d` | 流动性 | 非流动性溢价 |

`ep_ttm` 特意包含：它依赖财务数据的 PIT 处理，是验证 PIT 机制是否正确的最佳测试用例。

## 7. 时间估算与任务分解

### 7.1 P0（3-4 周）

| 周 | 任务 |
|---|---|
| W1 | docker-compose、数据库 schema、Alembic 迁移、交易日历 |
| W2 | Collector（akshare 行情 + baostock 校验）、Normalizer、原始归档 |
| W3 | Validator 规则、Loader（PIT 写入）、`PITRepository` + SQL 函数 |
| W4 | 财务数据管道（PIT 重点）、未来函数哨兵测试、Buy&Hold 回测 |

P0 完成标志：`make backtest-baseline` 能跑出沪深300 Buy&Hold 结果，且哨兵测试通过。

### 7.2 P1（3-4 周）

| 周 | 任务 |
|---|---|
| W5 | 8 个因子实现 + 单元测试 |
| W6 | 因子评估（IC、分层、报告生成） |
| W7 | 最小组合构建 + 基础风控 + `SimulatedBroker` |
| W8 | ReporterAgent、日报模板、Shadow Portfolio、调度器 |

P1 完成标志：连续 20 个交易日自动产出日报，Shadow Portfolio 开始积累。

### 7.3 关键路径

```
数据库 schema ──▶ Collector ──▶ Validator ──▶ Repository ──┐
                                                            ▼
交易日历 ──────────────────────────────────────────▶ 因子计算
                                                            │
                                                            ▼
                                          因子评估 ──▶ 组合 ──▶ Shadow
                                                            │
                                                            ▼
                                                         日报 Agent
```

`PITRepository` 是关键节点，它没做好后面全部要返工。

## 8. MVP 验收清单（Gate 1）

### 8.1 数据正确性

- [ ] 50 支池内标的 10 年日线完整，缺失率 < 1%
- [ ] 双源行情校验通过，差异 < 0.5%
- [ ] 财务数据带 `announced_at`，修订产生新 revision
- [ ] 复权因子 PIT，存未复权价
- [ ] 行业归属按区间存储
- [ ] `universe_snapshot` 有月度历史快照
- [ ] 退市股票保留（若池内有）
- [ ] 交易日历双源一致，覆盖 10 年 + 未来 1 年
- [ ] `is_limit_up/down`、`is_suspended` 字段正确
- [ ] 全部 FATAL 级校验规则实现且能中止流程
- [ ] 原始数据归档为 Parquet，可重放 normalize

### 8.2 PIT 正确性（最重要）

- [ ] **未来函数哨兵测试通过**
- [ ] 所有 `Repository` 方法强制 `as_of`（keyword-only 无默认值）
- [ ] `get_financials_as_of` 正确过滤 `announced_at`
- [ ] `get_universe_as_of` 返回历史成分而非当前成分
- [ ] 运行时断言 `assert_no_lookahead` 已接入
- [ ] CI 含 PIT 静态检查（禁止业务代码写 SQL）
- [ ] 生存者偏差测试通过

### 8.3 因子与回测

- [ ] 8 个因子实现，均为纯函数
- [ ] 每个因子有单元测试（构造数据验证计算正确）
- [ ] 每个因子有 IC / 分层测试报告
- [ ] `ep_ttm` 因子的 PIT 正确性单独验证
- [ ] Buy&Hold 基准回测可跑，结果记入 `baseline-results.md`
- [ ] 单因子回测结果与 IC 分析一致（验证回测引擎正确）
- [ ] 回测含 T+1、涨跌停、停牌、成本
- [ ] 涨跌停拒单有统计输出

### 8.4 流程自动化

- [ ] 调度器每日自动运行，无需人工触发
- [ ] 连续 20 个交易日无中断
- [ ] 数据质量 FATAL 时正确中止且告警
- [ ] 数据源失效时正确降级并标注
- [ ] `run_id` 贯穿全链路

### 8.5 Agent 与日报

- [ ] ReporterAgent 输出通过 Pydantic 校验，失败率 < 5%
- [ ] Evidence 覆盖率 100%
- [ ] 日报中数字可追溯（抽检 20 个数字全部命中）
- [ ] 无编造的因果解释（人工抽检 5 份日报）
- [ ] Token 成本实测记入 `cost-log.md`

### 8.6 Shadow Portfolio

- [ ] `shadow_baseline`（等权 50）已启动
- [ ] `shadow_factor`（单因子 Top15）已启动
- [ ] 记录 append-only（触发器生效）
- [ ] 成本模型完整
- [ ] 未执行项（涨停买不进）有记录

### 8.7 工程质量

- [ ] 测试覆盖率 > 70%（核心模块 > 85%）
- [ ] mypy strict 通过
- [ ] ruff 无警告
- [ ] `make` 命令齐备（db-init / ingest / backtest / report / test）
- [ ] README 的快速上手步骤可用
- [ ] 无硬编码市场常量（CI 检查通过）

## 9. MVP 之后的第一件事

Gate 1 通过后，**立即启动 Shadow Portfolio 的持续积累**，然后才开始 P2 的多 Agent。

理由：Shadow 需要真实时间，越早开始越好。P2/P3 的开发可以与 Shadow 积累并行。

```
Gate 1 通过
    ├──▶ Shadow 持续积累（后台，不占开发时间）
    └──▶ P2 多 Agent 开发
```

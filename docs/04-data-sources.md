# 04 — 数据源

## 1. 数据源清单（A 股）

### 1.1 主源与备源

原则：**关键数据双源，交叉校验。** 单一数据源必然有错，且错误不会告诉你。

| 数据类别 | 主源 | 备源 | 校验方式 |
|---|---|---|---|
| 日线行情 | akshare | baostock | 逐字段比对，容差 0.01 |
| 复权因子 | akshare | tushare | 比对，差异告警 |
| 财务报表 | tushare | akshare | 关键科目比对 |
| 行业分类 | akshare(申万) | tushare | 归属一致性 |
| 指数成分 | akshare | tushare | 成分集合比对 |
| 资金流 | akshare(东财) | — | 单源，仅做内部一致性校验 |
| 概念板块 | akshare(东财) | akshare(同花顺) | 不强制一致（口径本就不同） |
| 交易日历 | akshare | tushare | 必须完全一致 |
| 公告 | 交易所官网 | 巨潮 | 按公告编号去重 |
| 新闻快讯 | 财联社电报 | 东财快讯 | 内容哈希去重 |
| 宏观数据 | 国家统计局 | FRED(海外部分) | — |

### 1.2 各源特性

**akshare**

| 项 | 说明 |
|---|---|
| 成本 | 免费 |
| 覆盖 | 极广（行情/财务/板块/资金流/龙虎榜等） |
| 稳定性 | 一般。底层多为网页抓取，接口会因源站改版失效 |
| 限频 | 无明确限制，但需自我约束（建议 ≤2 req/s） |
| 风险 | **最大风险源**。必须有重试、校验、失效告警 |

应对措施：
- 每个 akshare 调用包裹 `tenacity` 重试（指数退避，最多 3 次）
- 返回结果做 schema 校验（列名、类型、行数范围）
- 接口失效时不静默跳过，必须告警并中止依赖流程
- **版本与字段以当日实测为准**（记入 `docs/data-access-log.md`），设计稿里的 pin 版本会过期；升级前跑完整回归
- 示例拉取窗口应覆盖「当前月」附近交易日，避免只用多年前样本冒充接口仍可用

**tushare**

| 项 | 说明 |
|---|---|
| 成本 | 积分制。基础接口低积分可用，财务/高频数据需较高积分 |
| 覆盖 | 财务数据质量优于 akshare |
| 稳定性 | 好（官方 API） |
| 限频 | 按积分等级限制每分钟调用次数 |
| 用途 | 财务主源 + 行情校验源 |

需要在 P0 阶段确认自己的积分等级能覆盖哪些接口，并把接口清单写入 `docs/data-access-log.md`。

**baostock**

| 项 | 说明 |
|---|---|
| 成本 | 免费 |
| 覆盖 | 行情、基础财务 |
| 稳定性 | 好，历史数据质量高 |
| 限频 | 需登录会话，单连接串行 |
| 用途 | 行情校验源、历史数据回填 |

### 1.3 新闻与公告源

| 源 | 内容 | 获取方式 | 频率 |
|---|---|---|---|
| 财联社电报 | 实时快讯，A 股最快的公开源之一 | akshare 接口 / 网页 | 5 分钟轮询 |
| 东财快讯 | 快讯 + 研报摘要 | akshare | 15 分钟 |
| 上交所公告 | 法定公告 | 官网列表页 | 每日 3 次 |
| 深交所公告 | 法定公告 | 官网列表页 | 每日 3 次 |
| 巨潮资讯 | 全市场公告汇总 | 网页 | 每日 1 次（补漏） |
| 央行/发改委等 | 政策文件 | 官网 RSS/列表 | 每日 1 次 |

抓取约定：

| 约定 | 说明 |
|---|---|
| 遵守 robots.txt | 抓取前检查 |
| 限频 | 单站 ≤1 req/2s，带 User-Agent 标识 |
| 不抓付费墙内容 | 仅公开可访问内容 |
| 原文归档 | 保留原始 HTML/JSON，不只存解析结果 |
| 失败不重试风暴 | 连续失败 3 次后停止当轮，告警 |

### 1.4 美股源（P6 启用）

| 数据 | 源 | 说明 |
|---|---|---|
| 行情 | Alpaca Market Data | 免费档为 IEX 数据；全市场 SIP 数据需付费。差异需评估 |
| 基本面 | SEC EDGAR | 官方 XBRL，免费，质量高 |
| 宏观 | FRED | 官方，免费 |
| 新闻 | Alpaca News / 公开 RSS | — |
| 交易日历 | Alpaca / pandas_market_calendars | — |

注意：Alpaca 免费档的 IEX 数据只覆盖 IEX 交易所的成交，与全市场价格有差异。做研究可接受，但要知道这个偏差存在。

## 2. 采集架构

### 2.1 三段式管道

```
┌──────────┐    ┌────────────┐    ┌───────────┐    ┌────────┐
│ Collector│───▶│ Normalizer │───▶│ Validator │───▶│ Loader │
└──────────┘    └────────────┘    └───────────┘    └────────┘
     │                                   │
     ▼                                   ▼
 raw Parquet 归档                  data_quality_check 表
```

每段职责严格分离：

| 段 | 输入 | 输出 | 允许做 | 禁止做 |
|---|---|---|---|---|
| Collector | 无 | 原始响应 | 重试、限频、归档 | 解析、清洗、判断 |
| Normalizer | 原始响应 | 标准 DataFrame | 列名映射、单位换算、代码归一 | 修数、丢弃异常行 |
| Validator | 标准 DataFrame | 校验报告 | 检查、打标记 | 改数 |
| Loader | 标准 DataFrame | 数据库行 | UPSERT、版本管理 | 覆盖历史版本 |

### 2.2 Collector 契约

```python
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

class Collector(ABC):
    """采集器基类。只负责取数和归档，不做任何解释。"""

    source: str          # 'akshare' | 'tushare' | 'cls' | ...
    dataset: str         # 'price_daily' | 'financial' | 'news' | ...
    rate_limit: float    # 最小请求间隔（秒）

    @abstractmethod
    async def collect(self, target_date: date, **kwargs) -> RawBatch:
        """取数并归档原始响应。"""

    def archive_path(self, target_date: date) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return (
            Path("data/raw") / self.source / self.dataset
            / target_date.isoformat() / f"{ts}.parquet"
        )

class RawBatch(BaseModel):
    batch_id: int
    source: str
    dataset: str
    target_date: date | None
    raw_path: Path
    row_count: int
    collected_at: datetime
```

**原始归档是硬要求。** 理由：
- 数据源接口会改，归档让你能重放 normalize
- 历史数据经常拉不回来（源站只提供近期数据）
- 排查数据问题时需要看原始值

归档格式统一 Parquet（压缩率高、schema 自描述）。HTML 类内容压缩后存 Parquet 的 binary 列。

### 2.3 重试与限频

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class AkshareCollector(Collector):
    source = "akshare"
    rate_limit = 0.5     # 2 req/s

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    async def _fetch(self, fn, **kwargs):
        async with self._limiter:          # 令牌桶
            return await asyncio.to_thread(fn, **kwargs)
```

限频用 Redis 实现跨进程令牌桶，避免多个任务同时打爆同一数据源。

### 2.4 Normalizer 规范

**代码归一化**是最容易出错的地方。

```python
def normalize_symbol(raw: str, market: str) -> str:
    """统一为 {代码}.{交易所} 格式。

    A 股输入形态繁多：
      '600519' / 'sh600519' / '600519.SH' / 'SH600519' / '600519.XSHG'
    统一输出：'600519.SH'
    """
    if market == "CN":
        digits = re.sub(r"\D", "", raw)
        if len(digits) != 6:
            raise ValueError(f"Invalid CN symbol: {raw}")
        # 交易所判定基于代码段
        if digits.startswith(("60", "68", "90", "51", "58")):
            return f"{digits}.SH"
        if digits.startswith(("00", "30", "20", "15", "16", "18")):
            return f"{digits}.SZ"
        if digits.startswith(("43", "83", "87", "88")):
            return f"{digits}.BJ"
        raise ValueError(f"Unknown exchange for: {raw}")
    ...
```

代码段判定规则需在 P0 核实并写进单元测试，因为新代码段会启用（如科创板 688、北交所 920）。

**单位统一**：

| 数据 | 各源常见单位 | 统一为 |
|---|---|---|
| 成交量 | 股 / 手 / 千股 | 股 |
| 成交额 | 元 / 万元 / 亿元 | 元 |
| 财务金额 | 元 / 万元 | 元 |
| 比率 | 小数 / 百分数 | 小数（0.15 而非 15） |
| 市值 | 元 / 万元 / 亿元 | 元 |

每个 Normalizer 必须在文档字符串里写明源单位和换算，且有单元测试固定住。

## 3. 数据质量校验规则

### 3.1 规则分级

| 级别 | 处理 |
|---|---|
| `FATAL` | 中止整个流程，不写库，告警 |
| `ERROR` | 该批次不写库，标记，告警，其他批次继续 |
| `WARN` | 写库但标记 `quality='suspect'`，记录 |
| `INFO` | 仅记录 |

### 3.2 行情数据校验

| 规则码 | 检查 | 级别 |
|---|---|---|
| `PX_001` | `high >= low`，`high >= open/close`，`low <= open/close` | ERROR |
| `PX_002` | 所有价格 > 0 | ERROR |
| `PX_003` | `volume >= 0`，`amount >= 0` | ERROR |
| `PX_004` | 日涨跌幅在市场限制内（考虑 ST、新股、板块） | WARN |
| `PX_005` | 单日涨跌幅 > 50%（可能是未处理的除权） | ERROR |
| `PX_006` | 交易日历中的开市日必须有数据（除停牌） | ERROR |
| `PX_007` | 停牌日不应有成交量 | WARN |
| `PX_008` | `amount / volume` 应落在 `[low, high]` 区间 | WARN |
| `PX_009` | 双源价格差异 > 0.5% | ERROR |
| `PX_010` | 连续 5 日价格完全相同（疑似数据卡死） | WARN |
| `PX_011` | 股票池覆盖率 < 99% | ERROR |
| `PX_012` | `prev_close` 与前一交易日 `close` 不符且无除权记录 | ERROR |

### 3.3 财务数据校验

| 规则码 | 检查 | 级别 |
|---|---|---|
| `FIN_001` | `total_assets = total_liab + total_equity`（容差 1%） | ERROR |
| `FIN_002` | `announced_at >= period_end`（不能提前公布） | FATAL |
| `FIN_003` | `announced_at` 距 `period_end` < 180 天（超期可疑） | WARN |
| `FIN_004` | `revenue >= 0` | WARN |
| `FIN_005` | 同期不同 revision 的差异 > 20% → 重大重述，标记 | INFO |
| `FIN_006` | `gross_profit = revenue - operating_cost`（容差 1%） | WARN |
| `FIN_007` | 单季数据与累计数据可推导一致 | WARN |
| `FIN_008` | 双源关键科目（营收/净利）差异 > 1% | ERROR |
| `FIN_009` | 同一 `(security, period, type)` 出现重复 revision 号 | FATAL |

### 3.4 PIT 完整性校验（最重要）

| 规则码 | 检查 | 级别 |
|---|---|---|
| `PIT_001` | 任何表不存在 `announced_at` 晚于 `ingested_at` 的记录 | FATAL |
| `PIT_002` | 财务/宏观/因子表不存在 `announced_at IS NULL` | FATAL |
| `PIT_003` | 区间表无重叠区间（同 key 的 `[valid_from, valid_to)` 不交叠） | FATAL |
| `PIT_004` | 区间表无空洞（可选，某些场景允许） | WARN |
| `PIT_005` | `universe_snapshot` 覆盖回测期内每个调仓日 | ERROR |
| `PIT_006` | 退市股票在退市日之后无行情数据 | WARN |
| `PIT_007` | 退市股票在 `security` 表中存在（未被删除） | FATAL |
| `PIT_008` | `document_chunk.visible_at` 非空且不晚于 `ingested_at` | FATAL |
| `PIT_009` | 未来函数哨兵测试通过 | FATAL |

### 3.5 新闻数据校验

| 规则码 | 检查 | 级别 |
|---|---|---|
| `NEWS_001` | `published_at` 不在未来 | ERROR |
| `NEWS_002` | `published_at <= fetched_at` | ERROR |
| `NEWS_003` | 标题非空且长度合理 | WARN |
| `NEWS_004` | 去重率异常（> 80% 重复，疑似源站故障） | WARN |
| `NEWS_005` | 单日新闻数量偏离 30 日均值 3 个标准差 | WARN |
| `NEWS_006` | 抽取的 event 的 `visible_at` 等于源新闻 `published_at` | ERROR |

### 3.6 校验实现

```python
class ValidationRule(BaseModel):
    code: str
    dataset: str
    level: Literal["FATAL", "ERROR", "WARN", "INFO"]
    description: str

class Validator:
    def validate(self, df: pl.DataFrame, dataset: str, ctx: ValidationContext
                 ) -> ValidationReport:
        results = []
        for rule in RULES[dataset]:
            r = rule.check(df, ctx)
            results.append(r)
            self._persist(r)                      # 写 data_quality_check 表
            if r.failed and rule.level == "FATAL":
                raise DataQualityError(rule.code, r.detail)
        return ValidationReport(results=results)
```

所有校验结果落 `data_quality_check` 表，不只是打日志。这样可以查询"过去一个月哪条规则触发最多"。

## 4. 采集调度

### 4.1 A 股每日调度表

| 时间 | 任务 | 依赖 | 失败处理 |
|---|---|---|---|
| 09:00 | 交易日历检查 | — | 非交易日跳过后续 |
| 09:00 | 公告采集（盘前） | — | 重试 |
| 全天 5min | 新闻/快讯增量 | — | 单次失败跳过 |
| 15:15 | 日线行情采集（主源） | 交易日 | 重试 3 次后 FATAL |
| 15:20 | 日线行情采集（备源） | 同上 | 重试 |
| 15:25 | 双源行情校验 | 上两步 | 差异超阈值 FATAL |
| 15:30 | 资金流采集 | — | 重试 |
| 15:30 | 估值数据采集 | — | 重试 |
| 15:40 | 复权因子采集 | — | 重试 |
| 16:00 | 公告采集（盘后） | — | 重试 |
| 16:00 | 财务数据采集（若为财报季） | — | 重试 |
| 16:10 | 数据质量总检 | 全部采集 | FATAL 则中止后续所有 |
| 16:30 | 因子计算 | 质量检查通过 | — |
| 17:00 | Agent 研究流程 | 因子完成 | — |
| 18:00 | 决策与报告 | Agent 完成 | — |
| 22:00 | 概念板块成分同步 | — | 重试 |
| 周末 | 行业分类同步、指数成分同步 | — | — |
| 每月 | 全量数据一致性巡检 | — | — |

### 4.2 盘中监控调度（P2a 新增）

| 频率 | 任务 | 范围 | 失败处理 |
|---|---|---|---|
| 3 分钟 | 实时行情快照 | **仅持仓 + 关注列表** | 单次失败跳过，连续 3 次告警 |
| 5 分钟 | 风控指标计算 | 组合 | 单次失败跳过 |
| 5 分钟 | 公告增量采集 | 全市场（按类型过滤） | 重试 |
| 5 分钟 | 新闻批处理 | 累积后批量 | 单次失败跳过 |
| 09:25 | 持仓时效性检查 | — | — |
| 09:25 | 隔夜公告扫描 | 持仓 | 重试 |

关键约定：

| 约定 | 理由 |
|---|---|
| **只拉持仓 + 关注列表的行情** | 大幅降低数据源压力与处理量。全市场盘中轮询会打爆免费源 |
| 快照数据保留 30 天 | 仅用于触发判断，历史数据用 `price_daily` |
| 非交易时段不轮询行情 | 无意义的请求 |
| 公告盘后仍采集 | 重要公告常在盘后发布 |

盘中数据延迟的现实约束：

| 数据 | 可得性 | 延迟 |
|---|---|---|
| A 股实时行情快照（akshare） | 可得 | 秒到分钟级，**具体需实测** |
| A 股逐笔/盘口 | 免费源有限 | — |
| 交易所公告 | 官网列表页轮询 | 分钟级 |
| 财联社快讯 | 可得 | 分钟级 |

**明确不追求低延迟**：定位是中低频监控，分钟级完全够用。若某信号需秒级响应才有价值，不在本系统能力范围内（见 [00-overview](00-overview.md) 非目标）。

### 4.3 调度实现（P0-P2）

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

sched = AsyncIOScheduler(timezone="Asia/Shanghai")

@sched.scheduled_job("cron", hour=15, minute=15, day_of_week="mon-fri")
async def collect_daily_prices():
    if not await calendar.is_trading_day("CN", date.today()):
        return
    batch = await AkshareCollector().collect(date.today())
    df    = PriceNormalizer().normalize(batch)
    report = Validator().validate(df, "price_daily", ctx)
    if report.has_fatal:
        raise DataQualityError(report)
    await Loader().load(df)
```

### 4.4 回填与重放

历史数据回填是独立流程，要求：

| 要求 | 说明 |
|---|---|
| 断点续传 | 记录已完成的日期区间，中断后可继续 |
| 幂等 | 重复运行不产生重复数据（UPSERT 或 revision） |
| 限速 | 回填不能打爆数据源，加入更严格的限频 |
| 可重放 normalize | 从归档的 raw Parquet 重新 normalize，不重新拉取 |

```bash
# 首次回填（拉取 + 处理）— end 取「今天」所在月末/年，勿写死过期年份
python -m ingest.backfill --dataset price_daily --start 2015-01-01 --end 2026-09-05

# 仅重放 normalize（normalize 逻辑修复后）
python -m ingest.replay --dataset price_daily --start 2015-01-01 --from-archive
```

## 5. 数据源失效应对

akshare 接口失效是**必然会发生**的，需要预案。

### 5.1 失效检测

```python
class InterfaceHealthCheck:
    """每日检查关键接口可用性，早于业务流程发现问题。"""

    CRITICAL_INTERFACES = [
        ("akshare", "stock_zh_a_hist"),
        ("akshare", "stock_zh_a_spot_em"),
        ("tushare", "daily"),
        ("tushare", "income"),
    ]

    async def run(self) -> list[HealthResult]:
        # 用已知的历史日期 + 已知标的做探测
        # 比对返回值与预存的期望值
        ...
```

在每日 09:00 跑，失效立即告警，给出人工修复时间窗口。

### 5.2 降级策略

| 场景 | 降级方案 |
|---|---|
| 主源行情失效 | 切备源，标记 `source` 差异，继续流程 |
| 双源都失效 | 中止流程，不产出决策（宁可无输出，不可用错数据） |
| 财务源失效 | 使用上次可用版本，标记数据陈旧，Agent 报告中注明 |
| 新闻源失效 | 降级为无新闻信号，Fusion 权重重新归一化 |
| 资金流失效 | 相关因子置空，模型使用缺失值处理 |

关键原则：**缺数据时不要用旧数据冒充新数据。** 宁可信号缺失（并如实标记），不可静默用陈旧值。

### 5.3 数据源清单维护

维护 `docs/data-access-log.md`，记录：

```markdown
| 日期 | 接口 | 事件 | 处理 |
|---|---|---|---|
| 2026-xx-xx | akshare.stock_zh_a_hist | 返回列名变更 | 更新 normalizer，回归测试通过 |
| 2026-xx-xx | tushare.income | 积分不足 | 降级用 akshare 财务，标记质量 |
```

这份日志在数据出问题时是最有用的排查线索。

## 6. 成本与配额

| 源 | 成本 | 配额限制 | 监控 |
|---|---|---|---|
| akshare | 免费 | 自我约束 2 req/s | 请求计数 |
| tushare | 积分 | 按等级，需记录当前等级 | 剩余调用次数 |
| baostock | 免费 | 单会话串行 | — |
| 网页抓取 | 免费 | 1 req/2s per site | 请求计数 + 429 监控 |
| Alpaca | 免费档 | 200 req/min（需核实） | — |
| LLM API | 按量 | 配置的日预算 | `agent_run.total_cost_usd` |
| Embedding | 本地，仅算力 | — | — |

每日在报告中输出配额使用情况，避免突然超限。

## 7. 数据源检查清单

P0 验收：

- [ ] 每个关键数据类别有主源 + 备源
- [ ] 所有 Collector 原始响应归档为 Parquet
- [ ] 代码归一化函数覆盖所有已知代码段，有单元测试
- [ ] 单位换算有文档说明 + 单元测试
- [ ] 校验规则表全部实现，结果落库
- [ ] FATAL 级校验失败能中止流程
- [ ] 双源校验对 MVP 股票池全覆盖
- [ ] 交易日历双源一致
- [ ] 接口健康检查每日运行
- [ ] 回填流程幂等且支持断点续传
- [ ] normalize 可从归档重放，无需重新拉取
- [ ] `data-access-log.md` 已建立

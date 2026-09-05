# 17. 知识库设计

本文档回答一个容易走错的问题：**要不要给 Agent 灌输金融知识？**

结论：**不建通用金融知识库，但要沉淀自有判断历史。**

前者是公开的、静态的、LLM 已知的；后者是独有的、随时间增值的、预训练不可能包含的。把精力放在后者。

## 1. 知识注入的四条途径

在讨论"装什么"之前，先明确"怎么装"。同一份知识用不同途径注入，成本差两个数量级。

| 途径 | 机制 | 单次成本 | 适合什么 |
|---|---|---|---|
| **A. Prompt 常驻** | 拼进每次 system prompt | 高（可被前缀缓存部分抵消） | 极少量、每次都要用的口径定义 |
| **B. 代码/配置** | 写成 `config/*.yaml` 或纯函数 | **零** | 确定性规则、阈值、制度参数 |
| **C. 工具按需取** | Agent 调 `get_*()` 拿结构化数据 | 低（只取用到的） | 时变的事实数据 |
| **D. RAG 检索** | 向量检索文档片段 | 中（取决于 top_k 与片段长度） | 长文档、非结构化文本 |

### 1.1 成本量级对比

以一份 5 万字的 A 股制度手册为例（约 7 万 token）：

| 途径 | 每次调用增量 | 每日 40 次调用 | 每月 |
|---|---|---|---|
| A. Prompt 常驻 | ~70k token | — | **远超预算** |
| A. + 前缀缓存 | 缓存命中后大幅降低 | 仍显著 | 仍不划算 |
| D. RAG（top_k=5，每片 500 token） | ~2.5k token | 可接受 | 可接受 |
| B. 配置化（只提取参数） | **0** | **0** | **0** |

具体单价随模型与提供商变化，需在 P2 实测记入 `cost-log.md`。但量级关系不会变：**B 免费，D 便宜，A 昂贵。**

### 1.2 选择判据

按顺序问，第一个"是"就用对应途径：

```
这条知识是确定性规则或数值阈值吗？        → B. 配置化
这条知识是随时间变化的事实数据吗？        → C. 工具
这条知识 LLM 预训练已经可靠掌握吗？      → 不注入
这条知识是本项目独有的长文本吗？          → D. RAG
这条知识每次调用都必须用且极短吗？        → A. Prompt
```

绝大多数"金融知识"卡在第三问就该停下。

## 2. 明确不进知识库的内容

### 2.1 通用金融概念

| 例子 | 为什么不放 |
|---|---|
| PE / PB / ROE / 自由现金流的定义 | 预训练可靠掌握 |
| RSI / MACD / 布林带的计算方式 | 同上，且因子已由 `quant` 层计算 |
| DCF / DDM 估值原理 | 同上 |
| 财务报表三表关系 | 同上 |

花 token 告诉模型它已经知道的事，等于纯浪费。

### 2.2 投资流派与方法论 —— 这一类有害

| 例子 | 为什么有害 |
|---|---|
| 格雷厄姆式安全边际 | 灌进去后 Agent 会在所有股票上找低估理由 |
| 动量/趋势跟踪理论 | 灌进去后 Agent 会到处看趋势 |
| 巴菲特式护城河分析框架 | 同上，制造系统性偏见 |

这不是知识，是**先验信念**。

危害具体在哪：本项目的架构分工是 **量化因子回答"是什么"，Agent 回答"为什么"**（见 [00-overview](00-overview.md)）。把流派塞进 Agent，等于让 Agent 替量化层做本该由数据决定的判断。

举例说明这个失效模式：

```
若知识库含大量价值投资材料
        ↓
StockAgent 分析一支高估值成长股
        ↓
Agent 倾向于给出"估值偏高，谨慎"的结论
        ↓
但这个结论不来自当期数据，来自被灌输的先验
        ↓
Fusion 层以为收到了独立的 Agent 观点
        ↓
实际收到的是"知识库作者的观点"
```

结果是 Agent 观点与量化信号的独立性被破坏，而 Signal Fusion 恰恰假设它们独立（见 [09-portfolio-risk](09-portfolio-risk.md) 2 节的相关性陷阱）。

### 2.3 教科书策略

**能被写进教科书并广泛复述的策略，基本已被套利掉。**

让 Agent 熟读经典的净效果，很可能是让它**更自信地给出无 alpha 的结论**。这直接加剧两个已登记的风险：

- R-06 Agent 事后合理化 —— 有了完整框架，编故事更顺畅
- R-24 误当赚钱工具 —— 输出看起来更专业，更容易被信任

### 2.4 制度规则的全文

A 股制度规则（涨跌停幅度、T+1、ST 规则、新股首日）**必须精确**，而 RAG 检索无法保证精确——可能检索不到、可能检索到过期版本、可能被模型误读。

这类知识走途径 B：

```yaml
# config/markets/cn.yaml —— 唯一权威来源
price_limits:
  main_board:      0.10
  star_market:     0.20      # 科创板
  chinext:         0.20      # 创业板
  bse:             0.30      # 北交所
  st_stocks:       0.05
  new_listing_first_day: null   # ★ 需核实当前规则
settlement: "T+1"
short_selling: false
```

**规则参与计算，不参与推理。** 回测引擎、风控引擎读配置执行，Agent 不需要"知道"涨跌停是 10% ——它只需要看到 `is_limit_up = true` 这个已算好的字段。

### 2.5 被否决方案汇总

| 方案 | 否决理由 |
|---|---|
| 灌入金融教科书 | 预训练已掌握；占用预算换取零增益 |
| 灌入投资大师著作 | 制造系统性偏见，破坏 Agent 与量化信号的独立性 |
| 灌入券商研报方法论 | 同上，且研报本身有立场偏向 |
| 灌入 A 股制度规则全文 | 精确性要求高，RAG 不可靠。应配置化 |
| 灌入历史牛熊案例 | 样本极少（A 股 30 年 ~4 轮），归纳出的"规律"不可靠 |
| 灌入技术分析形态图谱 | 形态识别应由量化层做，且有效性存疑 |
| Fine-tune 一个"懂 A 股"的模型 | 成本高、数据不足、无法验证收益、更新困难 |
| 把 Agent prompt 写成投资框架长文 | 等于 2.2 的变体，成本更高 |

## 3. 应该进知识库的内容

### 3.1 四类真正有价值的知识

| 类型 | 内容 | 来源 | 阶段 |
|---|---|---|---|
| **K1 本项目口径** | 因子定义、评分语义、阈值含义 | 人工维护 | P1（走途径 A） |
| **K2 历史文档** | 年报/半年报、研报、重大公告全文 | 采集 | P2（走途径 D） |
| **K3 自有判断历史** | 过往 thesis、关键假设、是否被证伪、实际收益 | `decision_journal` + `decision_outcome` | **P4**（走途径 D） |
| **K4 沉淀的经验教训** | 归因结论、已知失效模式、触发器质量经验 | P4 归因 + 人工 | P4+ |

**K3 和 K4 才是这套系统真正的知识资产。**

### 3.2 为什么 K3/K4 值得

| 性质 | 通用金融知识 | 自有判断历史 |
|---|---|---|
| 可从预训练获得 | 是 | **否** |
| 竞争对手也有 | 是 | **否** |
| 随时间增值 | 否（静态） | **是（越用越多）** |
| 可验证有效性 | 难 | **可以（对比有无检索的准确率）** |
| 与本项目相关 | 弱 | **强** |

具体场景：

```
StockAgent 分析 600xxx 时应该能检索到：

  [2026-03-15] 看多理由：产能扩张落地，预计毛利率提升 3pct
               关键假设：新产线 2026Q3 投产
               信心度：0.72

  [结果] 20 日超额收益 -8.1%，假设被证伪（产线延期至 2027Q1）

  → 可用的教训：该公司过往产能指引偏乐观，
                管理层执行力指引应打折扣
```

这条信息 LLM 不可能知道，任何通用知识库也不会有。它只能来自自己的记录。

### 3.3 K1 的处理方式（走 Prompt 而非 RAG）

本项目口径必须**每次都用**且**极短**，适合 Prompt 常驻。放在 prompt 最前面以利用前缀缓存（见 [06-agent-design](06-agent-design.md) 4.5 节）。

```
系统口径（固定前缀，可缓存）：
- score 0.5 为中性，> 0.65 为明显看多
- confidence 反映证据充分度，非收益幅度
- momentum_20d 已做行业中性化
- 所有财务数据为 PIT，反映 as_of 时点的已披露值
```

上限 500 token。超过说明设计有问题——口径太复杂 Agent 也记不住。

## 4. K2：历史文档 RAG（P2）

### 4.1 入库范围

| 文档类型 | 优先级 | 切片策略 | 备注 |
|---|---|---|---|
| 年报"管理层讨论与分析" | 高 | 按小节，~800 字 | 信息密度最高的部分 |
| 年报"风险因素" | 高 | 按条目 | red flag 识别的直接依据 |
| 重大公告全文 | 高 | 整篇或按段 | 与 `event` 表关联 |
| 半年报/季报 | 中 | 同年报 | |
| 研报 | 低 | 按小节 | 有立场偏向，仅作参考 |
| 财务报表数字 | **不入** | — | 已结构化在 `financial_report` 表 |

原则：**能结构化的不进 RAG。** 财务数字走 `financial_report` 表 + 工具，比向量检索准确得多。RAG 只处理"无法结构化的文本"。

### 4.2 PIT 约束 —— 容易被忽略的未来函数

`document_chunk.visible_at` 已在 [03-data-model](03-data-model.md) 定义，但各文档类型的 `visible_at` 语义需明确：

| doc_type | `visible_at` 取值 | 陷阱 |
|---|---|---|
| `announcement` | 公告披露时间 | 注意盘后披露的归属日 |
| `report`（年报） | 年报披露日，**非报告期末** | 2025 年报在 2026-04 才可见 |
| `news` | 新闻发布时间 | 转载稿要用原发时间 |
| `research` | 研报发布日 | |
| `knowledge`（K3/K4） | **判断写下的时间** | 见 4.3 |

回测中检索必须过滤：

```sql
SELECT chunk_id, content, doc_type,
       1 - (embedding <=> :query_vec) AS similarity
FROM document_chunk
WHERE visible_at <= :as_of              -- ★ 强制
  AND (security_id = :sid OR security_id IS NULL)
ORDER BY embedding <=> :query_vec
LIMIT :top_k;
```

已有防护：`PIT_008` 校验规则、`search_chunks_as_of` 唯一入口、未来函数哨兵测试（向未来注入荒谬文档，历史回测结果不应变）。

### 4.3 知识文档自身的时效性

这一点比新闻的 PIT 更隐蔽：**知识本身会过期。**

```
2020 年注册制规则 ≠ 2018 年适用规则
        ↓
若回测 2018 年时检索到 2024 年的监管规则文档
        ↓
Agent 用未来规则分析历史事件
        ↓
一种很难发现的未来函数
```

处理方式：

| 情况 | 处理 |
|---|---|
| 有明确生效日的规则文档 | `visible_at` = 生效日；配 `expires_at` 列 |
| 无时效的通用文本 | 按 2.1 不该入库 |
| K3 历史 thesis | `visible_at` = thesis 写下的时间 |
| K4 归因结论 | `visible_at` = 归因分析完成时间 |

K4 的 PIT 尤其严格：2026 年做的归因结论，不能被 2025 年的回测检索到。否则等于"用后来总结的规律去回测过去"——这是最常见的过拟合伪装形式。

## 5. K3：自有判断历史（P4）

### 5.1 为什么要等到 P4

三个前置条件：

| 条件 | 为什么必须 | 何时满足 |
|---|---|---|
| 有足够的历史 thesis | 少于 100 条时检索几乎必然无命中 | P2 起累积，P4 达量 |
| 有结果回填 | 只有 thesis 没有结果 = 只知道说过什么，不知道对不对 | `decision_outcome` P4 |
| 有归因分析 | 才能判断"哪类判断准" | P4 |

**在 P2 就做历史检索是浪费**：库里只有几十条无结果的 thesis，检索出来的东西没有信息量，还要为 embedding 和检索付费。

### 5.2 转化设计

`decision_journal` 现在是审计记录（append-only、不可改）。要变成可检索资产，需要一个转化步骤：

```sql
-- ─────────────────────────────────────────────
-- 历史判断的可检索视图（P4）
-- ─────────────────────────────────────────────
CREATE VIEW v_thesis_with_outcome AS
SELECT
    j.decision_id,
    j.as_of_date,
    j.security_id,
    j.action,
    j.thesis,
    j.confidence,
    j.expected_ret_20d,
    o.ret_20d           AS actual_ret_20d,
    o.excess_ret_20d,
    o.hit_20d,
    -- 判断质量标签
    CASE
        WHEN o.hit_20d IS NULL              THEN 'pending'
        WHEN o.hit_20d AND j.confidence>0.7 THEN 'confident_correct'
        WHEN o.hit_20d                       THEN 'correct'
        WHEN NOT o.hit_20d AND j.confidence>0.7 THEN 'confident_wrong'   -- ★ 最有价值
        ELSE 'wrong'
    END AS quality_label
FROM decision_journal j
LEFT JOIN decision_outcome o USING (decision_id)
WHERE j.thesis IS NOT NULL;

COMMENT ON VIEW v_thesis_with_outcome IS
  'confident_wrong 是最有学习价值的样本：高信心但判断错误，'
  '说明当时的推理链有系统性缺陷。';
```

入库为可检索片段：

```sql
-- ─────────────────────────────────────────────
-- 历史 thesis 的 chunk 化（P4，每月批量）
-- ─────────────────────────────────────────────
INSERT INTO document_chunk
    (doc_type, doc_ref, security_id, chunk_index, content, visible_at,
     embedding, embed_model)
SELECT
    'thesis',
    'decision:' || decision_id,
    security_id,
    0,
    format(
      '[%s] %s 判断: %s (信心 %.2f)。论点: %s。结果: %s%s',
      as_of_date, action, action, confidence, thesis,
      quality_label,
      CASE WHEN actual_ret_20d IS NOT NULL
           THEN format('，20日超额 %.1f%%', excess_ret_20d * 100)
           ELSE '' END
    ),
    -- ★ visible_at 用结果确认时间，不是 thesis 写下时间
    -- 因为片段内容包含了结果，结果在当时不可知
    as_of_date + interval '20 trading days',
    embed(...),
    :model
FROM v_thesis_with_outcome
WHERE quality_label != 'pending';
```

**关键细节**：这个片段的 `visible_at` 不是 `as_of_date`，而是结果确认之后。因为片段内容含"结果"信息，在写下 thesis 的当时是不可知的。搞错这一点就直接造出未来函数。

### 5.3 检索工具

```python
def search_own_history(
    security_id: int | None,
    query: str,
    as_of: datetime,                      # ★ 必填，无默认值
    top_k: int = 3,                       # ★ 默认小
    only_wrong: bool = False,             # 只看错误案例
) -> list[HistoricalThesis]:
    """检索自己过往对该标的的判断与结果。

    默认 top_k=3：历史判断不是越多越好。3 条相关的比 10 条泛泛的有用，
    且直接决定这次调用的 token 消耗。
    """
```

工具返回值必须截断（`max_chars`，见 [06-agent-design](06-agent-design.md)）。历史 thesis 可能很长，全量返回会吃掉预算。

### 5.4 用途与边界

| 可以用来 | 不可以用来 |
|---|---|
| 提示"上次的关键假设是否仍成立" | 直接沿用上次结论（会产生锚定） |
| 提示"该公司的指引历史偏乐观" | 替代当期数据分析 |
| 避免重复犯同类错误 | 作为看多/看空的理由 |

**风险：锚定效应。** 如果 Agent 看到"三个月前我看多"，可能倾向于维持看多以保持一致。这是人的偏误，LLM 同样有。

缓解措施：

```
Prompt 约束（P4 加入）：
历史判断仅供参考。你的结论必须基于当期数据独立得出。
若当期数据与历史判断冲突，以当期数据为准，并明确指出冲突。
```

需在 P4 做 A/B 测试验证：有历史检索 vs 无历史检索，看**准确率**是否提升、**结论多样性**是否下降。如果只是让 Agent 更一致但没更准，说明是锚定而非学习，应关闭。

## 6. K4：经验教训沉淀（P4+）

### 6.1 内容来源

| 来源 | 沉淀什么 | 谁写 |
|---|---|---|
| P4 归因分析 | "赚的钱来自哪个维度""哪类判断准" | 自动生成 + 人工确认 |
| `v_trigger_quality` | "哪类告警事后有用" | 自动 |
| 失效模式记录 | "该行业业绩预告与实际偏差大" | **人工** |
| 数据陷阱记录 | "该数据源的某字段在某段时间不可靠" | 人工 |

### 6.2 准入标准

K4 是人工维护的，容易膨胀成一堆无用的"感想"。设三条硬标准：

| 标准 | 说明 |
|---|---|
| **可验证** | 能指向具体的历史案例或统计结果 |
| **可操作** | 影响某个具体判断，而非泛泛而谈 |
| **有时效** | 标注生效日期，过期条目定期清理 |

```yaml
# knowledge/lessons/L-0001.yaml
id: L-0001
created_at: 2026-11-15
visible_from: 2026-11-15        # ★ PIT
category: "data_reliability"
scope: { industry: "半导体" }
lesson: "该行业业绩预告与实际财报偏差中位数 18%，高于全市场 7%。"
evidence:
  - "统计 2020-2026 共 142 个样本"
  - "backtest_run: 3312"
actionable: "涉及该行业业绩预告时，confidence 上限 0.6"
expires_at: 2027-11-15          # 需重新验证
```

反例（不该进 K4）：

```
❌ "要注意宏观环境的影响"           —— 不可操作
❌ "这只股票我感觉不太好"           —— 不可验证
❌ "牛市要满仓，熊市要空仓"         —— 不可操作，且是废话
```

### 6.3 数量上限

**K4 条目上限 50 条。** 超过时必须删掉旧的。

理由：人工维护的知识超过 50 条就不可能保持质量。且检索命中率会下降——太多条目意味着大部分不相关。

## 7. 存储与实现

### 7.1 复用现有表

不新建表，复用 `document_chunk`，扩展 `doc_type`：

```sql
-- doc_type 取值扩展
-- 已有: 'news' | 'announcement' | 'report' | 'knowledge'
-- 新增: 'thesis'  (K3, P4)
--       'lesson'  (K4, P4+)

ALTER TABLE document_chunk ADD CONSTRAINT chk_doc_type CHECK (
    doc_type IN ('news','announcement','report','research',
                 'knowledge','thesis','lesson')
);

-- 知识类文档的时效性
ALTER TABLE document_chunk ADD COLUMN expires_at TIMESTAMPTZ;

COMMENT ON COLUMN document_chunk.expires_at IS
  '知识类文档的失效时间（如已废止的监管规则）。'
  '检索需加 (expires_at IS NULL OR expires_at > :as_of)。';
```

完整的检索约束：

```sql
WHERE visible_at <= :as_of
  AND (expires_at IS NULL OR expires_at > :as_of)   -- ★ 双向时效
```

### 7.2 目录结构

```
src/quantagent/knowledge/
├── ingestion/
│   ├── documents.py         # K2: 年报/研报/公告切片
│   ├── thesis.py            # K3: decision_journal → chunk
│   └── lessons.py           # K4: YAML → chunk
├── embedding/
│   ├── local.py             # bge-m3 本地推理（零 API 成本）
│   └── cache.py
├── retrieval/
│   ├── search.py            # search_chunks_as_of（唯一入口）
│   ├── history.py           # search_own_history
│   └── rerank.py            # 可选，P4+
└── curation/
    ├── validate.py          # K4 准入标准校验
    └── expire.py            # 过期条目清理

knowledge/                   # 仓库根，人工维护的内容
├── glossary.md              # K1: 本项目口径（≤500 token）
└── lessons/
    ├── L-0001.yaml
    └── ...
```

### 7.3 Embedding 用本地模型

| 项 | 选择 | 理由 |
|---|---|---|
| 模型 | `bge-m3`（中文效果好） | 本地推理，**零 API 成本** |
| 维度 | 1024 | 已在 `document_chunk.embedding` 定义 |
| 设备 | CPU 够用 | 增量入库量小（每日几百片段） |

Embedding 是少数可以完全本地化的环节，没有理由付费。首次全量入库耗时较长（几小时），但只做一次。

### 7.4 成本

| 项 | 成本 |
|---|---|
| Embedding（本地） | **0** |
| 向量存储（pgvector） | 磁盘，可忽略 |
| 检索（SQL） | **0** |
| **检索结果进 prompt** | ★ 唯一成本 |

所以成本控制的着力点是 `top_k` 和片段长度，不是入库量。入库多少都不花钱，取出来多少才花钱。

| 参数 | 默认 | 说明 |
|---|---|---|
| `top_k` | 3-5 | 超过 5 通常是噪声 |
| 片段长度 | ≤800 字 | 切片时控制 |
| 工具返回截断 | 2000 字符 | `Tool.max_chars` |

单次检索约 2-3k token 输入，属可接受范围。计入 `daily_research` 分项。

## 8. 阶段安排

| 阶段 | 做什么 | 不做什么 |
|---|---|---|
| P1 | K1 口径写入 prompt 固定前缀 | 无任何 RAG |
| P2 | K2 文档 RAG（年报 MD&A + 风险因素 + 公告） | K3/K4 |
| P2 | `search_chunks_as_of` + PIT 哨兵测试 | |
| P4 | K3 历史 thesis 检索 + A/B 验证 | |
| P4+ | K4 经验沉淀（上限 50 条） | |

### 8.1 P2 验收

- [ ] `document_chunk` 有年报 MD&A 与风险因素切片
- [ ] `search_chunks_as_of` 是唯一检索入口（有测试）
- [ ] 检索强制 `visible_at <= as_of`（有测试）
- [ ] 未来函数哨兵：注入未来文档，历史回测结果不变
- [ ] `top_k` 默认 ≤ 5，工具返回值有截断
- [ ] Embedding 本地跑通，API 成本为 0
- [ ] 财务数字**不在** RAG 里（走结构化表）

### 8.2 P4 验收

- [ ] `v_thesis_with_outcome` 视图可查
- [ ] thesis chunk 的 `visible_at` = 结果确认时间（有测试）
- [ ] `search_own_history` 的 `as_of` 参数无默认值
- [ ] A/B 测试：有无历史检索的准确率对比
- [ ] 锚定效应检查：结论多样性未显著下降
- [ ] 若只提升一致性未提升准确率，关闭该功能

## 9. 检查清单

判断某条"知识"该不该进库，按顺序问：

```
1. LLM 预训练已可靠掌握？                → 不放
2. 是投资流派或方法论？                  → 不放（有害）
3. 是确定性规则或阈值？                  → 配置化（途径 B）
4. 能结构化成表？                        → 工具（途径 C）
5. 是本项目独有的长文本？                → RAG（途径 D）
6. 每次都要用且 ≤500 token？             → Prompt（途径 A）
7. 有明确的 visible_at？                 → 无则不放
8. 可验证、可操作、有时效？（限 K4）      → 三者缺一不放
```

## 10. 与其他文档的关系

| 文档 | 关联 |
|---|---|
| [03-data-model](03-data-model.md) | `document_chunk` 表定义、`expires_at` 列 |
| [06-agent-design](06-agent-design.md) | `search_knowledge` / `search_own_history` 工具契约 |
| [08-backtest-eval](08-backtest-eval.md) | RAG PIT 防偏差检查项 |
| [16-token-economics](16-token-economics.md) | 检索结果进 prompt 的成本控制 |
| [ADR-0011](adr/0011-no-general-finance-kb.md) | 不建通用金融知识库的决策 |

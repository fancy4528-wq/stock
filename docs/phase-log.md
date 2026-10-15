# Phase log

各阶段实际关门记录。模板见 [12-roadmap](12-roadmap.md) 5.1。

## P3 (2026-10-11 ~ )

**Gate 3 状态**: 进行中（CSI300 5y 准入 **7/33**；**L2 等权/IC 加权基线已记录**）

**已完成**:
- 因子库扩至 33（OHLCV + 简单估值）；L1 流水线与 synthetic 报告
- 真实数据 L1：`make evaluate-real` / `evaluate --from-db`（`mvp_cn_50`，2015-01-01→2026-09-30，135k 行）
- 回填 `adjust_factor`（717 行）+ `valuation_daily`（~135k 行，baostock pe/pb/ps）
- 修复 `get_prices_as_of`：稀疏复权因子改为 as-of（`trade_date <=`）LATERAL join（migration `0008`）
- 截面变换管线 `features/transform.py`：MAD 去极值 → 行业/市值中性化 → `rank_pct`；`evaluate --transform/--no-transform`（默认开）
- L1 加载申万一级行业（`get_industry` @ as_of）；`log_mktcap` 在 `market_cap` 为空时用 `ln(close*volume/turnover)` 代理
- 标签可交易性：`attach_forward_returns` 默认在 **T+1 涨停/停牌** 时将 `fwd_ret_*` 置 NaN（§4.3；单测 `test_labels.py`）

**真实 L1（复权+估值后，2026-10-11）**:
- 评估 **33/33** 因子（含 `ep_ttm`/`bp`/`sp_ttm`）；L1 admission **PASS 0/33**
- 较接近：`dist_from_high_252d` IC=+0.025 t=+4.5 但 ICIR=0.09≪0.3；`skew_60d` |IC|=0.020 同样卡在 ICIR/方向比

**真实 L1 + 截面变换（2026-10-11）**:
- transform 生效：`industry=True mktcap=True rank=True`；admission 仍 **PASS 0/33**
- 较接近：`ep_ttm` IC=+0.016 ICIR=+0.116 t=+6.2；`rev_5d` IC=+0.015 ICIR=+0.103 t=+5.5

**真实 L1 + 变换 + 标签 mask（2026-10-11）**:
- 排除 T+1 涨停/停牌：**2468/135107（1.83%）** 行标签置空；admission 仍 **PASS 0/33**
- 较接近：`rev_5d` IC=+0.016 ICIR=+0.107；`ep_ttm` IC=+0.015 ICIR=+0.114（仍远低于 `|ICIR|≥0.3`）
- 结论：Gate 3 标签硬条件已满足；50 池噪声仍是准入主瓶颈
- 报告见 [factor-reports](factor-reports/README.md)

**CSI300 扩池（2026-10-11 ~ 2026-10-14）**:
- 先上 CSI300（CSI800 = HS300∪ZZ500，后续）
- `BaostockIndexConstituentCollector` + `make build-csi300`：当前成分 300 → `config/universe/csi300.yaml`；月度并集 **653** → `data/universes/csi300_hist_union.txt`
- Makefile 支持 `UNIVERSE=` / `SYMBOLS_FILE=` / `FROM_INDEX=hs300`
- 数据回填完成：行情（653）+ adjust（4 只 baostock 空因子）+ valuation（超时 8 只已重试补齐）+ 申万行业（当前成分）+ 月度 snapshot **141/141**（`--from-index hs300`）
- `PX_005`：有成交量的日涨跌 >50% 改为 WARN（放行 IPO/复牌），零成交仍 ERROR；`PriceNormalizer` 显式 schema 修 Polars 长历史类型推断

**真实 L1 CSI300（变换 + 标签 mask，2026-10-14；初跑作废）**:
- 初跑全员负 IC、因子两两 corr≈0.85–1.0：根因是 `neutralize` 对缺行业行写 **NaN**（Polars 不计入 null），`rank_pct` 把所有 NaN 打成同一百分位 → 截面因子塌缩。已修为 null + `fill_nan(None)`（单测覆盖）
- 附带：历史并集行业覆盖约半（当前成分入库）；缺行业行在中性化后正确置空，不再污染秩

**真实 L1 CSI300 修复后 10y（2015→2026-10，2026-10-14）**:
- 面板 **1.68M** 行；admission 仍 **PASS 0/33**；符号恢复正常（反转/估值为正，动量/换手为负）
- 较接近：`turnover_20d` ICIR=-0.252；`rev_5d`/+`mom_5d` |ICIR|=0.248；`ep_ttm` ICIR=+0.196
- 报告 [factor-reports-csi300](factor-reports-csi300/README.md)

**真实 L1 CSI300 5y 窗（2021-10-14→2026-10-13；行业补全 + 贪心准入）**:
- 全市场申万 L1 入库后 hist-union 覆盖 **631/653（96.6%）**（余 22 多为退市/已出指数，akshare 当前成分无）
- 相关门槛按文档改为「只对**已准入**因子」：按 `|ICIR|` 降序贪心录取（`apply_greedy_admission`）
- **PASS 7/33**：`max_ret_20d`(-0.511)、`skew_60d`(-0.462)、`turnover_20d`(-0.425)、`vol_60d`(-0.382)、`ep_ttm`(+0.348)、`vol_price_corr_20d`(-0.333)、`bp`(+0.327)
- 报告 [factor-reports-csi300-5y](factor-reports-csi300-5y/README.md)
- Gate 3「≥5 个达标因子」已满足；5y 为主评估窗，10y 作稳健性对照

**真实 L2 CSI300 5y（2026-10-14）**:
- 7 个准入因子：符号对齐（负 IC 则 `1-rank`）后等权 / `|IC|` 加权
- **`l2_equal`**: IC=+0.0606 ICIR=+0.514 t=+17.9 LS=+0.33%/期
- **`l2_ic`**: IC=+0.0610 ICIR=+0.493 t=+17.1 LS=+0.32%/期（略逊于等权 ICIR）
- 报告 [factor-reports-csi300-5y-l2](factor-reports-csi300-5y-l2/README.md)；CLI `evaluate-l2` / `make evaluate-l2`
- Gate 3「L2 等权基线结果已记录」已满足

**下一步（Gate 3）**:
- 进入 L3（Logistic / Ridge）；L4 须样本外显著优于 L2；可选 CSI800 / 补退市股历史行业

## P2 (约 2026-09-13 ~ 2026-10-11)

**Gate 2 状态**: 工程验收通过（2026-10-11 盘点）

**实际耗时**: 约 4 周日历（与 P1 观察窗及 P2a/P2b 基建重叠），估算 4–6 周内。

**偏差原因**:
- live LLM 验收被 `per_call_max_tokens_out=4000` vs `large.max_tokens_out=4096` 卡住，Chief 预调用 `budget_skip`；对齐到 4096 后恢复
- Chief 曾整份重吐 `MarketBrief` / 使用 `deepseek-reasoner` 烧完 completion，顶满上限致 `schema_fail`；改为 `ChiefRefinePatch` + `deepseek-chat` + `max_tokens_out=1024`

**关键决策**:
- Gate 2 只验工程质量（schema / evidence / PIT / 可追溯 / 预算），不把 Agent IC 当作关门条件（留给 Gate 4）
- Research live 路径以 `make research-live-accept` + `docs/research-validation-log.md` / `docs/cost-log.md` 为准
- 新闻数字提取以 `rule_v1` + `figures_gold` ≥100 回归基线关门；LLM extractor 对照不阻塞 P3
- P2a/P2b 观测（推送有用率、live L2）与 P3 并行，不阻塞 Quant 开工

**遗留问题**:
- Gate 2a：连续 20 交易日无漏报 + 推送有用率 >40% 仍在观测
- Gate 2b：live LLM L2 准确率 / 有用率对比、缓存命中率未收齐；heuristic funnel replay 已记入 `cost-log`
- Token 经济学清单中批处理最优批大小、结果缓存命中率等 P2b 项未全部勾完
- （已复核）`make research-live-accept` 应见 `schema_fails=0`；若偶发 JSON 损坏仍回退启发式且 overall 过线

**基线结果**:
- Live research（as_of=2026-09-30，`require-llm`）：schema_pass ≥95.5%、evidence 100%、PIT 0、untraceable 0、daily_research ≈ $0.012–$0.022 ≪ $0.80；见 `docs/research-validation-log.md`
- Extraction：`docs/extraction-eval.md` — n=100，soft match 100%（db 68 + synthetic 32）
- RAG PIT：`search_chunks_as_of` + 单测；K2 report_pack 可 `make ingest-reports`
- `shadow_agent` 已启动（信号=`MarketBrief.stock_ranking`）

## P0 + P1 (约 2026-09-02 ~ 2026-09-30)

**Gate 1 状态**: 通过（2026-10-03 盘点）

**实际耗时**: 约 4 周日历（含中秋休市），与估算 3–4 周相当。

**偏差原因**:
- 09-12 二次盘点时其余 46 项已齐，卡在「连续 20 交易日无中断」；后台继续跑至 09-30 收齐
- 09-02～11 日报曾于 09-13 为接入「重要事件」节重写（内容升级，非管道崩掉后补跑）
- 少数调度落点晚于设计的 18:00（北京时间）：09-14、09-22、09-29 的 `cost-log` UTC 对应晚间

**关键决策**:
- MVP Reporter 保持 deterministic / NullLLM，成本记 `$0`（`docs/cost-log.md`）
- Shadow 三组合在 Gate 1 窗口内已启动，不把 Shadow 成绩当作 Gate 1 条件
- P2 基建与盘中监控与 20 日观察并行，不阻塞日报管道

**遗留问题**:
- H1–H3（源超时、重复触发、数据未就绪）与 D3（半日市/调休开市）在窗口内未自然撞上，仍靠既有单测 + 后续运行观察
- 09-28/29/30 日报文件当时可能尚未入库 git，以仓库工作区 `docs/daily-reports/` 为准

**基线结果**:
- 见 `docs/baseline-results.md` 与 `docs/factor-reports/`
- 窗口内 20 份日报路径：`docs/daily-reports/2026-09-{02,03,04,07,08,09,10,11,14,15,16,17,18,21,22,23,24,28,29,30}.md`
- Reporter schema：`docs/reporter-validation-log.md` 窗口内记录全部 `ok=true`

# 新闻数字提取抽检基线

> 自动生成于 2026-09-13 05:14 UTC。金标：`tests/fixtures/extraction/figures_gold.jsonl`。
> Gate 2 目标：人工抽检 **≥100** 条，准确率 > 90%。当前为 **rule_v1** 可回归基线
> （含入库新闻摘录 + 合成模板）。

## 当前结果（rule_v1 / figures）

| 指标 | 值 |
|---|---|
| 样本数 n | 100 |
| 其中入库新闻 (origin=db) | 68 |
| 其中合成模板 (origin=synthetic) | 32 |
| 精确匹配（label+value+unit） | 100 (100.0%) |
| 软匹配（label+unit + value±1%） | 100 (100.0%) |
| label+unit 命中 | 100 |

## 用法

```bash
make extraction-eval
# 刷新金标（读 news 表）再评分：
uv run python scripts/build_figures_gold.py --target 100
uv run python scripts/extraction_eval.py \
  --gold tests/fixtures/extraction/figures_gold.jsonl --min-n 100
```

## 后续

1. 持续用入库正文扩库；`origin=db` 占比应逐步提高。
2. 接 LLM extractor 后与 rule_v1 对照，写入同表对比行。
3. Gate 2 以人工抽检准确率为准；本脚本保证回归不回退。

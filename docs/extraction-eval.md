# 新闻数字提取抽检基线

> 自动生成于 2026-09-13 05:01 UTC。金标：`tests/fixtures/extraction/figures_gold.jsonl`。
> Gate 2 目标：人工抽检 100 条准确率 > 90%。本文件先建立 **规则抽取** 可回归基线。

## 当前结果（rule_v1 / figures）

| 指标 | 值 |
|---|---|
| 样本数 n | 30 |
| 精确匹配（label+value+unit） | 30 (100.0%) |
| 软匹配（label+unit + value±1%） | 30 (100.0%) |
| label+unit 命中 | 30 |

## 用法

```bash
make extraction-eval
# 或
uv run python scripts/extraction_eval.py --gold tests/fixtures/extraction/figures_gold.jsonl
```

## 后续

1. 用真实入库新闻扩到 100 条人工标注（保留本 JSONL 格式）。
2. 接 LLM extractor 后与 rule_v1 对照，写入同表对比行。
3. Gate 2 以人工抽检准确率为准；本脚本保证回归不回退。

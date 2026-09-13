#!/usr/bin/env python3
"""Score rule_v1 figure extraction against gold set; write docs/extraction-eval.md."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from quantagent.agents.news_extractor.eval import score_figures_gold

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = ROOT / "tests" / "fixtures" / "extraction" / "figures_gold.jsonl"
DEFAULT_OUT = ROOT / "docs" / "extraction-eval.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--min-soft-rate", type=float, default=0.8)
    parser.add_argument("--min-n", type=int, default=100)
    parser.add_argument("--write-doc", action="store_true", default=True)
    parser.add_argument("--no-write-doc", action="store_false", dest="write_doc")
    args = parser.parse_args()

    score = score_figures_gold(args.gold)
    print(
        f"figure-eval n={score.n} exact={score.exact} ({score.exact_rate:.1%}) "
        f"soft={score.value_tol} ({score.soft_rate:.1%}) "
        f"label_unit={score.label_unit}"
    )

    if args.write_doc:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        gold_path = Path(args.gold).resolve()
        try:
            gold_rel = gold_path.relative_to(ROOT).as_posix()
        except ValueError:
            gold_rel = gold_path.as_posix()
        n_db = 0
        n_syn = 0
        for line in Path(args.gold).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            if '"origin": "db"' in line or '"origin":"db"' in line:
                n_db += 1
            elif '"origin": "synthetic"' in line or '"origin":"synthetic"' in line:
                n_syn += 1
        args.out.write_text(
            f"""# 新闻数字提取抽检基线

> 自动生成于 {now}。金标：`{gold_rel}`。
> Gate 2 目标：人工抽检 **≥100** 条，准确率 > 90%。当前为 **rule_v1** 可回归基线
> （含入库新闻摘录 + 合成模板）。

## 当前结果（rule_v1 / figures）

| 指标 | 值 |
|---|---|
| 样本数 n | {score.n} |
| 其中入库新闻 (origin=db) | {n_db} |
| 其中合成模板 (origin=synthetic) | {n_syn} |
| 精确匹配（label+value+unit） | {score.exact} ({score.exact_rate:.1%}) |
| 软匹配（label+unit + value±1%） | {score.value_tol} ({score.soft_rate:.1%}) |
| label+unit 命中 | {score.label_unit} |

## 用法

```bash
make extraction-eval
# 刷新金标（读 news 表）再评分：
uv run python scripts/build_figures_gold.py --target 100
uv run python scripts/extraction_eval.py \\
  --gold tests/fixtures/extraction/figures_gold.jsonl --min-n 100
```

## 后续

1. 持续用入库正文扩库；`origin=db` 占比应逐步提高。
2. 接 LLM extractor 后与 rule_v1 对照，写入同表对比行。
3. Gate 2 以人工抽检准确率为准；本脚本保证回归不回退。
""",
            encoding="utf-8",
        )
        print(f"wrote {args.out}")

    failed = False
    if score.n < args.min_n:
        print(f"FAIL: n={score.n} < min_n={args.min_n}", file=sys.stderr)
        failed = True
    if score.soft_rate < args.min_soft_rate:
        print(
            f"FAIL: soft_rate={score.soft_rate:.1%} < min={args.min_soft_rate:.1%}",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

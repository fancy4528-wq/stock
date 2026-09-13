"""Build / refresh figures_gold.jsonl from ingested news (+ seed templates)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import create_engine, text

from quantagent.agents.news_extractor.figures import extract_figures
from quantagent.shared.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "extraction" / "figures_gold.jsonl"

# Hand-verified seed templates (kept for regression).
SEED: list[dict[str, object]] = [
    {
        "id": "s001",
        "origin": "synthetic",
        "text": "公司实现营收12.3亿元，同比增长15%",
        "figure": {"label": "营收", "value": 12.3, "unit": "亿元"},
    },
    {
        "id": "s002",
        "origin": "synthetic",
        "text": "净利润3.5亿元，同比下降8.2%",
        "figure": {"label": "净利润", "value": 3.5, "unit": "亿元"},
    },
    {
        "id": "s003",
        "origin": "synthetic",
        "text": "归母净利润同比增长25.6%",
        "figure": {"label": "同比", "value": 25.6, "unit": "%"},
    },
    {
        "id": "s004",
        "origin": "synthetic",
        "text": "中标金额1.2亿元的重大合同",
        "figure": {"label": "中标金额", "value": 1.2, "unit": "亿元"},
    },
    {
        "id": "s005",
        "origin": "synthetic",
        "text": "合同金额8500万元已确认",
        "figure": {"label": "合同金额", "value": 8500.0, "unit": "万元"},
    },
    {
        "id": "s006",
        "origin": "synthetic",
        "text": "营业收入同比增12%",
        "figure": {"label": "同比", "value": 12.0, "unit": "%"},
    },
    {
        "id": "s007",
        "origin": "synthetic",
        "text": "环比下降3.5%",
        "figure": {"label": "环比", "value": -3.5, "unit": "%"},
    },
    {
        "id": "s008",
        "origin": "synthetic",
        "text": "产能提升至50万吨",
        "figure": {"label": "产能", "value": 50.0, "unit": "万吨"},
    },
    {
        "id": "s009",
        "origin": "synthetic",
        "text": "投资额约28亿元建设新产线",
        "figure": {"label": "投资额", "value": 28.0, "unit": "亿元"},
    },
    {
        "id": "s010",
        "origin": "synthetic",
        "text": "募资总额15.8亿元用于扩产",
        "figure": {"label": "募资", "value": 15.8, "unit": "亿元"},
    },
    {
        "id": "s011",
        "origin": "synthetic",
        "text": "净利-1.2亿元，同比转亏",
        "figure": {"label": "净利润", "value": -1.2, "unit": "亿元"},
    },
    {
        "id": "s012",
        "origin": "synthetic",
        "text": "订单金额2.05亿元",
        "figure": {"label": "订单金额", "value": 2.05, "unit": "亿元"},
    },
    {
        "id": "s013",
        "origin": "synthetic",
        "text": "收入增长18.5%",
        "figure": {"label": "营收", "value": 18.5, "unit": "%"},
    },
    {
        "id": "s014",
        "origin": "synthetic",
        "text": "净利润同比上升9%",
        "figure": {"label": "同比", "value": 9.0, "unit": "%"},
    },
    {
        "id": "s015",
        "origin": "synthetic",
        "text": "营收达100亿元关口",
        "figure": {"label": "营收", "value": 100.0, "unit": "亿元"},
    },
    {
        "id": "s016",
        "origin": "synthetic",
        "text": "同比增长-5.1%",
        "figure": {"label": "同比", "value": -5.1, "unit": "%"},
    },
    {
        "id": "s017",
        "origin": "synthetic",
        "text": "中标金额3亿元，刷新纪录",
        "figure": {"label": "中标金额", "value": 3.0, "unit": "亿元"},
    },
    {
        "id": "s018",
        "origin": "synthetic",
        "text": "合同金额1200万元",
        "figure": {"label": "合同金额", "value": 1200.0, "unit": "万元"},
    },
    {
        "id": "s019",
        "origin": "synthetic",
        "text": "归母净利润0.88亿元",
        "figure": {"label": "归母净利润", "value": 0.88, "unit": "亿元"},
    },
    {
        "id": "s020",
        "origin": "synthetic",
        "text": "环比增长2.3个百分点",
        "figure": {"label": "环比", "value": 2.3, "unit": "个百分点"},
    },
    {
        "id": "s021",
        "origin": "synthetic",
        "text": "营收45678元（单店测算）",
        "figure": {"label": "营收", "value": 45678.0, "unit": "元"},
    },
    {
        "id": "s022",
        "origin": "synthetic",
        "text": "净利润同比增长32%",
        "figure": {"label": "同比", "value": 32.0, "unit": "%"},
    },
    {
        "id": "s023",
        "origin": "synthetic",
        "text": "同比下降12%",
        "figure": {"label": "同比", "value": -12.0, "unit": "%"},
    },
    {
        "id": "s024",
        "origin": "synthetic",
        "text": "投资额6.5亿元",
        "figure": {"label": "投资额", "value": 6.5, "unit": "亿元"},
    },
    {
        "id": "s025",
        "origin": "synthetic",
        "text": "订单金额同比增长40%",
        "figure": {"label": "同比", "value": 40.0, "unit": "%"},
    },
    {
        "id": "s026",
        "origin": "synthetic",
        "text": "中标金额0.5亿元",
        "figure": {"label": "中标金额", "value": 0.5, "unit": "亿元"},
    },
    {
        "id": "s027",
        "origin": "synthetic",
        "text": "营收8亿元，净利1亿元",
        "figure": {"label": "营收", "value": 8.0, "unit": "亿元"},
    },
    {
        "id": "s028",
        "origin": "synthetic",
        "text": "产能将达120万吨/年",
        "figure": {"label": "产能", "value": 120.0, "unit": "万吨"},
    },
    {
        "id": "s029",
        "origin": "synthetic",
        "text": "募资10亿元完成",
        "figure": {"label": "募资", "value": 10.0, "unit": "亿元"},
    },
    {
        "id": "s030",
        "origin": "synthetic",
        "text": "收入同比增幅达21.4%",
        "figure": {"label": "同比", "value": 21.4, "unit": "%"},
    },
    {
        "id": "s031",
        "origin": "synthetic",
        "text": "公司回购股份比例达到1%，累计金额2.3亿元",
        "figure": {"label": "回购", "value": 1.0, "unit": "%"},
    },
    {
        "id": "s032",
        "origin": "synthetic",
        "text": "持股5%以上股东拟减持不超过2%",
        "figure": {"label": "持股", "value": 5.0, "unit": "%"},
    },
]


def _is_junk(label: str, value: float, unit: str, text: str) -> bool:
    if label == "同比" and abs(value) > 500:
        return True
    if unit in {"元", "亿元"} and 1900 <= value <= 2100 and "年" in text:
        return True
    # "增长 预计2026" style
    if label == "同比" and unit == "%" and value > 1000:
        return True
    return False


def _excerpt(text: str, raw: str | None) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    if raw and raw in flat:
        idx = flat.find(raw)
        start = max(0, idx - 24)
        end = min(len(flat), idx + len(raw) + 36)
        return flat[start:end].strip()
    return flat[:160]


def claims_from_db(*, limit: int = 500) -> list[dict[str, object]]:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT news_id, source, title, coalesce(body, '') AS body
                    FROM news
                    ORDER BY published_at DESC
                    """
                )
            )
            .mappings()
            .all()
        )

    out: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for row in rows:
        title = str(row["title"] or "")
        body = str(row["body"] or "")
        full = re.sub(r"\s+", " ", f"{title} {body}").strip()
        for fig in extract_figures(full):
            if _is_junk(fig.label, fig.value, fig.unit, full):
                continue
            key = (fig.label, fig.value, fig.unit, full[:100])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "origin": "db",
                    "news_id": int(row["news_id"]),
                    "source": str(row["source"]),
                    "text": _excerpt(full, fig.raw),
                    "figure": {
                        "label": fig.label,
                        "value": fig.value,
                        "unit": fig.unit,
                    },
                }
            )
            if len(out) >= limit:
                return out
    return out


def build_gold(*, target: int = 100) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = list(SEED)
    rows.extend(claims_from_db(limit=max(target * 5, 300)))

    # Deduplicate by (text, figure)
    deduped: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for row in rows:
        fig = row["figure"]
        assert isinstance(fig, dict)
        key = (str(row["text"]), fig.get("label"), fig.get("value"), fig.get("unit"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    # Pad with unique synthetic templates if DB coverage is thin.
    pad_i = 0
    while len(deduped) < target:
        pad_i += 1
        value = round(1.0 + pad_i * 0.17, 2)
        text = f"门店测算营收{value}万元（抽检垫片{pad_i}）"
        fig = {"label": "营收", "value": value, "unit": "万元"}
        key = (text, fig["label"], fig["value"], fig["unit"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"origin": "synthetic", "text": text, "figure": fig})

    numbered: list[dict[str, object]] = []
    for i, row in enumerate(deduped[:target], start=1):
        item = dict(row)
        item["id"] = f"g{i:03d}"
        numbered.append(item)
    return numbered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    gold = build_gold(target=args.target)
    n_db = sum(1 for r in gold if r.get("origin") == "db")
    n_syn = sum(1 for r in gold if r.get("origin") == "synthetic")
    print(f"gold n={len(gold)} synthetic={n_syn} db={n_db} target={args.target}")
    if len(gold) < args.target:
        print(f"WARN: only {len(gold)} rows; ingest more news/announcements and re-run")

    if args.dry_run:
        for row in gold[:5]:
            print(json.dumps(row, ensure_ascii=False))
        return 0 if len(gold) >= args.target else 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in gold:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")
    return 0 if len(gold) >= args.target else 1


if __name__ == "__main__":
    raise SystemExit(main())

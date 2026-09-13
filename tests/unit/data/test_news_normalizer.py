"""Unit tests for news normalizer."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from quantagent.data.contracts import RawBatch
from quantagent.data.normalizers.news import NewsNormalizer, content_hash

CN_TZ = ZoneInfo("Asia/Shanghai")


def _batch(df: pl.DataFrame, *, source: str, dataset: str, tmp: Path) -> RawBatch:
    path = tmp / f"{source}.parquet"
    df.write_parquet(path)
    return RawBatch(
        batch_id=1,
        source=source,
        dataset=dataset,
        target_date=date(2026, 9, 13),
        raw_path=path,
        row_count=df.height,
        collected_at=datetime(2026, 9, 13, 12, 0, tzinfo=CN_TZ),
        meta={},
    )


def test_normalize_cls(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        {
            "标题": ["贵州茅台中标合同金额1.2亿元"],
            "内容": ["【快讯】600519 中标金额1.2亿元"],
            "发布日期": ["2026-09-13"],
            "发布时间": ["10:30:00"],
        }
    )
    df = NewsNormalizer().normalize(_batch(raw, source="cls", dataset="news", tmp=tmp_path))
    assert df.height == 1
    assert df["source"][0] == "cls"
    assert df["title"][0].startswith("贵州茅台")
    assert df["published_at"][0].hour == 10
    assert df["content_hash"][0] == content_hash(
        "贵州茅台中标合同金额1.2亿元", "【快讯】600519 中标金额1.2亿元"
    )


def test_normalize_em(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        {
            "标题": ["APEC 会议闭幕"],
            "摘要": ["摘要正文"],
            "发布时间": ["2026-09-13 12:42:33"],
            "链接": ["https://finance.eastmoney.com/a/202609133872795387.html"],
        }
    )
    df = NewsNormalizer().normalize(_batch(raw, source="em", dataset="news", tmp=tmp_path))
    assert df.height == 1
    assert df["source_id"][0] == "202609133872795387"
    assert df["url"][0].endswith(".html")


def test_normalize_announcement(tmp_path: Path) -> None:
    raw = pl.DataFrame(
        {
            "代码": ["600519"],
            "名称": ["贵州茅台"],
            "公告标题": ["贵州茅台:重大合同公告"],
            "公告类型": ["重大合同"],
            "公告日期": ["2026-09-12"],
            "网址": [
                "https://data.eastmoney.com/notices/detail/600519/AN202609121829285737.html"
            ],
        }
    )
    df = NewsNormalizer().normalize(
        _batch(raw, source="em_announce", dataset="announcement", tmp=tmp_path)
    )
    assert df.height == 1
    assert df["source"][0] == "em_announce"
    assert df["source_id"][0] == "AN202609121829285737"
    assert df["related_symbol"][0] == "600519.SH"
    assert df["announce_type"][0] == "重大合同"
    assert "600519.SH" in str(df["body"][0])
    assert df["published_at"][0].hour == 16


def test_symbol_from_em_announce_url() -> None:
    from quantagent.data.normalizers.news import symbol_from_em_announce_url

    url = "https://data.eastmoney.com/notices/detail/002375/AN202609041234.html"
    assert symbol_from_em_announce_url(url) == "002375.SZ"
    assert symbol_from_em_announce_url(None) is None
    assert symbol_from_em_announce_url("https://example.com/x") is None

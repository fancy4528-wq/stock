"""Shared domain enums (mirror DB enums)."""

from enum import StrEnum


class MarketCode(StrEnum):
    CN = "CN"
    HK = "HK"
    US = "US"


class ListingStatus(StrEnum):
    LISTED = "listed"
    SUSPENDED = "suspended"
    DELISTED = "delisted"
    PRE_IPO = "pre_ipo"


class BoardType(StrEnum):
    MAIN = "main"
    STAR = "star"
    GEM = "gem"
    BSE = "bse"
    NASDAQ = "nasdaq"
    NYSE = "nyse"
    AMEX = "amex"


class DataQuality(StrEnum):
    OK = "ok"
    SUSPECT = "suspect"
    CORRECTED = "corrected"
    MISSING = "missing"

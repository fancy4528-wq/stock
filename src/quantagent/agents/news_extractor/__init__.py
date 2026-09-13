"""NewsExtractor package (rule_v1 skeleton; LLM later)."""

from quantagent.agents.news_extractor.extractor import (
    EXTRACTOR_MODEL,
    EXTRACTOR_VERSION,
    RuleNewsExtractor,
)
from quantagent.agents.news_extractor.figures import extract_figures
from quantagent.agents.news_extractor.schema import EventExtraction, Figure, RelatedEntity

__all__ = [
    "EXTRACTOR_MODEL",
    "EXTRACTOR_VERSION",
    "EventExtraction",
    "Figure",
    "RelatedEntity",
    "RuleNewsExtractor",
    "extract_figures",
]

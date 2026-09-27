"""P2b three-tier funnel — L1 rules first (zero LLM at package import).

Import ``l2_triage`` directly when needed; it may pull ``agents.llm``.
"""

from quantagent.monitor.funnel.entity_matcher import EntityAliasConfig, EntityMatcher, load_entity_aliases
from quantagent.monitor.funnel.keywords import KeywordConfig, KeywordSeverity, keyword_severity, load_keyword_config
from quantagent.monitor.funnel.l1_rules import L1Filter, L1News, L1Result

__all__ = [
    "EntityAliasConfig",
    "EntityMatcher",
    "KeywordConfig",
    "KeywordSeverity",
    "L1Filter",
    "L1News",
    "L1Result",
    "keyword_severity",
    "load_entity_aliases",
    "load_keyword_config",
]

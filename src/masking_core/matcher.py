from __future__ import annotations

import re
from dataclasses import dataclass

from masking_core.models import Rule


@dataclass(frozen=True)
class MatchSpan:
    start: int
    end: int
    matched_text: str
    rule_name: str


def compile_rule_pattern(rule: Rule) -> re.Pattern[str]:
    """Compile a Rule's pattern into a usable regex.

    literal -> re.escape(pattern), so regex metacharacters in the pattern
    text are matched as literal substrings, never interpreted as regex.
    regex   -> pattern used as-is.
    """
    if rule.pattern_type == "literal":
        return re.compile(re.escape(rule.pattern))
    return re.compile(rule.pattern)


def find_matches(text: str, rule: Rule) -> list[MatchSpan]:
    """Return all non-overlapping matches of `rule` in `text`, left to right."""
    if not rule.enabled:
        return []
    compiled = compile_rule_pattern(rule)
    return [
        MatchSpan(m.start(), m.end(), m.group(0), rule.name)
        for m in compiled.finditer(text)
    ]

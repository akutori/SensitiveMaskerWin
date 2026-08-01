from __future__ import annotations

from dataclasses import dataclass, field

from masking_core.matcher import MatchSpan, find_matches
from masking_core.models import Rule, RuleProfile


@dataclass
class MappingStore:
    """original_value -> dummy_value, plus per-prefix counters for sequential mode.

    Passed in and returned by the caller (cli/gui) on every call -- never
    held as module-level/global state inside masking_core. Callers decide
    whether to reuse the same store across a batch of files or reset it
    per file.
    """

    mapping: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def get_or_create(self, original: str, rule: Rule) -> str:
        if original in self.mapping:
            return self.mapping[original]
        dummy = self._generate_dummy(original, rule)
        self.mapping[original] = dummy
        return dummy

    def _generate_dummy(self, original: str, rule: Rule) -> str:
        if rule.mode == "fixed":
            assert rule.fixed_value is not None  # guaranteed by Rule validator
            return rule.fixed_value
        assert rule.prefix is not None  # guaranteed by Rule validator
        self._counters[rule.prefix] = self._counters.get(rule.prefix, 0) + 1
        return f"{rule.prefix}{self._counters[rule.prefix]}__"


@dataclass(frozen=True)
class _Segment:
    text: str
    is_placeholder: bool


@dataclass(frozen=True)
class RuleMatchCount:
    """How many times one enabled rule matched during an apply_profile() run.

    One entry per *enabled* rule in `profile.rules` order (disabled rules
    never run, so they're omitted rather than reported as 0). `count` is
    the number of matched occurrences, not the number of distinct values
    (a repeated value still adds to count each time it's matched).
    """

    rule_name: str
    count: int


def apply_profile(
    text: str,
    profile: RuleProfile,
    store: MappingStore,
) -> tuple[str, MappingStore, list[RuleMatchCount]]:
    """Apply every enabled rule in `profile.rules`, in order, to `text`.

    Rules run strictly in `profile.rules` list order, and a rule can only
    ever match within segments of `text` not already claimed by an earlier
    rule's replacement -- this makes it structurally impossible for a
    later rule to re-match text inside an already-inserted placeholder.

    Returns (masked_text, updated_store, match_counts).
    """
    segments: list[_Segment] = [_Segment(text, False)]
    match_counts: list[RuleMatchCount] = []

    for rule in profile.rules:
        if not rule.enabled:
            continue
        segments, count = _apply_rule_to_segments(segments, rule, store)
        match_counts.append(RuleMatchCount(rule_name=rule.name, count=count))

    masked_text = "".join(seg.text for seg in segments)
    return masked_text, store, match_counts


def _apply_rule_to_segments(
    segments: list[_Segment],
    rule: Rule,
    store: MappingStore,
) -> tuple[list[_Segment], int]:
    new_segments: list[_Segment] = []
    total_matches = 0
    for seg in segments:
        if seg.is_placeholder:
            new_segments.append(seg)
            continue
        split_segments, count = _split_segment_by_rule(seg.text, rule, store)
        new_segments.extend(split_segments)
        total_matches += count
    return new_segments, total_matches


def _split_segment_by_rule(
    text: str,
    rule: Rule,
    store: MappingStore,
) -> tuple[list[_Segment], int]:
    matches: list[MatchSpan] = find_matches(text, rule)
    if not matches:
        return [_Segment(text, False)], 0

    result: list[_Segment] = []
    cursor = 0
    for m in matches:
        if m.start > cursor:
            result.append(_Segment(text[cursor:m.start], False))
        dummy = store.get_or_create(m.matched_text, rule)
        result.append(_Segment(dummy, True))
        cursor = m.end
    if cursor < len(text):
        result.append(_Segment(text[cursor:], False))
    return result, len(matches)

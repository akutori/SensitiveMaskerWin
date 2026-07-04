from masking_core.matcher import MatchSpan, compile_rule_pattern, find_matches
from masking_core.models import Rule


def _literal_rule(pattern: str, name: str = "lit", enabled: bool = True) -> Rule:
    return Rule(
        name=name,
        pattern_type="literal",
        pattern=pattern,
        mode="fixed",
        fixed_value="__MASK__",
        enabled=enabled,
    )


def _regex_rule(pattern: str, name: str = "rx", enabled: bool = True) -> Rule:
    return Rule(
        name=name,
        pattern_type="regex",
        pattern=pattern,
        mode="fixed",
        fixed_value="__MASK__",
        enabled=enabled,
    )


# --- literal matching -------------------------------------------------

def test_literal_match_finds_exact_substring():
    rule = _literal_rule("192.0.2.10")
    matches = find_matches("connect to 192.0.2.10 now", rule)
    assert [m.matched_text for m in matches] == ["192.0.2.10"]


def test_literal_match_treats_dot_as_literal_not_wildcard():
    # Positive: the exact literal string (with real dots) matches.
    rule = _literal_rule("192.0.2.10")
    assert len(find_matches("ip=192.0.2.10;", rule)) == 1


def test_literal_match_does_not_match_wildcard_variant():
    # Negative: if '.' were treated as regex wildcard, this would also
    # match "192X0X2X10" (each '.' matching any single char). It must not.
    rule = _literal_rule("192.0.2.10")
    assert find_matches("ip=192X0X2X10;", rule) == []


def test_literal_match_special_chars_parens_plus_match_exact_text():
    # Positive: literal pattern containing regex metacharacters ( ) +
    # matches only the exact substring.
    rule = _literal_rule("value(x)+1")
    matches = find_matches("config: value(x)+1 end", rule)
    assert [m.matched_text for m in matches] == ["value(x)+1"]


def test_literal_match_special_chars_do_not_match_regex_interpretation():
    # Negative: under real regex semantics, "value(x)+1" means
    # "value" followed by one-or-more "x", followed by "1" -- which
    # would match "valuexxx1". Literal mode must NOT match this.
    rule = _literal_rule("value(x)+1")
    assert find_matches("config: valuexxx1 end", rule) == []


# --- regex matching -----------------------------------------------------

def test_regex_match_finds_pattern():
    rule = _regex_rule(r"\d{3}-\d{4}")
    matches = find_matches("call 123-4567 now", rule)
    assert [m.matched_text for m in matches] == ["123-4567"]


def test_regex_match_does_not_match_wrong_shape():
    rule = _regex_rule(r"\d{3}-\d{4}")
    assert find_matches("call 12-34567 now", rule) == []


# --- find_matches behavior ------------------------------------------------

def test_find_matches_returns_multiple_non_overlapping_spans():
    rule = _regex_rule(r"\d{3}-\d{4}")
    matches = find_matches("first 111-2222 then 333-4444", rule)
    assert [m.matched_text for m in matches] == ["111-2222", "333-4444"]


def test_find_matches_respects_enabled_false():
    rule = _regex_rule(r"\d{3}-\d{4}", enabled=False)
    assert find_matches("call 123-4567 now", rule) == []


def test_find_matches_no_match_returns_empty_list():
    rule = _regex_rule(r"\d{3}-\d{4}")
    assert find_matches("nothing to see here", rule) == []


def test_match_span_reports_correct_start_end_and_text():
    rule = _regex_rule(r"\d{3}-\d{4}", name="phone")
    text = "call 123-4567 now"
    matches = find_matches(text, rule)
    assert len(matches) == 1
    m = matches[0]
    assert isinstance(m, MatchSpan)
    assert (m.start, m.end) == (5, 13)
    assert text[m.start:m.end] == m.matched_text == "123-4567"
    assert m.rule_name == "phone"


# --- compile_rule_pattern -------------------------------------------------

def test_compile_rule_pattern_literal_escapes_special_chars():
    rule = _literal_rule("a.b(c)+d")
    compiled = compile_rule_pattern(rule)
    assert compiled.match("a.b(c)+d") is not None
    assert compiled.fullmatch("aXbcccd") is None


def test_compile_rule_pattern_regex_used_as_is():
    rule = _regex_rule(r"\d+")
    compiled = compile_rule_pattern(rule)
    assert compiled.fullmatch("12345") is not None

import pytest
from pydantic import ValidationError

from masking_core.models import Rule, RuleProfile, format_validation_error


def test_rule_fixed_mode_requires_fixed_value():
    with pytest.raises(ValidationError):
        Rule(name="r1", pattern_type="literal", pattern="x", mode="fixed")


def test_rule_fixed_mode_with_fixed_value_succeeds():
    rule = Rule(
        name="r1",
        pattern_type="literal",
        pattern="x",
        mode="fixed",
        fixed_value="__MASK__",
    )
    assert rule.fixed_value == "__MASK__"
    assert rule.prefix is None


def test_rule_sequential_mode_requires_prefix():
    with pytest.raises(ValidationError):
        Rule(name="r1", pattern_type="regex", pattern=r"\d+", mode="sequential")


def test_rule_sequential_mode_with_prefix_succeeds():
    rule = Rule(
        name="r1",
        pattern_type="regex",
        pattern=r"\d+",
        mode="sequential",
        prefix="__MASK_X_",
    )
    assert rule.prefix == "__MASK_X_"
    assert rule.fixed_value is None


def test_rule_fixed_mode_rejects_empty_string_fixed_value():
    with pytest.raises(ValidationError):
        Rule(name="r1", pattern_type="literal", pattern="x", mode="fixed", fixed_value="")


def test_rule_sequential_mode_rejects_empty_string_prefix():
    with pytest.raises(ValidationError):
        Rule(name="r1", pattern_type="regex", pattern=r"\d+", mode="sequential", prefix="")


def test_rule_legacy_random_mode_value_no_longer_accepted():
    # GitHub issue #11: "random" was the mode value's original, misleading
    # name (the actual behavior has always been a sequential counter, never
    # random). No backward-compat alias is kept -- old profile JSON files
    # using "random" must now fail cleanly rather than silently normalize.
    with pytest.raises(ValidationError):
        Rule(name="r1", pattern_type="regex", pattern=r"\d+", mode="random", prefix="__P_")


def test_rule_invalid_mode_literal_rejected():
    with pytest.raises(ValidationError):
        Rule(
            name="r1",
            pattern_type="literal",
            pattern="x",
            mode="bogus",
            fixed_value="v",
        )


def test_rule_invalid_pattern_type_rejected():
    with pytest.raises(ValidationError):
        Rule(
            name="r1",
            pattern_type="fuzzy",
            pattern="x",
            mode="fixed",
            fixed_value="v",
        )


def test_rule_enabled_defaults_true():
    rule = Rule(
        name="r1",
        pattern_type="literal",
        pattern="x",
        mode="fixed",
        fixed_value="v",
    )
    assert rule.enabled is True


def test_rule_enabled_can_be_set_false():
    rule = Rule(
        name="r1",
        pattern_type="literal",
        pattern="x",
        mode="fixed",
        fixed_value="v",
        enabled=False,
    )
    assert rule.enabled is False


def test_rule_profile_holds_multiple_rules_in_order():
    rule_a = Rule(name="a", pattern_type="literal", pattern="x", mode="fixed", fixed_value="v")
    rule_b = Rule(name="b", pattern_type="regex", pattern=r"\d+", mode="sequential", prefix="__P_")
    profile = RuleProfile(profile_name="test", rules=[rule_a, rule_b])
    assert [r.name for r in profile.rules] == ["a", "b"]


def test_rule_profile_defaults_to_empty_rules_list():
    profile = RuleProfile(profile_name="empty")
    assert profile.rules == []


def test_rule_regex_pattern_type_rejects_syntactically_invalid_regex():
    # Found via adversarial review of issue #12's fix: an invalid regex used
    # to save successfully (no validation anywhere) and only crash uncaught
    # with re.error the moment a rule was actually used to mask text. Fail
    # fast and cleanly at construction time instead, matching how
    # fixed_value/prefix are already validated here.
    with pytest.raises(ValidationError):
        Rule(name="r1", pattern_type="regex", pattern="(", mode="fixed", fixed_value="v")


def test_rule_regex_pattern_type_accepts_valid_regex():
    rule = Rule(
        name="r1", pattern_type="regex", pattern=r"\d{3}-\d{4}", mode="fixed", fixed_value="v"
    )
    assert rule.pattern == r"\d{3}-\d{4}"


def test_rule_literal_pattern_type_allows_regex_special_characters():
    # Negative test paired with the two above: pattern_type="literal" must
    # NOT be regex-validated -- a literal string containing regex-special
    # characters like "(" is a perfectly valid literal pattern.
    rule = Rule(name="r1", pattern_type="literal", pattern="(", mode="fixed", fixed_value="v")
    assert rule.pattern == "("


# --- format_validation_error --------------------------------------------
# GitHub issue #12: raw pydantic ValidationError text leaked pydantic.dev
# URLs, `type=value_error`, and a repr() dump of every submitted field
# (including whatever real sensitive value a user typed while testing a
# rule) straight into GUI error dialogs / CLI stderr. format_validation_error
# must extract only the human-authored validator message and drop
# everything else pydantic attaches.


def test_format_validation_error_returns_only_fixed_value_message():
    with pytest.raises(ValidationError) as exc_info:
        Rule(name="r1", pattern_type="literal", pattern="x", mode="fixed")

    message = format_validation_error(exc_info.value)

    assert message == "ルール 'r1': mode='fixed' の場合は 'fixed_value' が必須です"


def test_format_validation_error_returns_only_prefix_message():
    with pytest.raises(ValidationError) as exc_info:
        Rule(name="r1", pattern_type="regex", pattern=r"\d+", mode="sequential")

    message = format_validation_error(exc_info.value)

    assert message == "ルール 'r1': mode='sequential' の場合は 'prefix' が必須です"


def test_format_validation_error_excludes_pydantic_internals():
    # Negative test: none of pydantic's own internal-implementation markers
    # (its docs URL, the machine-readable error type/kind, the "Value error, "
    # prefix it auto-prepends) should survive into the formatted message.
    with pytest.raises(ValidationError) as exc_info:
        Rule(name="r1", pattern_type="literal", pattern="x", mode="fixed")

    message = format_validation_error(exc_info.value)

    assert "pydantic.dev" not in message
    assert "type=value_error" not in message
    assert "Value error," not in message


def test_format_validation_error_excludes_dumped_field_values():
    # Negative test: the specific leak from issue #12 -- pydantic's
    # input_value=... repr dumps every submitted field, including whatever
    # (potentially real/sensitive) value the user typed into `pattern`.
    # A synthetic, obviously-fake value stands in for a real one here.
    fake_pattern = "0120-XXX-FAKE-CALLER-ID"
    with pytest.raises(ValidationError) as exc_info:
        Rule(name="r1", pattern_type="literal", pattern=fake_pattern, mode="fixed")

    message = format_validation_error(exc_info.value)

    assert "input_value" not in message
    assert fake_pattern not in message


def test_format_validation_error_joins_multiple_errors_one_per_line():
    # A profile can contain more than one invalid rule at once (e.g. a
    # hand-edited/corrupted JSON file); every error's message must survive,
    # not just the first.
    with pytest.raises(ValidationError) as exc_info:
        RuleProfile(
            profile_name="broken",
            rules=[
                {"name": "a", "pattern_type": "literal", "pattern": "x", "mode": "fixed"},
                {"name": "b", "pattern_type": "regex", "pattern": r"\d+", "mode": "sequential"},
            ],
        )

    message = format_validation_error(exc_info.value)

    assert "ルール 'a': mode='fixed' の場合は 'fixed_value' が必須です" in message
    assert "ルール 'b': mode='sequential' の場合は 'prefix' が必須です" in message
    # Negative: a naive `return str(exc)` would also satisfy the two
    # assertions above (the clean text sits embedded inside pydantic's raw
    # dump too), so this must independently confirm no leak markers survive
    # for the multi-error path specifically, not just the single-error path.
    assert "pydantic.dev" not in message
    assert "type=value_error" not in message
    assert "input_value" not in message


def test_format_validation_error_handles_builtin_pydantic_error_not_just_custom_validator():
    # Not every ValidationError comes from check_mode_requirements' custom
    # ValueError -- a built-in pydantic error (e.g. an out-of-enum
    # pattern_type, as could appear in a hand-edited profile JSON) takes a
    # different path through format_validation_error (the `msg` fallback
    # branch, since there is no ctx.error for this error type). A leaked
    # fake-sensitive value stands in for whatever a hand-edited file might
    # contain in the same field.
    with pytest.raises(ValidationError) as exc_info:
        Rule.model_validate(
            {
                "name": "r1",
                "pattern_type": "SENSITIVE_09012345678_NOT_A_REAL_TYPE",
                "pattern": "x",
                "mode": "fixed",
                "fixed_value": "v",
            }
        )

    message = format_validation_error(exc_info.value)

    assert "pydantic.dev" not in message
    assert "type=value_error" not in message
    assert "input_value" not in message
    assert "SENSITIVE_09012345678_NOT_A_REAL_TYPE" not in message

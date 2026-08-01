from masking_core.masker import MappingStore, RuleMatchCount, apply_profile
from masking_core.models import Rule, RuleProfile


def _rule(name, pattern, pattern_type="regex", mode="sequential", prefix=None, fixed_value=None, enabled=True):
    kwargs = {}
    if mode == "sequential":
        kwargs["prefix"] = prefix
    else:
        kwargs["fixed_value"] = fixed_value
    return Rule(
        name=name,
        pattern_type=pattern_type,
        pattern=pattern,
        mode=mode,
        enabled=enabled,
        **kwargs,
    )


# --- basic masking behavior -------------------------------------------

def test_apply_profile_masks_single_rule_and_leaves_rest_untouched():
    rule = _rule("phone", r"\d{3}-\d{4}", prefix="__MASK_PHONE_")
    profile = RuleProfile(profile_name="p", rules=[rule])
    text = "2026-01-01 call 123-4567 please"
    masked, _, _ = apply_profile(text, profile, MappingStore())
    assert masked == "2026-01-01 call __MASK_PHONE_1__ please"


def test_apply_profile_fixed_mode_produces_configured_value():
    rule = _rule("pwd", r"secret\d+", mode="fixed", fixed_value="__MASK_REDACTED__")
    profile = RuleProfile(profile_name="p", rules=[rule])
    masked, _, _ = apply_profile("login secret123 ok", profile, MappingStore())
    assert masked == "login __MASK_REDACTED__ ok"


def test_apply_profile_sequential_mode_produces_incrementing_counter():
    rule = _rule("num", r"\d{4}", prefix="__MASK_N_")
    profile = RuleProfile(profile_name="p", rules=[rule])
    masked, store, _ = apply_profile("a 1111 b 2222 c", profile, MappingStore())
    assert masked == "a __MASK_N_1__ b __MASK_N_2__ c"
    assert store.mapping == {"1111": "__MASK_N_1__", "2222": "__MASK_N_2__"}


def test_apply_profile_same_original_value_reuses_same_dummy():
    rule = _rule("num", r"\d{4}", prefix="__MASK_N_")
    profile = RuleProfile(profile_name="p", rules=[rule])
    masked, _, _ = apply_profile("a 1111 b 1111 c", profile, MappingStore())
    assert masked == "a __MASK_N_1__ b __MASK_N_1__ c"


def test_apply_profile_disabled_rule_is_skipped():
    rule = _rule("num", r"\d{4}", prefix="__MASK_N_", enabled=False)
    profile = RuleProfile(profile_name="p", rules=[rule])
    text = "a 1111 b"
    masked, store, _ = apply_profile(text, profile, MappingStore())
    assert masked == text
    assert store.mapping == {}


def test_apply_profile_empty_profile_returns_text_unchanged():
    profile = RuleProfile(profile_name="empty", rules=[])
    text = "nothing to mask here"
    masked, store, _ = apply_profile(text, profile, MappingStore())
    assert masked == text
    assert store.mapping == {}


# --- double-mask prevention (core anti-regression test) ------------------

def test_apply_profile_does_not_double_mask_placeholder_text():
    # Rule A claims any 3+ digit run first; its inserted placeholder
    # (e.g. "__MASK_DIGIT_1__") itself contains a digit ("1"). Rule B
    # matches any digit run at all. If placeholder text were re-scanned,
    # rule B would corrupt rule A's placeholder by masking the digit
    # inside it.
    rule_a = _rule("digits3plus", r"\d{3,}", prefix="__MASK_DIGIT_")
    rule_b = _rule("anydigit", r"\d+", prefix="__MASK_ANY_")
    profile = RuleProfile(profile_name="p", rules=[rule_a, rule_b])

    text = "code 12345 ab12cd end"
    masked, _, _ = apply_profile(text, profile, MappingStore())

    assert "__MASK_DIGIT_1__" in masked
    assert masked == "code __MASK_DIGIT_1__ ab__MASK_ANY_1__cd end"


# --- rule order affects result (order-dependent test) ---------------------

def test_apply_profile_rule_order_affects_result():
    header_rule = _rule("header_ip", r"IP: \d{1,3}(?:\.\d{1,3}){3}", prefix="__MASK_HDR_")
    generic_ip_rule = _rule("generic_ip", r"\d{1,3}(?:\.\d{1,3}){3}", prefix="__MASK_IP_")

    text = "IP: 192.0.2.10 other"

    forward = RuleProfile(profile_name="fwd", rules=[header_rule, generic_ip_rule])
    reversed_profile = RuleProfile(profile_name="rev", rules=[generic_ip_rule, header_rule])

    forward_masked, _, _ = apply_profile(text, forward, MappingStore())
    reversed_masked, _, _ = apply_profile(text, reversed_profile, MappingStore())

    assert forward_masked == "__MASK_HDR_1__ other"
    assert reversed_masked == "IP: __MASK_IP_1__ other"
    assert forward_masked != reversed_masked


# --- MappingStore unit tests --------------------------------------------

def test_mapping_store_get_or_create_fixed_mode():
    rule = _rule("pwd", r".*", mode="fixed", fixed_value="__MASK_REDACTED__")
    store = MappingStore()
    assert store.get_or_create("secret", rule) == "__MASK_REDACTED__"
    assert store.get_or_create("secret", rule) == "__MASK_REDACTED__"


def test_mapping_store_get_or_create_sequential_mode_increments_counter():
    rule = _rule("num", r".*", prefix="__MASK_N_")
    store = MappingStore()
    assert store.get_or_create("111", rule) == "__MASK_N_1__"
    assert store.get_or_create("222", rule) == "__MASK_N_2__"
    assert store.get_or_create("111", rule) == "__MASK_N_1__"


def test_mapping_store_counters_independent_per_prefix():
    rule_a = _rule("a", r".*", prefix="__MASK_A_")
    rule_b = _rule("b", r".*", prefix="__MASK_B_")
    store = MappingStore()
    assert store.get_or_create("x1", rule_a) == "__MASK_A_1__"
    assert store.get_or_create("x2", rule_a) == "__MASK_A_2__"
    assert store.get_or_create("y1", rule_b) == "__MASK_B_1__"


# --- match-count reporting (issue #14 leak-verification summary) ---------
# apply_profile's 3rd return value: list[RuleMatchCount], one entry per
# *enabled* rule in profile.rules order, used by the GUI's "direct convert"
# path to show a "何件マスクしたか" summary without rendering the full
# masked text on screen.


def test_apply_profile_reports_match_count_for_matching_rule():
    rule = _rule("phone", r"\d{3}-\d{4}", prefix="__MASK_PHONE_")
    profile = RuleProfile(profile_name="p", rules=[rule])
    text = "call 123-4567 or 987-6543"
    _, _, match_counts = apply_profile(text, profile, MappingStore())
    assert match_counts == [RuleMatchCount(rule_name="phone", count=2)]


def test_apply_profile_reports_zero_count_for_enabled_rule_with_no_match():
    # A rule that matched nothing must still be reported (count=0), not
    # silently omitted -- this is exactly the signal a "見せずに直接変換"
    # user needs to notice "this rule found nothing, is that expected?".
    rule = _rule("phone", r"\d{3}-\d{4}", prefix="__MASK_PHONE_")
    profile = RuleProfile(profile_name="p", rules=[rule])
    _, _, match_counts = apply_profile("nothing to mask here", profile, MappingStore())
    assert match_counts == [RuleMatchCount(rule_name="phone", count=0)]


def test_apply_profile_match_counts_omit_disabled_rules():
    enabled_rule = _rule("phone", r"\d{3}-\d{4}", prefix="__MASK_PHONE_")
    disabled_rule = _rule("ip", r"\d{1,3}\.\d{1,3}", prefix="__MASK_IP_", enabled=False)
    profile = RuleProfile(profile_name="p", rules=[enabled_rule, disabled_rule])
    _, _, match_counts = apply_profile("call 123-4567", profile, MappingStore())
    assert match_counts == [RuleMatchCount(rule_name="phone", count=1)]


def test_apply_profile_match_counts_preserve_rule_order_and_count_each_rule_independently():
    rule_a = _rule("digits3plus", r"\d{3,}", prefix="__MASK_DIGIT_")
    rule_b = _rule("anydigit", r"\d+", prefix="__MASK_ANY_")
    profile = RuleProfile(profile_name="p", rules=[rule_a, rule_b])

    _, _, match_counts = apply_profile("code 12345 ab12cd end", profile, MappingStore())

    # rule_a claims "12345" (1 match); rule_b then only sees the leftover
    # "12" inside "ab12cd" (1 match) since "12345" is already a placeholder.
    assert match_counts == [
        RuleMatchCount(rule_name="digits3plus", count=1),
        RuleMatchCount(rule_name="anydigit", count=1),
    ]


def test_apply_profile_match_count_counts_every_occurrence_not_unique_values():
    # The same original value appearing twice must count as 2 matches, even
    # though MappingStore.mapping dedupes it down to a single entry -- the
    # summary is meant to reflect "how many spots got masked", not "how many
    # distinct secrets were found".
    rule = _rule("num", r"\d{4}", prefix="__MASK_N_")
    profile = RuleProfile(profile_name="p", rules=[rule])
    _, store, match_counts = apply_profile("a 1111 b 1111 c", profile, MappingStore())
    assert match_counts == [RuleMatchCount(rule_name="num", count=2)]
    assert len(store.mapping) == 1

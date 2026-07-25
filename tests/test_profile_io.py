import json

import pytest

from masking_core.models import Rule, RuleProfile
from masking_core.profile_io import ProfileLoadError, load_profile, save_profile


def test_load_profile_valid_json_returns_rule_profile(tmp_path):
    data = {
        "profile_name": "test",
        "description": "a test profile",
        "rules": [
            {
                "name": "phone",
                "pattern_type": "regex",
                "pattern": r"\d{3}-\d{4}",
                "mode": "random",
                "prefix": "__MASK_PHONE_",
            }
        ],
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    profile = load_profile(path)

    assert isinstance(profile, RuleProfile)
    assert profile.profile_name == "test"
    assert len(profile.rules) == 1
    assert profile.rules[0].name == "phone"


def test_load_profile_missing_file_raises_profile_load_error(tmp_path):
    with pytest.raises(ProfileLoadError):
        load_profile(tmp_path / "does_not_exist.json")


def test_load_profile_malformed_json_raises_profile_load_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ProfileLoadError, match="JSONが不正"):
        load_profile(path)


def test_load_profile_schema_violation_raises_profile_load_error(tmp_path):
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "phone",
                "pattern_type": "regex",
                "pattern": r"\d{3}-\d{4}",
                "mode": "fixed",
                # missing fixed_value -- violates Rule's model_validator
            }
        ],
    }
    path = tmp_path / "invalid_schema.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProfileLoadError):
        load_profile(path)


def test_load_profile_schema_violation_message_excludes_pydantic_internals_and_field_values(
    tmp_path,
):
    # GitHub issue #12: a schema-invalid profile's ValidationError used to be
    # stringified raw, leaking pydantic.dev URLs, type=value_error, and an
    # input_value=... repr dump of every field -- including whatever
    # (potentially sensitive) pattern text a rule in the file contained.
    fake_pattern = "0120-XXX-FAKE-CALLER-ID"
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "phone",
                "pattern_type": "regex",
                "pattern": fake_pattern,
                "mode": "fixed",
                # missing fixed_value -- violates Rule's model_validator
            }
        ],
    }
    path = tmp_path / "invalid_schema.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProfileLoadError) as exc_info:
        load_profile(path)

    message = str(exc_info.value)
    assert "ルール 'phone': mode='fixed' の場合は 'fixed_value' が必須です" in message
    assert "pydantic.dev" not in message
    assert "type=value_error" not in message
    assert "input_value" not in message
    assert fake_pattern not in message


def test_load_profile_invalid_regex_pattern_raises_profile_load_error_cleanly(tmp_path):
    # Adversarial-review follow-up to issue #12: a profile with a
    # syntactically invalid regex used to load successfully (no validation
    # anywhere) and only crash uncaught with re.error the moment the rule
    # was actually used to mask text. It must now fail cleanly at load time.
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "broken_regex",
                "pattern_type": "regex",
                "pattern": "(",
                "mode": "fixed",
                "fixed_value": "v",
            }
        ],
    }
    path = tmp_path / "invalid_regex.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProfileLoadError) as exc_info:
        load_profile(path)

    message = str(exc_info.value)
    assert "正しい正規表現ではありません" in message
    assert "pydantic.dev" not in message
    assert "input_value" not in message


def test_save_profile_round_trip(tmp_path):
    rule = Rule(
        name="phone",
        pattern_type="regex",
        pattern=r"\d{3}-\d{4}",
        mode="random",
        prefix="__MASK_PHONE_",
    )
    profile = RuleProfile(profile_name="roundtrip", rules=[rule])
    path = tmp_path / "out.json"

    save_profile(profile, path)
    loaded = load_profile(path)

    assert loaded == profile


def test_save_profile_excludes_none_fields(tmp_path):
    rule = Rule(
        name="phone",
        pattern_type="regex",
        pattern=r"\d{3}-\d{4}",
        mode="random",
        prefix="__MASK_PHONE_",
    )
    profile = RuleProfile(profile_name="p", rules=[rule])
    path = tmp_path / "out.json"

    save_profile(profile, path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert "fixed_value" not in raw["rules"][0]

"""Synthetic-only dummy log data for tests.

NEVER real data -- see CLAUDE.md "テストデータポリシー". Every value below
is intentionally fake: phone numbers use an obviously-dummy 0120 prefix or
a placeholder-shaped number, IPs are drawn from RFC 5737
documentation-reserved ranges (192.0.2.0/24, 198.51.100.0/24,
203.0.113.0/24), passwords carry an explicit _FAKE suffix, and SIP/email
hosts use example.com / example.invalid.
"""

FAKE_PHONE_1 = "0120-123-456"
FAKE_PHONE_2 = "090-1234-5678"

FAKE_IP_1 = "192.0.2.10"
FAKE_IP_2 = "198.51.100.42"
FAKE_IP_3 = "203.0.113.7"

FAKE_PASSWORD_LINE = "password=hunter2_FAKE"
FAKE_PASSWORD_LINE_ALT_CASE = "PASSWORD: SuperSecret_FAKE123"

FAKE_EMAIL = "test.user@example.com"

FAKE_SIP_URI = "sip:0120123456@example.invalid"
FAKE_SIP_AUTH_HEADER = (
    'Authorization: Digest username="0120123456_FAKE", '
    'realm="example.invalid", nonce="abcFAKEnonce123", '
    'response="deadbeefFAKEHASHvalue0000"'
)
FAKE_SIP_CONTACT_HEADER = f"Contact: <sip:0120123456@{FAKE_IP_1}:5060>"
FAKE_SIP_VIA_HEADER = f"Via: SIP/2.0/UDP {FAKE_IP_2}:5060;branch=z9hG4bKFAKEbranch"

SAMPLE_GENERAL_LOG = f"""\
2026-01-01 10:00:00 INFO connection established
2026-01-01 10:00:01 DEBUG caller={FAKE_PHONE_1} ip={FAKE_IP_1}
2026-01-01 10:00:02 WARN {FAKE_PASSWORD_LINE} used for login
2026-01-01 10:00:03 INFO contact email {FAKE_EMAIL}
"""

SAMPLE_SIP_LOG = f"""\
INVITE {FAKE_SIP_URI} SIP/2.0
{FAKE_SIP_VIA_HEADER}
{FAKE_SIP_CONTACT_HEADER}
{FAKE_SIP_AUTH_HEADER}
2026-01-01 10:05:00 NOTICE call from {FAKE_PHONE_2}
"""

LITERAL_SPECIAL_CHARS_SAMPLE = (
    "config.value(x)+1 should stay untouched unless literal-matched exactly"
)

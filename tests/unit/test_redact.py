"""AC-217: secret-looking values are replaced before data leaves the gate (also used by the audit log, AC-131)."""

from __future__ import annotations

import pytest

from keel_gate.domain.redact import REDACTED, redact_text, redact_value

SECRETS = [
    "sk-ant-api03-" + "a1B2" * 10,
    "sk-proj-" + "Z9y8" * 8,
    "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
    "rk_test_" + "abcdefghijklmnop1234",
    "whsec_" + "Q1w2E3r4T5y6U7i8O9p0",
    "ASIA" + "QRSTUVWXYZ234567",
    "ghp_" + "x" * 36,
    "github_pat_" + "Ab1_" * 10,
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "xoxb-1234567890-abcdefghij",
    "AIza" + "B" * 35,
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_token_shapes_are_redacted(secret: str) -> None:
    text = redact_text(f"use {secret} here")

    assert secret not in text
    assert text == f"use {REDACTED} here"


def test_private_keys_are_redacted() -> None:
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----"

    assert redact_text(f"key:\n{key}\nend") == f"key:\n{REDACTED}\nend"


def test_bearer_tokens_keep_the_word_bearer() -> None:
    assert redact_text("Authorization: Bearer abc.def-ghi_jkl012345") == f"Authorization: Bearer {REDACTED}"


def test_passwords_in_urls_are_redacted() -> None:
    assert redact_text("psql postgres://admin:s3cr3t!@db.example.com/prod") == (
        f"psql postgres://admin:{REDACTED}@db.example.com/prod"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password=hunter2", f"password={REDACTED}"),
        ("API_KEY: abc123xyz", f"API_KEY: {REDACTED}"),
        ("export GITHUB_TOKEN=abc123", f"export GITHUB_TOKEN={REDACTED}"),
        ("client_secret = 'zzz'", f"client_secret = {REDACTED}"),
        ('PASSWORD="hunter 2 x" ./run', f"PASSWORD={REDACTED} ./run"),
        (
            """curl -d '{"password": "hunter2"}' https://x.example""",
            f"""curl -d '{{"password": {REDACTED}}}' https://x.example""",
        ),
        ("psql --password hunter2 -h db", f"psql --password {REDACTED} -h db"),
        ("tool --api-key=abc123 run", f"tool --api-key={REDACTED} run"),
        ("mysql -u root -phunter2 shop", f"mysql -u root -p{REDACTED} shop"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", f"Authorization: Basic {REDACTED}"),
        ("Cookie: session=abc; theme=dark", f"Cookie: {REDACTED}"),
        ("git clone https://:tok123@github.com/x/y", f"git clone https://:{REDACTED}@github.com/x/y"),
        (
            "aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            f"aws configure set aws_secret_access_key {REDACTED}",
        ),
    ],
)
def test_assignments_to_secret_names_are_redacted(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "ls -la",
        "git commit -m 'fix tokenizer'",
        "pytest -q tests/test_password_reset.py",
        "sk-short",
        "skip-this",
        "mkdir -p src/app",
        "git log --author=alice",
    ],
)
def test_normal_text_is_untouched(text: str) -> None:
    assert redact_text(text) == text


def test_nested_values_and_secret_keys_are_redacted() -> None:
    value = {
        "command": "deploy --token ghp_" + "y" * 36,
        "headers": {"Authorization": "Bearer abcdefghijklmnop", "Accept": "json"},
        "password": "plain words",
        "items": ["ok", {"api_key": 123}],
    }

    assert redact_value(value) == {
        "command": f"deploy --token {REDACTED}",
        "headers": {"Authorization": REDACTED, "Accept": "json"},
        "password": REDACTED,
        "items": ["ok", {"api_key": REDACTED}],
    }


def test_redact_value_does_not_change_its_input() -> None:
    value = {"password": "x", "list": ["password=y"]}

    redact_value(value)

    assert value == {"password": "x", "list": ["password=y"]}


@pytest.mark.parametrize("key", ["DB_PASS", "passphrase", "Authorization", "auth", "Cookie", "session", "access_key"])
def test_more_secret_key_names_are_redacted(key: str) -> None:
    assert redact_value({key: "value", "note": "keep"}) == {key: REDACTED, "note": "keep"}


@pytest.mark.parametrize("key", ["author", "passenger", "bypass_cache", "tokenizer_name", "session_count"])
def test_harmless_key_names_are_kept(key: str) -> None:
    assert redact_value({key: "value"}) == {key: "value"}


def test_secrets_in_dict_keys_are_redacted() -> None:
    key = "ghp_" + "k" * 36

    assert redact_value({key: 1}) == {REDACTED: 1}

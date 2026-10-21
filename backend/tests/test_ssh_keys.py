"""`services/ssh_keys.py` — публичный ключ sshfs (раздел 15.1 ТЗ)."""

from __future__ import annotations

import base64

import pytest

from services.errors import ValidationError
from services.ssh_keys import (
    MAX_PUBLIC_KEY_LENGTH,
    fingerprint,
    fingerprint_of_public_key,
    parse_public_key,
)
from tests.factories import (
    SAMPLE_ECDSA_FINGERPRINT,
    SAMPLE_ECDSA_KEY,
    SAMPLE_ED25519_BODY,
    SAMPLE_ED25519_FINGERPRINT,
    SAMPLE_ED25519_KEY,
)


class TestParse:
    @pytest.mark.parametrize(
        ("text", "key_type", "comment"),
        [
            (SAMPLE_ED25519_KEY, "ssh-ed25519", "dev@example.com"),
            (f"  {SAMPLE_ECDSA_KEY}  \n", "ecdsa-sha2-nistp256", None),
            (
                f"ssh-ed25519 {SAMPLE_ED25519_BODY} рабочий ноутбук",
                "ssh-ed25519",
                "рабочий ноутбук",
            ),
        ],
        ids=["ed25519", "ecdsa_trimmed", "comment_with_spaces"],
    )
    def test_accepts(self, text: str, key_type: str, comment: str | None) -> None:
        parsed = parse_public_key(text)

        assert parsed.key_type == key_type
        assert parsed.comment == comment

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "ssh-ed25519",
            f"ssh-dss {SAMPLE_ED25519_BODY}",
            "ssh-ed25519 не-base64!!!",
            f"ssh-rsa {SAMPLE_ED25519_BODY}",
            f"ssh-ed25519 {base64.b64encode(b'xx').decode()}",
            f"{SAMPLE_ED25519_KEY}\n{SAMPLE_ECDSA_KEY}",
            f"ssh-ed25519 {SAMPLE_ED25519_BODY} {'x' * MAX_PUBLIC_KEY_LENGTH}",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
        ],
        ids=[
            "empty",
            "no_body",
            "unsupported_type",
            "not_base64",
            "type_mismatch",
            "truncated_blob",
            "two_keys",
            "too_long",
            "private_key",
        ],
    )
    def test_rejects(self, text: str) -> None:
        with pytest.raises(ValidationError):
            parse_public_key(text)

    def test_normalizes_line(self) -> None:
        parsed = parse_public_key(f"  ssh-ed25519   {SAMPLE_ED25519_BODY}   dev@example.com ")

        assert parsed.to_authorized_keys_line() == SAMPLE_ED25519_KEY


class TestFingerprint:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (SAMPLE_ED25519_KEY, SAMPLE_ED25519_FINGERPRINT),
            (SAMPLE_ECDSA_KEY, SAMPLE_ECDSA_FINGERPRINT),
        ],
        ids=["ed25519", "ecdsa"],
    )
    def test_matches_ssh_keygen(self, text: str, expected: str) -> None:
        assert fingerprint(parse_public_key(text).blob) == expected

    def test_of_stored_key(self) -> None:
        assert fingerprint_of_public_key(SAMPLE_ED25519_KEY) == SAMPLE_ED25519_FINGERPRINT

    def test_of_broken_stored_key(self) -> None:
        assert fingerprint_of_public_key("мусор") is None

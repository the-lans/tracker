import pytest

from services.crypto import DecryptionError, decrypt, encrypt


@pytest.mark.parametrize(
    "value",
    ["простой секрет", "", "emoji 🔒 и юникод", "a" * 1000],
)
def test_encrypt_decrypt_round_trip(value: str) -> None:
    token = encrypt(value)
    assert token != value
    assert decrypt(token) == value


def test_decrypt_invalid_token_raises() -> None:
    with pytest.raises(DecryptionError):
        decrypt("not-a-valid-fernet-token")

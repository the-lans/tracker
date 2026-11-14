import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from services.auth_tokens import (
    InvalidSessionTokenError,
    SessionClaims,
    _fernet,
    issue_session_token,
    verify_session_token,
)


class TestSessionVersion:
    """
    Раздел 19.1: версия сессий в токене — по ней отзываются выданные токены.
    """

    @pytest.mark.parametrize("session_version", [0, 3])
    def test_round_trip(self, session_version: int) -> None:
        user_id = uuid.uuid4()

        token = issue_session_token(user_id, session_version=session_version)

        assert verify_session_token(token) == SessionClaims(user_id, session_version)

    def test_token_without_version_is_version_zero(self) -> None:
        """Токены, выданные до появления версии, после обновления действуют."""
        user_id = uuid.uuid4()
        expires_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        payload = json.dumps({"user_id": str(user_id), "expires_at": expires_at})
        token = _fernet().encrypt(payload.encode()).decode()

        assert verify_session_token(token) == SessionClaims(user_id, 0)


def test_verify_rejects_tampered_token() -> None:
    token = issue_session_token(uuid.uuid4())
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    with pytest.raises(InvalidSessionTokenError):
        verify_session_token(tampered)


def test_verify_rejects_garbage_input() -> None:
    with pytest.raises(InvalidSessionTokenError):
        verify_session_token("not-a-real-token")


def test_verify_rejects_expired_token() -> None:
    token = issue_session_token(uuid.uuid4(), ttl=timedelta(seconds=-1))

    with pytest.raises(InvalidSessionTokenError, match="истёк"):
        verify_session_token(token)

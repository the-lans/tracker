import uuid
from datetime import timedelta

import pytest

from services.auth_tokens import (
    InvalidSessionTokenError,
    issue_session_token,
    verify_session_token,
)


def test_issue_and_verify_round_trip() -> None:
    user_id = uuid.uuid4()

    token = issue_session_token(user_id)

    assert verify_session_token(token) == user_id


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

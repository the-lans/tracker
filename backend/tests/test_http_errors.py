"""`clients/http_errors.py` — классы сбоев внешних API (раздел 17.3 ТЗ)."""

from __future__ import annotations

import pytest

from clients.http_errors import HttpFailure, classify_status


class TestClassifyStatus:
    @pytest.mark.parametrize(
        ("status", "failure"),
        [
            (200, None),
            (302, None),
            (408, HttpFailure.TRANSIENT),
            (429, HttpFailure.TRANSIENT),
            (503, HttpFailure.TRANSIENT),
            (401, HttpFailure.ACCESS_DENIED),
            (403, HttpFailure.ACCESS_DENIED),
            (404, HttpFailure.CLIENT_ERROR),
            (422, HttpFailure.CLIENT_ERROR),
        ],
    )
    def test_status(self, status: int, failure: HttpFailure | None) -> None:
        assert classify_status(status) is failure

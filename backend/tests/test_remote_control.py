import pytest

from db.models.enums import RemoteControlStatus
from services.remote_control import MAX_RECONNECT_ATTEMPTS, decide_remote_control_bridge_action


def test_alive_process_needs_no_action() -> None:
    decision = decide_remote_control_bridge_action(
        is_process_alive=True,
        current_reconnect_attempts=0,
    )

    assert decision.should_attempt_reconnect is False
    assert decision.new_status is None


@pytest.mark.parametrize("attempts", range(MAX_RECONNECT_ATTEMPTS))
def test_dead_process_under_attempt_limit_triggers_reconnect(attempts: int) -> None:
    decision = decide_remote_control_bridge_action(
        is_process_alive=False,
        current_reconnect_attempts=attempts,
    )

    assert decision.should_attempt_reconnect is True
    assert decision.new_status is RemoteControlStatus.RECONNECTING


def test_dead_process_after_exhausting_attempts_marks_disconnected() -> None:
    decision = decide_remote_control_bridge_action(
        is_process_alive=False,
        current_reconnect_attempts=MAX_RECONNECT_ATTEMPTS,
    )

    assert decision.should_attempt_reconnect is False
    assert decision.new_status is RemoteControlStatus.DISCONNECTED

from services.session_lifecycle import plan_session_start


def test_first_start_has_no_resume_and_enables_remote_control() -> None:
    plan = plan_session_start(existing_session_id=None)

    assert plan.resume_session_id is None
    assert plan.enable_remote_control is True


def test_restart_after_failed_resumes_existing_session_without_remote_control() -> None:
    plan = plan_session_start(existing_session_id="sess-abc123")

    assert plan.resume_session_id == "sess-abc123"
    assert plan.enable_remote_control is False

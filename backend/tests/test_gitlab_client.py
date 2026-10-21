import httpx
import pytest

from clients.gitlab import GitlabAccessDeniedError, GitlabClient, project_path_from_git_url
from services.errors import ExternalServiceError


@pytest.mark.parametrize(
    ("git_url", "expected"),
    [
        ("git@gitlab.com:group/subgroup/project.git", "group/subgroup/project"),
        ("https://gitlab.com/group/project.git", "group/project"),
        ("https://gitlab.example.com/group/project", "group/project"),
    ],
)
def test_project_path_from_git_url(git_url: str, expected: str) -> None:
    assert project_path_from_git_url(git_url) == expected


def _client_with_handler(handler: httpx.MockTransport) -> GitlabClient:
    http_client = httpx.AsyncClient(transport=handler)
    return GitlabClient(
        base_url="https://gitlab.example.com",
        token="secret-token",
        http_client=http_client,
    )


async def test_get_latest_merge_request_state_returns_most_recent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["PRIVATE-TOKEN"] == "secret-token"
        # request.url.path нормализует %2F обратно в "/" — сырой encoded
        # путь, который реально ушёл в запрос, виден только в raw_path.
        assert request.url.raw_path.startswith(
            b"/api/v4/projects/group%2Fproject/merge_requests",
        )
        return httpx.Response(200, json=[{"state": "merged"}])

    client = _client_with_handler(httpx.MockTransport(handler))

    state = await client.get_latest_merge_request_state(
        project_path="group/project",
        source_branch="feature/RR-00001",
    )

    assert state == "merged"


async def test_get_latest_merge_request_state_returns_none_when_no_mrs() -> None:
    client = _client_with_handler(httpx.MockTransport(lambda request: httpx.Response(200, json=[])))

    state = await client.get_latest_merge_request_state(
        project_path="group/project",
        source_branch="feature/RR-00001",
    )

    assert state is None


async def test_server_error_raises_transient_external_service_error() -> None:
    client = _client_with_handler(
        httpx.MockTransport(lambda request: httpx.Response(503, text="upstream down")),
    )

    with pytest.raises(ExternalServiceError) as exc_info:
        await client.get_latest_merge_request_state(project_path="group/project", source_branch="x")

    assert exc_info.value.is_transient is True


async def test_client_error_raises_permanent_external_service_error() -> None:
    client = _client_with_handler(
        httpx.MockTransport(lambda request: httpx.Response(404, text="not found")),
    )

    with pytest.raises(ExternalServiceError) as exc_info:
        await client.get_latest_merge_request_state(project_path="group/project", source_branch="x")

    assert exc_info.value.is_transient is False


async def test_network_failure_raises_transient_external_service_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("сеть недоступна", request=request)

    client = _client_with_handler(httpx.MockTransport(handler))

    with pytest.raises(ExternalServiceError) as exc_info:
        await client.get_latest_merge_request_state(project_path="group/project", source_branch="x")

    assert exc_info.value.is_transient is True


class TestStatusClassification:
    """Раздел 17.3: какие ответы GitLab временные, какие — постоянные."""

    @pytest.mark.parametrize(
        ("status", "transient"),
        [(408, True), (429, True), (502, True), (404, False), (422, False)],
    )
    async def test_transient_flag(self, status: int, transient: bool) -> None:
        client = _client_with_handler(
            httpx.MockTransport(lambda request: httpx.Response(status, text="ошибка")),
        )

        with pytest.raises(ExternalServiceError) as exc_info:
            await client.get_latest_merge_request_state(project_path="g/p", source_branch="x")

        assert exc_info.value.is_transient is transient
        assert not isinstance(exc_info.value, GitlabAccessDeniedError)

    @pytest.mark.parametrize("status", [401, 403])
    async def test_rejected_token(self, status: int) -> None:
        client = _client_with_handler(
            httpx.MockTransport(lambda request: httpx.Response(status, text="401 Unauthorized")),
        )

        with pytest.raises(GitlabAccessDeniedError) as exc_info:
            await client.get_latest_merge_request_state(project_path="g/p", source_branch="x")

        assert exc_info.value.is_transient is False

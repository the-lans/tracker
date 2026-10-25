"""
Мок Jira REST API и GitLab API для ручного E2E-тестирования
(docs/qa_e2e_manual.md), когда настоящие сервисы не настроены.

Отвечает только на то, что вызывает трекер:

- Jira: `GET /rest/api/2/issue/{key}` и скачивание вложения (раздел 15.6);
- GitLab: `GET /api/v4/projects/{path}/merge_requests?source_branch=…`
  (`sync_gitlab_merge_status`, раздел 16.2).

Служебные эндпоинты для тестировщика:

- `POST /_qa/merge-requests` с JSON `{"source_branch": "...", "state": "merged"}`
  задаёт состояние MR ветки (`opened`/`merged`/`closed`);
- `GET /_qa/requests` — журнал обращений трекера (метод, путь, был ли
  заголовок авторизации; сами токены не сохраняются).

Только стандартная библиотека: `python3 scripts/qa/mock_providers.py --port 8090`.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

DEFAULT_PORT = 8090
JIRA_ISSUE_KEY = "RR-QA-2"
ATTACHMENT_NAME = "requirements.md"
ATTACHMENT_BODY = (
    "# Требования RR-QA-2\n\n"
    "- `percent(value, total)` возвращает долю в процентах, округлённую до 2 знаков.\n"
    "- При `total == 0` — `ValueError` с сообщением «total must not be zero».\n"
).encode()
MERGE_REQUEST_STATES = frozenset({"opened", "merged", "closed"})

_JIRA_ISSUE_PATH = re.compile(r"^/rest/api/2/issue/(?P<key>[^/]+)$")
_JIRA_ATTACHMENT_PATH = re.compile(r"^/secure/attachment/\d+/(?P<name>[^/]+)$")
_GITLAB_MR_PATH = re.compile(r"^/api/v4/projects/(?P<project>[^/]+)/merge_requests$")
_AUTH_HEADERS = ("Authorization", "PRIVATE-TOKEN")


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    method: str
    path: str
    authorized: bool


class MockState:
    """Состояние мока: MR по веткам и журнал обращений, общие для потоков сервера."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._merge_requests: dict[str, str] = {}
        self._requests: list[RecordedRequest] = []

    def record(self, request: RecordedRequest) -> None:
        with self._lock:
            self._requests.append(request)

    def requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(request) for request in self._requests]

    def set_merge_request(self, source_branch: str, state: str) -> None:
        with self._lock:
            self._merge_requests[source_branch] = state

    def merge_request(self, source_branch: str) -> str | None:
        with self._lock:
            return self._merge_requests.get(source_branch)


def _jira_issue(key: str, base_url: str) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": "Функция percent в калькуляторе",
            "description": "Добавить в qa-calc функцию percent по требованиям из вложения.",
            "attachment": [
                {
                    "filename": ATTACHMENT_NAME,
                    "size": len(ATTACHMENT_BODY),
                    "content": f"{base_url}/secure/attachment/1/{ATTACHMENT_NAME}",
                },
            ],
        },
    }


class MockHandler(BaseHTTPRequestHandler):
    server: MockServer

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, path: str) -> None:
        authorized = any(self.headers.get(name) for name in _AUTH_HEADERS)
        self.server.state.record(RecordedRequest(self.command, path, authorized))

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/_qa/requests":
            self._send_json(self.server.state.requests())
            return
        self._record(url.path)
        if match := _JIRA_ISSUE_PATH.match(url.path):
            self._get_jira_issue(unquote(match["key"]))
        elif match := _JIRA_ATTACHMENT_PATH.match(url.path):
            self._get_jira_attachment(unquote(match["name"]))
        elif _GITLAB_MR_PATH.match(url.path):
            self._get_merge_requests(parse_qs(url.query).get("source_branch", [""])[0])
        else:
            self._send_json({"message": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/_qa/merge-requests":
            self._send_json({"message": "not found"}, HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"message": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return
        source_branch = str(body.get("source_branch") or "")
        state = str(body.get("state") or "")
        if not source_branch or state not in MERGE_REQUEST_STATES:
            message = f"нужны source_branch и state из {sorted(MERGE_REQUEST_STATES)}"
            self._send_json({"message": message}, HTTPStatus.BAD_REQUEST)
            return
        self.server.state.set_merge_request(source_branch, state)
        self._send_json({"source_branch": source_branch, "state": state})

    def _get_jira_issue(self, key: str) -> None:
        if key != JIRA_ISSUE_KEY:
            self._send_json({"errorMessages": ["Issue does not exist"]}, HTTPStatus.NOT_FOUND)
            return
        host = self.headers.get("Host") or f"localhost:{self.server.server_port}"
        self._send_json(_jira_issue(key, f"http://{host}"))

    def _get_jira_attachment(self, name: str) -> None:
        if name != ATTACHMENT_NAME:
            self._send_json({"message": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(ATTACHMENT_BODY)

    def _get_merge_requests(self, source_branch: str) -> None:
        state = self.server.state.merge_request(source_branch)
        merge_requests = [] if state is None else [{"iid": 1, "state": state}]
        self._send_json(merge_requests)


class MockServer(ThreadingHTTPServer):
    def __init__(self, port: int) -> None:
        super().__init__(("0.0.0.0", port), MockHandler)  # noqa: S104 — мок в сети стенда
        self.state = MockState()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    port = parser.parse_args().port
    print(f"mock providers on :{port}", flush=True)  # noqa: T201 — вывод CLI
    MockServer(port).serve_forever()


if __name__ == "__main__":
    main()

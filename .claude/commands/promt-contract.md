Write the endpoint contract for the current task from context. Be concise, clear and structured; use lists, not tables. It must be ready to copy-paste into a Jira comment. Write it in Russian.

The contract must include:
- Method and path (e.g. GET /api/v1/...), plus a one-line purpose if needed.
- Path and query params (name, location, type, required, allowed values), or explicitly "Параметров и тела запроса нет".
- Headers and auth — how it works (JWT, x-omp-server, X-Client, etc.), or explicitly "Авторизация не требуется".
- Request body, if any, with a JSON example.
- Success response — HTTP code and JSON example, with each field and its type. If fields depend on record type/variant (discriminated union), describe per variant which fields are relevant and which are null.
- Client-relevant behavior: pagination/limits, idempotency, element order, effect of repeated calls, whether composite entities (bundles etc.) are expanded.
- Errors — all possible 4xx/5xx codes with trigger conditions and exact response body format (or "без тела").

Base everything on the actual implementation (router, schemas, handler), not on assumptions.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.

Act as a senior Python backend and frontend reviewer. Find all significant errors in the code in a single pass, so that later passes only verify fixes instead of finding new issues in already-reviewed code. Do not discuss minor inaccuracies with no functional impact. Write only truly important remarks! Also check against the development rules (CLAUDE.md/AGENTS.md and nearby `.claude/rules/*`), not just the diff code. If there are no significant errors, say so. Do not change code — review only. Do not stop until you have found everything.

## Review scope

Review the current branch's diff against its base. The base is the branch the task branch was created from: if the task, conversation or notes name a related branch (e.g. another task's branch it was forked from), use it; otherwise `origin/main`. At the start of the report, state in one line the chosen base and where it came from. If context suggests several possible bases and you can't choose, ask one question and do not start the review.

In scope: changed lines (committed and uncommitted), direct callers and callees of changed code, their tests. Read other code for understanding, but don't write remarks on it. Exceptions: the change breaks its behavior, or the change widens the set of cases hitting a pre-existing defect — in the second case, mark the remark «существовало до изменения».

Create temporary verification files (trial tests, scripts) only outside the repo. After the pass, make sure `git status` shows the same as before.

## Severity levels

- **Блокер** — loss or duplication of money/data, data corruption, security hole, crash in a working scenario.
- **Важное** — wrong behavior in a real scenario, or violation of a documented project convention (doesn't break functionality, but matters for observability and maintenance — always mention it).
- **Мелкое** — style, taste, inaccuracies with no functional impact and no rule violation. Do not output or count anywhere.

## How to proceed

1. Go through the categories below in order across all changed files and collect candidates.
2. Verify each candidate against the code: is the path reachable in practice, is the case covered by calling code, validation or an existing test. Mark «подтверждено» (concrete scenario: input → wrong result) or «гипотеза» (state what remains to check). Discard candidates that fail verification. Confirm blockers by running something (existing or temporary test) where possible; for them, conclusions from code reading alone are «гипотеза».
3. Check against the code the assumptions from the plan and conversation for this task ("no redelivery happens", "this path is never called"). A refuted assumption is a separate remark if behavior depends on it.
4. Merge duplicates: one cause — one remark, even if it shows up in several places.
5. Sort: first remarks that change the logic or design of the solution, then local fixes; within each, blockers above important.
6. For each remark determine dependencies: which other remarks drop or change if this one is accepted.

## Repeat pass

If the conversation already contains a previous review of this task:
- First check each previous remark and assign a status: «исправлено», «частично», «не исправлено», «ждёт решения» (needs an answer or choice, not a code fix) or «принято как есть» (user agreed to leave it). Do not output or count «принято как есть» anymore.
- Review only lines changed since the previous pass, and work through the remainder from the «Ещё найдено» block.
- In unchanged code, new remarks are allowed only at «блокер» level — with an explanation of why it wasn't found earlier.
- A remark the user rejected or called "not a bug" must not be raised again while the code there hasn't changed.

## Error categories to check

 - **Logic errors** — wrong conditions, off-by-one, inverted logic, mutable default arguments
 - **Project conventions** — violations of CLAUDE.md rules even without direct functional impact: logging that bypasses structlog/`app_logging` (structured fields and context are lost), business logic in `api/` instead of `services/`, not following project structure and naming, violation of the critical rules in CLAUDE.md section 6. Never «мелкое» — the rule is explicitly documented.
 - **Validation and types** — missing None/empty checks, implicit type coercion, trusting external data without validation
 - **Cross-field validator without a guard for already-failed fields** — pydantic `model_validator`/root validators and analogs may run even when per-field validation already failed. If such a hook contains an expensive or external call with a side effect (HTTP to another service, write, send) without an explicit "field errors exist → return immediately" check, the code makes an unnecessary external call on knowingly wrong data and adds a second, often misleading message on top of the already-shown field error
 - **DB work** — SQL injection, missing transactions, N+1 queries, unclosed sessions, missing SELECT FOR UPDATE, .all() without LIMIT
 - **Authentication and authorization** — IDOR, incorrect JWT check, unsafe password comparison, missing permission checks
 - **Integrations** — missing timeout/retry, ignoring HTTP statuses, insecure secret transfer
 - **Exception handling** — swallowed errors, too-broad except, lost traceback on re-raise
 - **Fallback paths after an error** — for every new `try/except` with a fallback, trace whether the fallback transitively calls THE SAME code / same flag check / same resource as the failed main path. Common pattern: function A fails, a "backup" B with a similar name ("direct path", "DB fallback") is called, but B itself re-checks the same condition and hits the same problematic dependency — so there is no real fallback. Check with a separate run "what if the fallback fails exactly the same way", not only its happy path
 - **Race conditions** — check-then-act without locking, shared state without a Lock, non-idempotent handlers
 - **Boundary values** — division by 0, indexing without length check, empty iterables, naive vs aware datetime
 - **State and side effects** — argument mutation, global mutable state, cache without invalidation
 - **Performance** — N+1 without eager load, sync calls in async context, no connection pool
 - **Configuration** — hardcoded secrets, no env-var validation at startup
 - **Serialization** — datetime without isoformat, float precision loss for money, returning an ORM object without serialization. Separately, for cache-aside with serialization (Redis etc.): compare write vs read strictness — if reads validate strictly (Pydantic/schema) but writes store anything, bad DB data passes serialization and only fails on read. Check whether metrics/logs distinguish this case ("cache holds bad data") from a regular miss — if not, mention it even without a ready fix
 - **Payments/billing — transaction boundaries and side effects** (for any payment, billing or money/grant service, regardless of framework and stack — Django, FastAPI+SQLAlchemy, anything):
   - A side effect (event, queue task, webhook, email, etc.) is sent right after exiting the function's local transaction block, not after the REAL commit — check whether the function can be called from inside the caller's already-open transaction (not only directly on its own). If it can, the effect must be deferred until the actual commit of the outermost transaction (Django — `transaction.on_commit(..., robust=True)`; SQLAlchemy — a session hook like `after_commit`/the `session.commit()` event; any other stack — the equivalent "run after commit" mechanism, not a direct call)
   - Config/input validation is placed BEFORE the idempotency check ("already applied" — a flag on the record, a unique key, a dedup table) within one operation — so a redelivery/retry of an already-processed operation fails instead of a silent no-op if the config became invalid between the first and repeat call
   - Lookup of a record for refund/reversal/cancellation uses the current value of a MUTABLE config/setting rather than immutable fields of the record itself (type, metadata saved at creation, etc.) — when the config changes, old records silently become unreachable for cancellation, often without any log line
   - Code reads/saves an entity field AFTER calling a nested function that independently re-reads and saves the same entity (e.g. under its own lock/new query) — the second save/update on the original (stale) object overwrites what the nested function wrote
   - Retry/redelivery AFTER A PARTIAL failure — the operation partially applied (e.g. the credit went through, but the next step in the same function failed), then it's retried or redelivered: check this path specifically, not just "two successful calls in a row with the same input"
   - The same business logic (credit, refund, purchase/payment routing) is duplicated in several places (several payment providers, API versions, delivery channels) — a fix in one branch doesn't guarantee a fix in the others; check each separately
   - An identical or near-identical balance credit/debit function (or other money operation) is copied into a neighboring file of the same domain instead of reusing a shared helper

## Answer format (in Russian)

**Сводка** — diff base and its source; pass number (first or repeat); total remarks found, of which blockers and important; how many are shown in detail.

**Статус прошлых замечаний** — repeat pass only: number, status, one line of explanation. For «ждёт решения», state what answer is needed and from whom.

**Замечания** — at most the 10 most important, in sort order, each as a numbered block strictly in this format:

**№N. Проблема:** [what's wrong, where exactly — file/function/line]
**Уровень:** [блокер / важное] · [подтверждено / гипотеза] · [if needed: существовало до изменения]
**Категория:** [one of the categories above or your own]
**Риск:** [what can go wrong in practice — concrete scenario]
**Решение:** [concrete fix, or if there's no unambiguous fix — what to clarify/check before fixing]
**Зависимости:** [which remarks drop or change if this is accepted; «нет» if independent]

**Ещё найдено** — everything beyond the 10, one line each: level, location (`file:line`), essence. Omit the block if nothing remains.

**Допущения** — only if the plan or conversation had assumptions: one line each marked «подтверждено», «опровергнуто» (and how it was checked) or «не проверяется по коду» (external system behavior or product rule — say who/where can answer).

**Покрытие** — one or two lines: which categories were checked and clean, which are not applicable to this diff.

**Вердикт** — one line: «можно мержить» / «нужен ещё проход после исправлений» / «нужна переделка решения», plus the number of open blockers.

Do not propose the solution as "full correct code" — only the direction and essence of the fix, enough to understand the approach. Format the text for easy reading and structure it.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.

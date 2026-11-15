Investigate a support ticket "paid but item not received" or "payment problems" following the chain below and give a structured answer. The ticket text (nickname, server, account UID, payment provider ID, what was bought, when, screenshots) was already sent above in the conversation — take it from there; if there are several, use the most recent one (closest above).

If there is no parseable ticket text above (no account_uid/item/time), do not invent data and do not proceed. Stop and ask for the ticket text.

Use only MCP integrations actually available in this session. Discover shared resource maps through `tracker-knowledge` when available. Use configured MCP authentication or credentials explicitly provided for the task. For an access file supplied through a repository template, first check `./access_task.txt` in the task working directory. Also check an explicitly supplied path or an uploaded `access_task.txt` in the task artifacts directory. Check that the file exists before reading it. Do not assume a workstation path, a knowledge directory, or external tools exist. If access is missing, identify the specific integration or file needed. Never print credentials.
You may connect to the DB directly; if the safety classifier blocks it, use Django admin. Also use the Aghanim dashboard for cross-checking.

UI labels, statuses and log message strings below are quoted verbatim in Russian as they appear in the admin/logs — search by them as-is.

## Mandatory evidence before any refund decision

Make a refund recommendation, including "no refund needed" or "no compensation needed", only after all three sources have been checked and reconciled for the same purchase:
1. **Aghanim:** the actual, current payment status, matched transaction(s), amount/currency and purchase time, including any existing refund or reversal.
2. **Game delivery:** whether the item or currency was actually delivered to the correct game account. Confirm this with game-side records, delivery API/admin data or reliable delivery logs tied to this order. An internal shop flag or Storage row alone does not establish game delivery.
3. **Internal shop:** our matched order, its status/error, grant flag, Storage/transfer records and any recorded compensation or recovery.

For each source, record the result and supporting link or evidence. Match the account, product, time and amount; resolve ambiguous matches and contradictions before deciding. Missing access, an unavailable source, an incomplete search, expired logs or an unverified match means **unknown**, not "no payment" or "no grant". Never infer non-delivery solely from an empty log search or the internal shop's error status.

If any required source is missing, incomplete, contradictory or cannot be verified, the verdict is **«Недостаточно данных для решения о рефанде»**. List the confirmed facts, the exact missing checks and who or what is needed to complete them. Do not recommend a refund, refuse a refund, recommend a re-grant or declare compensation unnecessary until this gate is satisfied. Continue collecting the missing evidence or escalate; do not stop after a finding from only one or two sources.

## Verification chain (go through every step in order, skip none)

1. **Parse the ticket.** Extract account_uid, server, item name, exact purchase time (convert to UTC — ticket time is usually the player's local time), amount, and the provider payment ID from the ticket (Mercado Pago etc.) — this is the payment provider's ID, not Aghanim's; it almost never matches our `external_order_id` or the Aghanim transaction ID. Keep it only as context for the player/screenshots, not as a search key — search orders and transactions by account_uid + item + time/amount.

2. **Find our order** (DB or Django admin shop.riorise.com/admin):
   `/admin/billing/order/?q=<account_uid>`
   Find the order by item and nearest time. Record: `Статус`, `Описание ошибки` (code), `Грант применён`, `Дата подтверждения лимита`, link to the order, link to "Товар магазина" (needed in steps 4 and 7 as store_item_id).

3. **Check whether the item was actually granted despite status "Ошибка"** (common case: an old manual compensation not reflected in the order status):
   `/admin/storage/storageitem/?order__id__exact=<order_id>`
   If a record exists, check `Дата перевода` and confirm actual game-side delivery for the matched order and account. Record delivered / not delivered / unknown with evidence. Treat the shop grant flag and Storage row as internal shop evidence; do not substitute them for a game-side delivery check. Complete the Aghanim and internal shop checks before making any compensation/refund conclusion, even if an item appears to have been delivered.

4. **If the error code is the purchase limit (`PURCHASE_LIMIT_REACHED`), dig into the limit:**
   - Item: `/admin/catalog/storeitem/<store_item_id>/change/` → section "Лимиты и флаги"
   - Item change history: `/admin/catalog/storeitem/<store_item_id>/history/` — who changed the limit and when
   - Character id: `/admin/player/character/?q=<account_uid>`
   - Player counter: `/admin/catalog/accountstoreitemlimit/?store_item__id__exact=<store_item_id>&character__id__exact=<character_id>` — `Куплено`/`Зарезервировано`/`Дата обновления`
   If the error code is different, investigate by that code (`PREREQUISITE_NOT_PURCHASED`, `BILLING_PRODUCT_NOT_FOUND`, etc.) — don't force-fit the limit.

   **If the error code is `RIO_GRANT_UNCERTAIN` (Google Play / App Store, RR-16894)** — the order was removed from auto-retry because RIO may already have been credited: RIO is committed to master_db separately from the "grant applied" flag, and the RC journal rolls back together with the grant, so the admin doesn't show the credit. **Do not press "Recover" on the order until you've checked logs** — otherwise RIO is doubled. Check via Grafana (logs kept ~7 days; after that there's nothing to check — escalate to development):
   - `{env="production", service="shop-service"} "изменение rio_coins" shop_order_id:="<order_id>"` — take `account_uid` and `balance_after`;
   - `{env="production", service="shop-service"} "rio_coins обновлён" account_uid:="<account_uid>"` — a record with the same `balance_after` close in time confirms the credit was committed.
   Both events present → record this as evidence of committed game credit, then complete and reconcile the Aghanim and internal shop checks before deciding. Missing events are not proof that credit was absent. If game credit cannot be verified, return «Недостаточно данных для решения о рефанде» and escalate; do not recommend "Recover" or refund solely because logs are empty. The same hint is in the `manual_check_hint` field of log `order.rio_grant_uncertain_held_for_manual_check` (level error, Sentry).

5. **Confirm the actual charge in the Aghanim dashboard** (primary source of truth about money — our `Order.status` may be wrong):
   `https://dashboard.aghanim.com/company/com_eFdUoVuAOjV/gm_eFgipFCEwgP/transactions?search_string=<account_uid>` (searching via URL is faster than typing into "Search...").
   It's an SPA — after navigation wait 2–3 s (`browser_wait_for`) before the snapshot, otherwise the page is empty/loading; do not mistake that for "no transactions". If the session expired and you see a login form, log in via company SSO (Google, thelans@apexplay.games), as in Sentry.
   Find the transaction by item and time/amount. The Aghanim transaction is usually 10–30 s **earlier** than our order's `created_at` (webhook delay) — use this as a guide if several rows match the amount. Provider transaction status:
   - `Succeeded` → confirms a successful charge; it does not justify a refund by itself. Verify current refund/reversal status and complete the other two required sources
   - `Rejected`/`Declined`/`Abandoned`/`Expired` → record the unsuccessful attempt; check all matching attempts and the other two required sources before deciding whether a refund is needed
   If one of our orders has several Aghanim transactions (payment retries, different order_ids in "Внешний ID заказа" on our side), list all of them with statuses separately — assess each transaction independently against all three required sources; multiple attempts do not imply that every transaction needs a refund.

6. **Grafana logs — auxiliary, not the main source.** Via MCP (`mcp__grafana__query_loki_logs`, datasource `vm-logs`), query like `{env="production", service="shop-service"} "<order_id or account_uid>"`. Empty results by account_uid are normal (often not indexed); do not treat that as proof processing didn't happen — rely on admin + Aghanim.

7. **Assess scale** — whether others were affected by the same cause (same item + same error code):
   `/admin/billing/order/?store_item__id__exact=<store_item_id>&status__exact=3&all=`
   (`status__exact=3` = FAILED). Columns "Предметы в хранилище"/"Платежи кассы" (0/1) in the list immediately show who was already compensated, without opening each order. If you find other affected players, list their account_uids.

## Verdict rule

Apply these outcomes only after the mandatory three-source evidence gate above is satisfied:
- Aghanim confirms a successful charge that has not already been refunded/reversed, actual game delivery is confirmed absent, and the internal shop records for the matched purchase have been checked and reconciled → **рефанд** (recommendation under the current team policy, subject to human confirmation).
- Aghanim confirms no charge for the relevant purchase/attempts, and game delivery plus internal shop data have also been checked and reconciled → **рефанд не нужен**; explain the confirmed payment outcome.
- Actual game delivery is confirmed, with the Aghanim payment and internal shop records also verified and reconciled → **компенсация не нужна**; explain where the item/currency was delivered. A Storage row alone is not enough for this conclusion.
- Any required evidence is missing, incomplete, ambiguous or contradictory → **недостаточно данных для решения о рефанде**; state the missing facts and escalate as needed, without a refund/denial/re-grant recommendation.
- For `RIO_GRANT_UNCERTAIN`, additionally perform step 4. If game credit cannot be established, including because required logs are no longer available, escalate to development with the insufficient-data verdict; do not press "Recover" or recommend a refund on that basis alone.

## Answer format (in Russian) — a two-column markdown table: "Пункт проверки" | "Результат"

Required rows, in this order (values with direct admin/Aghanim links where applicable):

| Пункт проверки | Результат |
|---|---|
| Account UID | link/value |
| Никнейм / сервер | |
| Товар | |
| Время покупки | player local time = UTC time |
| ID платежа из тикета | value (reference only; payment provider, not Aghanim; usually matches nothing below; not a search key) |
| Заказ (наш ID) | id + link to `/admin/billing/order/<id>/change/` |
| Статус заказа | |
| Код ошибки | |
| Грант во внутреннем магазине / Storage | shop grant flag, Storage/transfer records and links; keep separate from game-side delivery |
| Фактическая выдача в игру | delivered / not delivered / unknown + game-side evidence or the exact missing check |
| Лимит покупки сработал? | yes/no + if yes — which one, when set/reset |
| Транзакция(и) Aghanim | txn id + link + status (Succeeded/Rejected/...) + amount + time; if several attempts — all, each with its status |
| Деньги списаны? | confirmed yes / confirmed no / unknown; include existing refund/reversal status |
| Полнота обязательных данных | Aghanim: verified/missing; game delivery: verified/missing; internal shop: verified/missing; unresolved contradictions |
| Логи Grafana | what was found, or honestly "не проверялись отдельно / не показатель" |
| Вердикт | рефанд / рефанд не нужен / компенсация не нужна / недостаточно данных для решения о рефанде — per the evidence gate and verdict rule |
| Масштаб | how many other account_uids are affected by the same cause (if checked) |

Do not grant or refund anything yourself — only gather facts and give a recommendation in the table. A human confirms the compensation decision.

## Short Slack message example (use as a template at the end of the answer)

Use the following completed-check example only when all three required sources are verified:

> Проверил <никнейм> (`<account_uid>`). Aghanim: <подтверждённый статус платежа и ссылка>. Выдача в игру: <подтверждённый результат и источник>. Внутренний магазин: заказ `<order_id>` — `<статус>`, `<код ошибки>` (<ссылка>). Все три источника сверены. Рекомендация: <рефанд / рефанд не нужен / компенсация не нужна> — <обоснование>. Решение подтверждает ответственный сотрудник.

If the evidence gate is not satisfied, use this instead:

> По <никнейм> (`<account_uid>`) недостаточно данных для решения о рефанде. Подтверждено: <факты и источники>. Не хватает: <Aghanim / выдача в игру / внутренний магазин — что именно не проверено>. Нужно: <конкретная проверка или доступ>. Рекомендация о компенсации пока не сформирована.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.

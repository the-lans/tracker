/** Формат ключа задачи Jira: как проверяет backend (`services/jira_import.py`). */
const KEY = "[A-Za-z][A-Za-z0-9_]*-\\d+";
const URL_KEY_PATTERNS = [
  // https://example.atlassian.net/browse/RR-20274?focusedId=1
  new RegExp(`/browse/(${KEY})`),
  // https://example.atlassian.net/jira/software/projects/RR/boards/1?selectedIssue=RR-20274
  new RegExp(`[?&]selectedIssue=(${KEY})`),
  new RegExp(`[?&]issueKey=(${KEY})`),
];

/**
 * Поле «Ключ задачи Jira» (раздел 15.6): вставленная ссылка на задачу заменяется
 * её ключом — `https://…/browse/RR-20274` → `RR-20274`. Всё, что не похоже на
 * ссылку, возвращается как есть, чтобы не мешать вводу ключа по буквам; ссылка
 * без ключа тоже остаётся, и пользователь видит, что ключ не найден.
 */
export function extractJiraKey(text: string): string {
  const trimmed = text.trim();
  if (!/^https?:\/\//i.test(trimmed)) return text;
  for (const pattern of URL_KEY_PATTERNS) {
    const match = pattern.exec(trimmed);
    if (match) return match[1]!.toUpperCase();
  }
  return text;
}

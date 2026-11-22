import { describe, expect, it } from "vitest";
import { extractJiraKey } from "@/lib/jiraKey";

describe("extractJiraKey", () => {
  it.each([
    ["https://riorise.atlassian.net/browse/RR-20274", "RR-20274"],
    ["  https://riorise.atlassian.net/browse/RR-20274  ", "RR-20274"],
    ["https://riorise.atlassian.net/browse/RR-20274?qwe=123", "RR-20274"],
    ["https://riorise.atlassian.net/browse/RR-20274?focusedId=10&page=comments", "RR-20274"],
    ["https://riorise.atlassian.net/browse/RR-20274#comment-5", "RR-20274"],
    ["http://jira.example.com:8080/browse/proj_x-7", "PROJ_X-7"],
    ["https://riorise.atlassian.net/jira/software/projects/RR/boards/1?selectedIssue=RR-20274", "RR-20274"],
    ["https://jira.example.com/issues/?issueKey=RR-5", "RR-5"],
  ])("ссылка %s → %s", (input, expected) => {
    expect(extractJiraKey(input)).toBe(expected);
  });

  it.each([
    "",
    "RR-",
    "RR-20274",
    "rr-20274",
    " RR-20274 ",
    "https://",
    "https://riorise.atlassian.net/browse/R",
    "https://riorise.atlassian.net/jira/dashboards/1",
    "задача RR-1 в https://x.atlassian.net/browse/RR-1",
  ])("«%s» остаётся как есть", (input) => {
    expect(extractJiraKey(input)).toBe(input);
  });
});

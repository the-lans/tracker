import { screen } from "@testing-library/react";
import { expect } from "vitest";
import { TaskJiraLink } from "@/components/tasks/TaskJiraLink";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

test("адрес ссылки берётся из настроек Jira", async ({ api }) => {
  api.respond("GET /jira/server", { jira_url: "https://jira.example.com/" });
  renderWithProviders(<TaskJiraLink task={makeTask({ code: "RR-15592" })} />);
  const link = await screen.findByRole("link", { name: "Открыть задачу в Jira" });
  expect(link).toHaveAttribute("href", "https://jira.example.com/browse/RR-15592");
  expect(link).toHaveAttribute("target", "_blank");
});

test("ссылка импортированной задачи имеет приоритет", ({ api }) => {
  api.respond("GET /jira/server", { jira_url: "https://jira.example.com" });
  renderWithProviders(<TaskJiraLink task={makeTask({ jira_issue_url: "https://other.example.com/browse/X-1" })} />);
  expect(screen.getByRole("link")).toHaveAttribute("href", "https://other.example.com/browse/X-1");
});

test("у локальной задачи ссылка не отображается", ({ api }) => {
  api.respond("GET /jira/server", { jira_url: "https://jira.example.com" });
  renderWithProviders(<TaskJiraLink task={makeTask({ code: "local" })} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});

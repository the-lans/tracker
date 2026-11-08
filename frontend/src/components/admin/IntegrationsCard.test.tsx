import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { IntegrationsCard } from "@/components/admin/IntegrationsCard";
import type { Integrations } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PATH = "/system-settings/integrations";

function renderCard(api: MockedApi, integrations: Integrations) {
  api.respond(`GET ${PATH}`, integrations);
  api.respond(`PUT ${PATH}`, integrations);
  return renderWithProviders(<IntegrationsCard />);
}

describe("IntegrationsCard", () => {
  test("полей GitLab нет — доступ к API задаётся в учётных данных Git", async ({ api }) => {
    renderCard(api, { jira_url: null });

    await screen.findByLabelText("Адрес Jira");

    expect(screen.queryByLabelText(/GitLab/)).not.toBeInTheDocument();
  });

  test.for([
    { typed: "", jira_url: null },
    { typed: " https://example.atlassian.net ", jira_url: "https://example.atlassian.net" },
  ])("адрес Jira «$typed» → $jira_url", async ({ typed, jira_url }, { api }) => {
    const { user } = renderCard(api, { jira_url: null });
    const field = await screen.findByLabelText("Адрес Jira");

    if (typed) await user.type(field, typed);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([{ method: "PUT", path: PATH, body: { jira_url } }]);
  });
});

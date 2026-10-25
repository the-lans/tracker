import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { IntegrationsCard } from "@/components/admin/IntegrationsCard";
import type { Integrations } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PATH = "/system-settings/integrations";

const configured: Integrations = {
  gitlab_url: "https://gitlab.example.com",
  gitlab_token_set: true,
  jira_url: "https://example.atlassian.net",
};

function renderCard(api: MockedApi, integrations: Integrations = configured) {
  api.respond(`GET ${PATH}`, integrations);
  api.respond(`PUT ${PATH}`, integrations);
  return renderWithProviders(<IntegrationsCard />);
}

describe("IntegrationsCard", () => {
  test("сохранённый токен не показывается", async ({ api }) => {
    renderCard(api);

    const field = await screen.findByLabelText("Токен API GitLab");

    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("placeholder", "Сохранён — введите новый, чтобы заменить");
  });

  test.for([
    { typed: "", token: null },
    { typed: "glpat-test-new", token: "glpat-test-new" },
  ])("поле токена «$typed» → gitlab_token: $token", async ({ typed, token }, { api }) => {
    const { user } = renderCard(api);
    const field = await screen.findByLabelText("Токен API GitLab");

    if (typed) await user.type(field, typed);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(api.mutations()).toEqual([
      {
        method: "PUT",
        path: PATH,
        body: { gitlab_url: configured.gitlab_url, gitlab_token: token, jira_url: configured.jira_url },
      },
    ]);
    await expect.poll(() => (field as HTMLInputElement).value).toBe("");
  });

  test("«Удалить токен GitLab» отправляет пустую строку", async ({ api }) => {
    const { user } = renderCard(api);

    await user.click(await screen.findByRole("button", { name: "Удалить токен GitLab" }));

    expect(api.mutations()[0].body).toMatchObject({ gitlab_token: "" });
  });

  test("без сохранённого токена удалять нечего, пустые адреса уходят null", async ({ api }) => {
    const { user } = renderCard(api, { gitlab_url: null, gitlab_token_set: false, jira_url: null });

    await screen.findByLabelText("Адрес GitLab");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(screen.queryByRole("button", { name: "Удалить токен GitLab" })).not.toBeInTheDocument();
    expect(api.mutations()[0].body).toEqual({ gitlab_url: null, gitlab_token: null, jira_url: null });
  });
});

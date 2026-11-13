import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import type { MockedApi } from "@/test/apiMock";
import { makeRepository } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";
import type { Repository } from "@/lib/types";
import { RepositoryForm } from "./RepositoryForm";

const GITLAB_CREDENTIAL = {
  id: "cred1",
  name: "GitLab RioRise",
  host: "gitlab.example.com",
  kind: "https_token",
  username: "oauth2",
};

function renderForm(api: MockedApi, repository?: Repository) {
  api.respond("GET /git-credentials", [GITLAB_CREDENTIAL]);
  const saved = vi.fn();
  const view = renderWithProviders(
    <RepositoryForm repository={repository} onSaved={saved} onCancel={() => {}} />,
  );
  return { ...view, saved };
}

const branchField = () => screen.getByLabelText("Ветка по умолчанию");
const fromServer = () => screen.getByRole("button", { name: /С сервера/ });

describe("RepositoryForm", () => {
  test.for(["Название", "Git URL", "Ветка по умолчанию"])("«%s» отмечено обязательным", (field, { api }) => {
    renderForm(api);

    expect(screen.getByText(field, { selector: "label" })).toHaveAttribute("data-required");
  });

  test("сохраняет выбранный доступ вместо приватного ключа", async ({ api }) => {
    const { user, saved } = renderForm(api);

    await user.type(screen.getByLabelText("Название"), "repo");
    await user.type(screen.getByLabelText("Git URL"), "https://gitlab.example.com/repo.git");
    await user.click(screen.getByRole("combobox", { name: "Учётные данные Git" }));
    await user.click(await screen.findByRole("option", { name: "GitLab RioRise · gitlab.example.com" }));
    await user.click(screen.getByRole("button", { name: "Создать" }));

    expect(api.mutations()).toEqual([
      {
        method: "POST",
        path: "/repositories",
        body: {
          name: "repo",
          git_url: "https://gitlab.example.com/repo.git",
          default_branch: "master",
          git_credential_id: "cred1",
          default_template_id: null,
        },
      },
    ]);
    expect(screen.queryByLabelText(/Deploy-ключ/)).not.toBeInTheDocument();
    await vi.waitFor(() => expect(saved).toHaveBeenCalled());
  });

  describe("ветка по умолчанию", () => {
    test.for([
      { repository: undefined, shown: "master" },
      { repository: makeRepository({ default_branch: "develop" }), shown: "develop" },
    ])("в форме — «$shown»", ({ repository, shown }, { api }) => {
      renderForm(api, repository);

      expect(branchField()).toHaveValue(shown);
    });

    test("введённая ветка уходит при правке", async ({ api }) => {
      api.respond("PATCH /repositories/r1", makeRepository({ default_branch: "trunk" }));
      const { user } = renderForm(api, makeRepository());

      await user.clear(branchField());
      await user.type(branchField(), " trunk ");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));

      expect(api.mutations().at(-1)).toMatchObject({
        method: "PATCH",
        body: { default_branch: "trunk" },
      });
    });

    test("без ветки сохранить нельзя", async ({ api }) => {
      const { user } = renderForm(api, makeRepository());

      await user.clear(branchField());

      expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    });

    test("кнопка берёт ветку с git-сервера по адресу и доступу из формы", async ({ api }) => {
      api.respond("POST /repositories/default-branch", { default_branch: "main" });
      const { user } = renderForm(api, makeRepository());

      await user.click(fromServer());

      await vi.waitFor(() => expect(branchField()).toHaveValue("main"));
      expect(api.mutations().at(-1)).toEqual({
        method: "POST",
        path: "/repositories/default-branch",
        body: { git_url: "git@gitlab.example.com:shop/web-app.git", git_credential_id: "cred1" },
      });
    });

    test("ошибка git-сервера — уведомление, ветка не меняется", async ({ api, toasts }) => {
      api.respond("POST /repositories/default-branch", {
        error: { status: 422, message: "Git отказал в доступе: проверьте URL, ключ или токен" },
      });
      const { user } = renderForm(api, makeRepository({ default_branch: "develop" }));

      await user.click(fromServer());

      await expect
        .poll(() => toasts.error.mock.calls)
        .toEqual([["Git отказал в доступе: проверьте URL, ключ или токен"]]);
      expect(branchField()).toHaveValue("develop");
    });

    test("без Git URL кнопка недоступна", ({ api }) => {
      renderForm(api);

      expect(fromServer()).toBeDisabled();
    });
  });
});

import { screen, within } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskEnvVariableRow } from "@/components/tasks/TaskEnvVariableRow";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const VARIABLES_PATH = "/tasks/t1/env-variables";
const SECRET = "sk-test-123456";
const MASK = "••••••";

function renderRow({ readOnly = false } = {}) {
  return renderWithProviders(
    <TaskEnvVariableRow taskId="t1" variable={{ id: "v1", key: "API_TOKEN" }} readOnly={readOnly} />,
  );
}

describe("TaskEnvVariableRow", () => {
  describe("значение скрыто (правило 8)", () => {
    test("по умолчанию — маска, значение не запрашивается", ({ api }) => {
      renderRow();

      expect(screen.getByText(MASK)).toBeInTheDocument();
      expect(api.requests).toEqual([]);
    });

    test("«Показать» запрашивает и показывает значение", async ({ api }) => {
      api.respond(`GET ${VARIABLES_PATH}/v1/reveal`, { value: SECRET });
      const { user } = renderRow();

      await user.click(screen.getByRole("button", { name: "Показать" }));

      expect(await screen.findByText(SECRET)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Показать" })).not.toBeInTheDocument();
    });

    test("ошибка показа оставляет маску", async ({ api, toasts }) => {
      api.respond(`GET ${VARIABLES_PATH}/v1/reveal`, { error: { status: 403, message: "Нет доступа к задаче" } });
      const { user } = renderRow();

      await user.click(screen.getByRole("button", { name: "Показать" }));

      await expect.poll(() => toasts.error.mock.calls).toEqual([["Нет доступа к задаче"]]);
      expect(screen.getByText(MASK)).toBeInTheDocument();
    });
  });

  describe("правка", () => {
    test("новое значение сохраняется и снова скрывается", async ({ api }) => {
      api.respond(`GET ${VARIABLES_PATH}/v1/reveal`, { value: SECRET });
      const { user } = renderRow();
      await user.click(screen.getByRole("button", { name: "Показать" }));
      await screen.findByText(SECRET);

      await user.click(screen.getByRole("button", { name: "Изменить API_TOKEN" }));
      await user.type(screen.getByLabelText("Новое значение API_TOKEN"), "sk-test-new");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));

      expect(api.mutations()).toEqual([
        { method: "PATCH", path: `${VARIABLES_PATH}/v1`, body: { value: "sk-test-new" } },
      ]);
      expect(await screen.findByText(MASK)).toBeInTheDocument();
      expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    });

    test("отмена не оставляет введённый секрет в поле", async ({ api }) => {
      const { user } = renderRow();

      await user.click(screen.getByRole("button", { name: "Изменить API_TOKEN" }));
      await user.type(screen.getByLabelText("Новое значение API_TOKEN"), "sk-test-typo");
      await user.click(screen.getByRole("button", { name: "Отмена" }));
      await user.click(screen.getByRole("button", { name: "Изменить API_TOKEN" }));

      expect(screen.getByLabelText("Новое значение API_TOKEN")).toHaveValue("");
      expect(api.mutations()).toEqual([]);
    });

    test("удаление — после подтверждения", async ({ api }) => {
      const { user } = renderRow();

      await user.click(screen.getByRole("button", { name: "Удалить API_TOKEN" }));
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));

      expect(api.mutations()).toEqual([{ method: "DELETE", path: `${VARIABLES_PATH}/v1`, body: undefined }]);
    });

    test("только чтение — без правки и удаления, показать можно", () => {
      renderRow({ readOnly: true });

      expect(screen.queryByRole("button", { name: "Изменить API_TOKEN" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Удалить API_TOKEN" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Показать" })).toBeEnabled();
    });
  });
});

import { screen, within } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TaskDetailsDialog } from "@/components/tasks/TaskDetailsDialog";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const ARTIFACTS = [
  { path: "brief.md", size: 2048, modified_at: "2026-11-10T10:00:00Z" },
  {
    path: "docs/схема.png",
    size: 1_048_576,
    modified_at: "2026-11-11T10:00:00Z",
  },
];

function renderDialog(
  api: { respond: (key: string, body: unknown) => void },
  overrides: Parameters<typeof makeTask>[0] = {},
  onOpenChange = vi.fn(),
) {
  const task = makeTask({ id: "t1", ...overrides });
  api.respond("GET /tasks/t1/artifacts", ARTIFACTS);
  return {
    ...renderWithProviders(
      <TaskDetailsDialog task={task} open onOpenChange={onOpenChange} />,
    ),
    onOpenChange,
  };
}

describe("TaskDetailsDialog", () => {
  test("название, код, описание текстом, ссылки и файлы", async ({ api }) => {
    renderDialog(api, {
      code: "RR-1",
      title: "Сводка по профилю игрока",
      description: "Первая строка\nВторая строка",
      jira_issue_url: "https://example.atlassian.net/browse/RR-1",
      guide_url: "https://example.com/guide",
    });

    expect(
      screen.getByRole("dialog", { name: "Сводка по профилю игрока" }),
    ).toBeInTheDocument();
    expect(screen.getByText("RR-1")).toBeInTheDocument();
    expect(screen.getByText(/Первая строка/)).toHaveClass(
      "whitespace-pre-wrap",
    );
    expect(
      screen.getByRole("link", { name: "Открыть в Jira" }),
    ).toHaveAttribute("href", "https://example.atlassian.net/browse/RR-1");
    expect(screen.getByRole("link", { name: "Открыть гайд" })).toHaveAttribute(
      "href",
      "https://example.com/guide",
    );
    expect(await screen.findByText("brief.md")).toBeInTheDocument();
    expect(screen.getByText("docs/схема.png")).toBeInTheDocument();
  });

  test("описание из Jira — отрисованным", async ({ api }) => {
    renderDialog(api, {
      description: "h2. Контекст",
      description_html: "<h2>Контекст</h2><p>Нужна <b>сводка</b></p>",
    });

    expect(
      await screen.findByRole("heading", { name: "Контекст" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("h2. Контекст")).not.toBeInTheDocument();
  });

  test("файлы только скачиваются: удаления нет", async ({ api }) => {
    renderDialog(api);

    const row = (await screen.findByText("brief.md")).closest(
      "div.flex",
    ) as HTMLElement;
    expect(
      within(row).getByRole("button", { name: "Скачать brief.md" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Удалить/ }),
    ).not.toBeInTheDocument();
  });

  test("без ссылок и файлов — пояснения", async ({ api }) => {
    api.respond("GET /tasks/t1/artifacts", []);
    renderWithProviders(
      <TaskDetailsDialog
        task={makeTask({ id: "t1" })}
        open
        onOpenChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Ссылок нет")).toBeInTheDocument();
    expect(await screen.findByText("Файлов нет")).toBeInTheDocument();
  });

  test("файлы удалены по сроку хранения — причина", async ({ api }) => {
    api.respond("GET /tasks/t1/artifacts", []);
    renderWithProviders(
      <TaskDetailsDialog
        task={makeTask({
          id: "t1",
          artifacts_cleaned_at: "2026-09-01T10:00:00Z",
        })}
        open
        onOpenChange={vi.fn()}
      />,
    );

    expect(await screen.findByText("Артефакты удалены")).toBeInTheDocument();
  });

  test("крестик закрывает окно", async ({ api }) => {
    const { user, onOpenChange } = renderDialog(api);

    await user.click(screen.getByRole("button", { name: "Закрыть" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  describe("правка описания", () => {
    test.for([
      { status: TaskStatus.NEW, editable: true },
      { status: TaskStatus.DEFINED, editable: true },
      { status: TaskStatus.IN_PROGRESS, editable: false },
      { status: TaskStatus.DONE, editable: false },
    ])("статус $status → «Изменить» есть: $editable", ({ status, editable }, { api }) => {
      renderDialog(api, { status, description: "d" });

      expect(screen.queryByRole("button", { name: "Изменить" }) !== null).toBe(editable);
    });

    test("новый текст сохраняется, окно возвращается к просмотру", async ({ api, toasts }) => {
      api.respond("PATCH /tasks/t1", makeTask({ id: "t1", description: "Новый текст", description_html: null }));
      const { user } = renderDialog(api, {
        description: "Старый текст",
        description_html: "<p>Старый текст</p>",
      });

      await user.click(screen.getByRole("button", { name: "Изменить" }));
      const field = screen.getByRole("textbox", { name: "Описание задачи" });
      expect(field).toHaveValue("Старый текст");
      expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
      await user.clear(field);
      await user.type(field, "Новый текст");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));

      await expect.poll(() => api.mutations()[0]?.body).toEqual({ description: "Новый текст" });
      expect(api.mutations()[0]?.path).toBe("/tasks/t1");
      await expect.poll(() => toasts.success).toHaveBeenCalledWith("Описание сохранено");
      expect(screen.queryByRole("textbox", { name: "Описание задачи" })).not.toBeInTheDocument();
    });

    test("пробелы и переводы строк по краям не отправляются, а одни они — не изменение", async ({ api }) => {
      api.respond("PATCH /tasks/t1", makeTask({ id: "t1", description: "Новый текст" }));
      const { user } = renderDialog(api, { description: "Старый текст" });

      await user.click(screen.getByRole("button", { name: "Изменить" }));
      const field = screen.getByRole("textbox", { name: "Описание задачи" });
      await user.type(field, "  {Enter}{Enter}");
      await user.type(field, "{Control>}{Home}{/Control}{Enter}  ");
      expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();

      await user.clear(field);
      await user.type(field, "  {Enter}Новый текст  {Enter}{Enter}  ");
      await user.click(screen.getByRole("button", { name: "Сохранить" }));

      await expect.poll(() => api.mutations()[0]?.body).toEqual({ description: "Новый текст" });
    });

    test("Ctrl+Enter сохраняет, ошибка сервера показывается и правка остаётся", async ({ api, toasts }) => {
      api.respond("PATCH /tasks/t1", { error: { status: 422, message: "Поля задачи можно менять только до запуска" } });
      const { user } = renderDialog(api, { description: "Старый" });

      await user.click(screen.getByRole("button", { name: "Изменить" }));
      await user.type(screen.getByRole("textbox", { name: "Описание задачи" }), " плюс{Control>}{Enter}{/Control}");

      await expect
        .poll(() => toasts.error)
        .toHaveBeenCalledWith("Поля задачи можно менять только до запуска");
      expect(screen.getByRole("textbox", { name: "Описание задачи" })).toHaveValue("Старый плюс");
    });

    test("Escape отменяет правку и не закрывает окно, второй Escape закрывает окно", async ({ api }) => {
      const { user, onOpenChange } = renderDialog(api, { description: "Старый" });

      await user.click(screen.getByRole("button", { name: "Изменить" }));
      await user.type(screen.getByRole("textbox", { name: "Описание задачи" }), " правка{Escape}");

      expect(screen.queryByRole("textbox", { name: "Описание задачи" })).not.toBeInTheDocument();
      expect(onOpenChange).not.toHaveBeenCalled();
      await user.keyboard("{Escape}");
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    test("«Отмена» закрывает редактор без сохранения", async ({ api }) => {
      const { user } = renderDialog(api, { description: "Старый" });

      await user.click(screen.getByRole("button", { name: "Изменить" }));
      await user.type(screen.getByRole("textbox", { name: "Описание задачи" }), " правка");
      await user.click(screen.getByRole("button", { name: "Отмена" }));

      expect(screen.queryByRole("textbox", { name: "Описание задачи" })).not.toBeInTheDocument();
      expect(screen.getByText("Старый")).toBeInTheDocument();
      expect(api.mutations()).toHaveLength(0);
    });
  });
});

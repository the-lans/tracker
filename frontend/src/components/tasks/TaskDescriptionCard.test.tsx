import { screen } from "@testing-library/react";
import { afterEach, describe, expect } from "vitest";
import { TaskDescriptionCard } from "@/components/tasks/TaskDescriptionCard";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("TaskDescriptionCard", () => {
  test("описание из Jira показывается отрисованным", async ({ api }) => {
    api.respond("GET /tasks/t1/artifacts", []);
    renderWithProviders(
      <TaskDescriptionCard
        task={makeTask({
          description: "h2. Контекст",
          description_html:
            "<h2>Контекст</h2><p>Нужна <b>сводка</b></p><script>1</script>",
        })}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Контекст" }),
    ).toBeInTheDocument();
    expect(screen.getByText("сводка")).toBeInTheDocument();
    expect(screen.queryByText("h2. Контекст")).not.toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  test("без HTML — обычный текст с переносами", () => {
    renderWithProviders(
      <TaskDescriptionCard
        task={makeTask({ description: "Первая строка\nВторая строка" })}
      />,
    );

    expect(screen.getByText(/Первая строка/)).toHaveClass(
      "whitespace-pre-wrap",
    );
  });

  test("кнопка обновляет описание из Jira и подгружает HTML", async ({
    api,
    toasts,
  }) => {
    api.respond(
      "POST /jira/tasks/t1/description",
      makeTask({ description_html: "<p>x</p>" }),
    );
    const { user } = renderWithProviders(
      <TaskDescriptionCard
        task={makeTask({
          description: "d",
          jira_issue_url: "https://example.atlassian.net/browse/RR-1",
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Обновить из Jira" }));

    await expect
      .poll(() => api.mutations()[0]?.path)
      .toBe("/jira/tasks/t1/description");
    await expect
      .poll(() => toasts.success)
      .toHaveBeenCalledWith("Описание обновлено из Jira");
  });

  test("ошибка обновления показывается", async ({ api, toasts }) => {
    api.respond("POST /jira/tasks/t1/description", {
      error: {
        status: 409,
        message: "Описание задачи отличается от описания в Jira",
      },
    });
    const { user } = renderWithProviders(
      <TaskDescriptionCard
        task={makeTask({
          description: "d",
          jira_issue_url: "https://example.atlassian.net/browse/RR-1",
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Обновить из Jira" }));

    await expect
      .poll(() => toasts.error)
      .toHaveBeenCalledWith("Описание задачи отличается от описания в Jira");
  });

  test("без ссылки на Jira кнопки обновления нет", () => {
    renderWithProviders(
      <TaskDescriptionCard task={makeTask({ description: "d" })} />,
    );

    expect(
      screen.queryByRole("button", { name: "Обновить из Jira" }),
    ).not.toBeInTheDocument();
  });

  test("ссылка на задачу Jira остаётся", () => {
    renderWithProviders(
      <TaskDescriptionCard
        task={makeTask({
          description: "d",
          jira_issue_url: "https://example.atlassian.net/browse/RR-1",
        })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Открыть в Jira" }),
    ).toBeInTheDocument();
  });

  describe("длинное описание", () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    afterEach(() => {
      if (original) Object.defineProperty(HTMLElement.prototype, "scrollHeight", original);
    });
    const setHeight = (height: number) =>
      Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get: () => height });

    test("обрезается, «Открыть полностью» открывает отдельное окно", async ({ api }) => {
      api.respond("GET /tasks/t1/artifacts", []);
      setHeight(900);
      const { user } = renderWithProviders(
        <TaskDescriptionCard task={makeTask({ description: "Очень длинное описание" })} />,
      );

      expect(screen.getByTestId("clamped-fade")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Открыть полностью" }));

      expect(await screen.findByRole("dialog")).toBeInTheDocument();
    });

    test("короткое описание — без кнопки", () => {
      setHeight(80);
      renderWithProviders(<TaskDescriptionCard task={makeTask({ description: "Коротко" })} />);

      expect(screen.queryByRole("button", { name: "Открыть полностью" })).not.toBeInTheDocument();
    });
  });
});

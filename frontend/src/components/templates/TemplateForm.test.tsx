import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { TemplateForm } from "@/components/templates/TemplateForm";
import {
  TEMPLATE_FILE_MAX_BYTES,
  TEMPLATE_FILE_NOT_TEXT,
  TEMPLATE_FILE_TOO_LARGE,
} from "@/lib/templateFiles";
import type { Template } from "@/lib/types";
import type { MockedApi } from "@/test/apiMock";
import { makeTemplate } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const RULES = "# Правила\nПиши тесты на каждую правку.";

function renderForm(api: MockedApi, template?: Template) {
  api.respond("POST /templates", makeTemplate());
  api.respond("PATCH /templates/tpl1", makeTemplate());
  return renderWithProviders(<TemplateForm template={template} onSaved={vi.fn()} onCancel={vi.fn()} />);
}

function savedFiles(api: MockedApi) {
  return (api.mutations().find((request) => request.path.startsWith("/templates"))?.body as Template)
    .files;
}

describe("TemplateForm", () => {
  describe("содержимое из файла", () => {
    test("текст файла уходит при создании, пустой путь — имя файла", async ({ api }) => {
      const { user } = renderForm(api);
      await user.type(screen.getByLabelText("Название"), "Python-сервис");
      await user.clear(screen.getByLabelText("Путь файла"));

      await user.click(screen.getByRole("button", { name: "Из файла" }));
      expect(screen.getByRole("button", { name: "Из файла" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.queryByLabelText("Содержимое файла")).not.toBeInTheDocument();
      await user.upload(screen.getByLabelText("Файл для без пути"), new File([RULES], "CLAUDE.md"));
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(screen.getByLabelText("Путь файла")).toHaveValue("CLAUDE.md");
      expect(screen.getByText(/^CLAUDE\.md · \d+ Б$/)).toBeInTheDocument();
      await vi.waitFor(() => expect(savedFiles(api)).toEqual({ "CLAUDE.md": RULES }));
    });

    test("введённый путь не меняется на имя файла", async ({ api }) => {
      const { user } = renderForm(api);
      await user.type(screen.getByLabelText("Название"), "Ревью");
      const path = screen.getByLabelText("Путь файла");
      await user.clear(path);
      await user.type(path, ".claude/commands/review.md");

      await user.click(screen.getByRole("button", { name: "Из файла" }));
      await user.upload(
        screen.getByLabelText("Файл для .claude/commands/review.md"),
        new File(["Проверь diff"], "my-review.md"),
      );
      await user.click(screen.getByRole("button", { name: "Создать" }));

      await vi.waitFor(() =>
        expect(savedFiles(api)).toEqual({ ".claude/commands/review.md": "Проверь diff" }),
      );
    });

    test("после снятия галки загруженный текст правится в поле", async ({ api }) => {
      const { user } = renderForm(api);
      await user.type(screen.getByLabelText("Название"), "Python-сервис");

      await user.click(screen.getByRole("button", { name: "Из файла" }));
      await user.upload(screen.getByLabelText("Файл для CLAUDE.md"), new File([RULES], "rules.md"));
      await user.click(screen.getByRole("button", { name: "Из файла" }));
      const content = screen.getByLabelText("Содержимое файла");
      expect(content).toHaveValue(RULES);
      await user.type(content, "\nБез магических чисел.");
      await user.click(screen.getByRole("button", { name: "Из файла" }));

      expect(screen.getByText(/^Текст из поля · \d+ Б$/)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Создать" }));
      await vi.waitFor(() =>
        expect(savedFiles(api)).toEqual({ "CLAUDE.md": `${RULES}\nБез магических чисел.` }),
      );
    });

    test.for([
      { title: "больше 1 МБ", file: new File(["a".repeat(TEMPLATE_FILE_MAX_BYTES + 1)], "big.md"), error: TEMPLATE_FILE_TOO_LARGE },
      { title: "не UTF-8", file: new File([new Uint8Array([0x89, 0x50, 0xff, 0xfe])], "logo.png"), error: TEMPLATE_FILE_NOT_TEXT },
      { title: "с символом NUL", file: new File(["a\u0000b"], "dump.bin"), error: TEMPLATE_FILE_NOT_TEXT },
    ])("файл $title — ошибка под полем, прежний текст остаётся", async ({ file, error }, { api }) => {
      const { user } = renderForm(api, makeTemplate({ files: { "CLAUDE.md": RULES } }));

      await user.click(screen.getByRole("button", { name: "Из файла" }));
      const input = screen.getByLabelText("Файл для CLAUDE.md");
      await user.upload(input, file);

      await vi.waitFor(() => expect(input).toHaveAccessibleDescription(error));
      expect(screen.getByRole("alert")).toHaveTextContent(error);
      await user.click(screen.getByRole("button", { name: "Сохранить" }));
      await vi.waitFor(() => expect(savedFiles(api)).toEqual({ "CLAUDE.md": RULES }));
    });

    test("снятие галки убирает ошибку", async ({ api }) => {
      const { user } = renderForm(api);

      await user.click(screen.getByRole("button", { name: "Из файла" }));
      await user.upload(screen.getByLabelText("Файл для CLAUDE.md"), new File(["a\u0000"], "x.bin"));
      await screen.findByRole("alert");
      await user.click(screen.getByRole("button", { name: "Из файла" }));

      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("редактирование", () => {
    test("сохранённый шаблон открывается с вводом текстом", ({ api }) => {
      renderForm(api, makeTemplate({ files: { "CLAUDE.md": RULES } }));

      expect(screen.getByRole("button", { name: "Из файла" })).toHaveAttribute("aria-pressed", "false");
      expect(screen.getByLabelText("Содержимое файла")).toHaveValue(RULES);
    });

    test("ошибка остаётся у своей строки после удаления соседней", async ({ api }) => {
      const { user } = renderForm(api, makeTemplate({ files: { "CLAUDE.md": RULES, "AGENTS.md": "x" } }));

      await user.click(screen.getAllByRole("button", { name: "Из файла" })[1]);
      await user.upload(screen.getByLabelText("Файл для AGENTS.md"), new File(["a\u0000"], "x.bin"));
      await screen.findByRole("alert");
      await user.click(screen.getByRole("button", { name: "Убрать файл CLAUDE.md" }));

      expect(screen.getByLabelText("Файл для AGENTS.md")).toHaveAccessibleDescription(TEMPLATE_FILE_NOT_TEXT);
    });
  });
});

import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, vi } from "vitest";
import { TaskArtifactRow } from "@/components/tasks/TaskArtifactRow";
import type { TaskArtifact } from "@/lib/types";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const artifact = (path: string): TaskArtifact => ({
  path,
  size: 10,
  modified_at: "2026-11-10T10:00:00Z",
});

describe("TaskArtifactRow", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "blob:x"),
        revokeObjectURL: vi.fn(),
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  test.for(["notes.md", "схема.png", "report.pdf", "app.log"])(
    "%s — есть кнопка просмотра",
    (path) => {
      renderWithProviders(
        <TaskArtifactRow taskId="t1" artifact={artifact(path)} />,
      );

      expect(
        screen.getByRole("button", { name: `Просмотреть ${path}` }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: `Скачать ${path}` }),
      ).toBeInTheDocument();
    },
  );

  test.for(["archive.zip", "table.xlsx", "Makefile"])(
    "%s — просмотра нет, скачать можно",
    (path) => {
      renderWithProviders(
        <TaskArtifactRow taskId="t1" artifact={artifact(path)} />,
      );

      expect(
        screen.queryByRole("button", { name: /Просмотреть/ }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: `Скачать ${path}` }),
      ).toBeInTheDocument();
    },
  );

  test("кнопка просмотра открывает окно с файлом, закрытие — крестиком", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({
            ok: true,
            status: 200,
            blob: async () => new Blob(["содержимое файла"]),
          }) as unknown as Response,
      ),
    );
    const { user } = renderWithProviders(
      <TaskArtifactRow taskId="t1" artifact={artifact("a.log")} />,
    );

    await user.click(screen.getByRole("button", { name: "Просмотреть a.log" }));
    expect(await screen.findByText("содержимое файла")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("только просмотр: удаления нет, просмотр есть", () => {
    renderWithProviders(
      <TaskArtifactRow taskId="t1" artifact={artifact("a.log")} readOnly />,
    );

    expect(
      screen.queryByRole("button", { name: /Удалить/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Просмотреть a.log" }),
    ).toBeInTheDocument();
  });
});

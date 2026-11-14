import { screen } from "@testing-library/react";
import { describe, expect } from "vitest";
import { TaskArtifactsCard } from "@/components/tasks/TaskArtifactsCard";
import { TaskStatus } from "@/lib/types";
import { makeTask } from "@/test/factories";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

describe("TaskArtifactsCard", () => {
  test.for([
    { cleanedAt: null, title: "Файлов нет", hint: /Загрузите файлы для агента/ },
    { cleanedAt: "2026-09-01T10:00:00Z", title: "Артефакты удалены", hint: /по сроку хранения/ },
  ])("пустой список, удалены $cleanedAt → «$title»", async ({ cleanedAt, title, hint }, { api }) => {
    const task = makeTask({ status: TaskStatus.ARCHIVED, artifacts_cleaned_at: cleanedAt });
    api.respond(`GET /tasks/${task.id}/artifacts`, []);

    renderWithProviders(<TaskArtifactsCard task={task} />);

    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  test("файлы, загруженные после удаления, показываются списком", async ({ api }) => {
    const task = makeTask({ status: TaskStatus.ARCHIVED, artifacts_cleaned_at: "2026-09-01T10:00:00Z" });
    api.respond(`GET /tasks/${task.id}/artifacts`, [
      { path: "report.md", size: 10, modified_at: "2026-09-02T10:00:00Z" },
    ]);

    renderWithProviders(<TaskArtifactsCard task={task} />);

    expect(await screen.findByText("report.md")).toBeInTheDocument();
    expect(screen.queryByText("Артефакты удалены")).not.toBeInTheDocument();
  });
});

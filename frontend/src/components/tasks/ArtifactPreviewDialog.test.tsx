import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, vi } from "vitest";
import { ArtifactPreviewDialog } from "@/components/tasks/ArtifactPreviewDialog";
import {
  TEXT_PREVIEW_MAX_BYTES,
  type PreviewKind,
} from "@/lib/artifactPreview";
import type { TaskArtifact } from "@/lib/types";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

/** Ответ с `Blob` окружения jsdom: у Node-овского `Response` другой класс `Blob`. */
const fileResponse = (blob: Blob) =>
  ({ ok: true, status: 200, blob: async () => blob }) as unknown as Response;

const ARTIFACT = (path: string, size = 100): TaskArtifact => ({
  path,
  size,
  modified_at: "2026-11-10T10:00:00Z",
});

/** Файл по адресу артефакта: настоящее содержимое, а не JSON подмены API. */
function serveFile(content: BlobPart, type = "text/plain") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => fileResponse(new Blob([content], { type }))),
  );
}

function renderDialog(
  artifact: TaskArtifact,
  kind: PreviewKind,
  onOpenChange = vi.fn(),
) {
  return {
    ...renderWithProviders(
      <ArtifactPreviewDialog
        taskId="t1"
        artifact={artifact}
        kind={kind}
        open
        onOpenChange={onOpenChange}
      />,
    ),
    onOpenChange,
  };
}

describe("ArtifactPreviewDialog", () => {
  beforeEach(() => {
    let counter = 0;
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => `blob:test/${++counter}`),
        revokeObjectURL: vi.fn(),
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  test("текст показывается как есть, с размером и датой", async () => {
    serveFile("первая строка\nвторая <b>строка</b>");
    renderDialog(ARTIFACT("log/app.log", 2048), "text");

    expect(await screen.findByText(/первая строка/)).toBeInTheDocument();
    expect(screen.getByText(/<b>строка<\/b>/)).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "log/app.log" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/2 КБ/)).toBeInTheDocument();
  });

  test("markdown — с оформлением", async () => {
    serveFile("# Заголовок\n\nТекст с **жирным**");
    renderDialog(ARTIFACT("notes.md"), "markdown");

    expect(await screen.findByText("Заголовок")).toBeInTheDocument();
    expect(screen.queryByText(/# Заголовок/)).not.toBeInTheDocument();
  });

  test("большой текст — показано начало и пометка", async () => {
    serveFile("а".repeat(TEXT_PREVIEW_MAX_BYTES + 10));
    renderDialog(ARTIFACT("big.log", TEXT_PREVIEW_MAX_BYTES + 10), "text");

    expect(await screen.findByText(/Показаны первые/)).toBeInTheDocument();
  });

  test("не текст — просмотр недоступен", async () => {
    serveFile(new Uint8Array([104, 105, 0, 1, 2]));
    renderDialog(ARTIFACT("data.log"), "text");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Файл не текстовый",
    );
  });

  test("картинка — тегом img с временным адресом", async () => {
    serveFile(new Uint8Array([137, 80, 78, 71]), "image/png");
    renderDialog(ARTIFACT("схема.png"), "image");

    const image = await screen.findByRole("img", { name: "схема.png" });
    expect(image).toHaveAttribute("src", expect.stringMatching(/^blob:/));
  });

  test("PDF — во встроенном просмотрщике", async () => {
    serveFile(new Uint8Array([37, 80, 68, 70]), "application/pdf");
    const { container } = renderDialog(ARTIFACT("doc.pdf"), "pdf");

    await screen.findByTitle("doc.pdf");
    expect(container.ownerDocument.querySelector("iframe")).toHaveAttribute(
      "src",
      expect.stringMatching(/^blob:/),
    );
  });

  test("сбой загрузки — сообщение", async ({ api }) => {
    api.respond("GET /tasks/t1/artifacts/a.log", {
      error: { status: 500, message: "сбой" },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          ({
            ok: false,
            status: 500,
            headers: new Headers(),
            text: async () => "",
            json: async () => ({}),
          }) as unknown as Response,
      ),
    );
    renderDialog(ARTIFACT("a.log"), "text");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Не удалось открыть файл",
    );
  });

  test("есть «Скачать» и «Открыть в новой вкладке», крестик закрывает", async () => {
    serveFile("текст");
    const { user, onOpenChange } = renderDialog(ARTIFACT("a.log"), "text");

    expect(
      await screen.findByRole("link", { name: /Открыть в новой вкладке/ }),
    ).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("button", { name: /Скачать/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Закрыть" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

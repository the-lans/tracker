import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { CollapsibleText } from "@/components/tasks/CollapsibleText";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PREVIEW_LENGTH = 320;
const longText = `${"а".repeat(PREVIEW_LENGTH)}ХВОСТ`;

const expandButton = () => screen.queryByRole("button", { name: "Показать полностью →" });

describe("CollapsibleText", () => {
  test.for([
    { length: PREVIEW_LENGTH, collapsible: false },
    { length: PREVIEW_LENGTH + 1, collapsible: true },
  ])("текст длиной $length сворачивается: $collapsible", ({ length, collapsible }) => {
    renderWithProviders(<CollapsibleText text={"б".repeat(length)} />);

    expect(expandButton() !== null).toBe(collapsible);
  });

  test("длинный текст свёрнут, разворачивается и сворачивается обратно", async () => {
    const { user } = renderWithProviders(<CollapsibleText text={longText} />);

    expect(screen.queryByText(/ХВОСТ/)).not.toBeInTheDocument();
    await user.click(expandButton()!);
    expect(screen.getByText(/ХВОСТ/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Свернуть" }));
    expect(screen.queryByText(/ХВОСТ/)).not.toBeInTheDocument();
  });

  test("текст, выросший после показа, тоже сворачивается", () => {
    const { rerender } = renderWithProviders(<CollapsibleText text="(пусто)" />);

    rerender(<CollapsibleText text={longText} />);

    expect(expandButton()).toBeInTheDocument();
    expect(screen.queryByText(/ХВОСТ/)).not.toBeInTheDocument();
  });

  test("текст, который ещё генерируется, показан целиком", () => {
    renderWithProviders(<CollapsibleText text={longText} live />);

    expect(screen.getByText(/ХВОСТ/)).toBeInTheDocument();
  });

  test("копируется полный текст, а не превью", async ({ toasts }) => {
    const { user } = renderWithProviders(<CollapsibleText text={longText} />);

    await user.click(screen.getByRole("button", { name: "Копировать" }));

    await expect.poll(() => navigator.clipboard.readText()).toBe(longText);
    await expect.poll(() => toasts.success.mock.calls).toEqual([["Скопировано"]]);
  });

  test("скачивается полный текст под заданным именем", async () => {
    const createUrl = vi.fn((blob: Blob) => (void blob, "blob:test"));
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("script-output.txt");
    });
    const { user } = renderWithProviders(<CollapsibleText text={longText} filename="script-output.txt" />);

    await user.click(screen.getByRole("button", { name: "Скачать" }));

    expect(click).toHaveBeenCalledOnce();
    expect(await createUrl.mock.calls[0][0].text()).toBe(longText);
    click.mockRestore();
  });
});

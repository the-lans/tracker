import { screen } from "@testing-library/react";
import { describe, expect, vi } from "vitest";
import { CollapsibleText } from "@/components/tasks/CollapsibleText";
import { test } from "@/test/fixtures";
import { renderWithProviders } from "@/test/renderWithProviders";

const PREVIEW_LENGTH = 320;
const longText = `${"а".repeat(PREVIEW_LENGTH)}ХВОСТ`;

const EXPAND = { name: "Показать полностью →" };

describe("CollapsibleText", () => {
  test.for([
    { length: PREVIEW_LENGTH, collapsible: false },
    { length: PREVIEW_LENGTH + 1, collapsible: true },
  ])("текст длиной $length сворачивается: $collapsible", ({ length, collapsible }) => {
    renderWithProviders(<CollapsibleText text={"б".repeat(length)} />);

    expect(screen.queryByRole("button", EXPAND) !== null).toBe(collapsible);
  });

  test("длинный текст свёрнут, разворачивается и сворачивается обратно", async () => {
    const { user } = renderWithProviders(<CollapsibleText text={longText} />);

    expect(screen.queryByText(/ХВОСТ/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", EXPAND));
    expect(screen.getByText(/ХВОСТ/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Свернуть" }));
    expect(screen.queryByText(/ХВОСТ/)).not.toBeInTheDocument();
  });

  test("текст, выросший после показа, тоже сворачивается", () => {
    const { rerender } = renderWithProviders(<CollapsibleText text="(пусто)" />);

    rerender(<CollapsibleText text={longText} />);

    expect(screen.getByRole("button", EXPAND)).toBeInTheDocument();
    expect(screen.queryByText(/ХВОСТ/)).not.toBeInTheDocument();
  });

  test.for([{ prop: "live" }, { prop: "defaultExpanded" }])("с $prop текст показан целиком", ({ prop }) => {
    renderWithProviders(<CollapsibleText text={longText} {...{ [prop]: true }} />);

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

  describe("блок кода в превью", () => {
    const fenced = (lines: number) =>
      `Вот код:\n\`\`\`python\n${Array.from({ length: lines }, (_, i) => `value_${i} = ${i}`).join("\n")}\n\`\`\`\nПосле блока.`;
    const visible = () => screen.getByText(/Вот код:/).textContent ?? "";

    test("предел внутри блока кода — блок показан до закрывающей ограды, многоточие под ним", () => {
      renderWithProviders(<CollapsibleText text={fenced(25)} />);

      expect(visible()).toContain("value_24");
      expect(visible()).not.toContain("После блока");
      expect(visible().endsWith("```\n…")).toBe(true);
    });

    test("слишком длинный блок кода обрезается и закрывается своей оградой", () => {
      renderWithProviders(<CollapsibleText text={fenced(300)} />);

      expect(visible()).not.toContain("value_299");
      expect(visible().endsWith("```\n…")).toBe(true);
      expect((visible().match(/```/g) ?? []).length).toBe(2);
    });

    test("после разворачивания виден весь текст блока", async () => {
      const { user } = renderWithProviders(<CollapsibleText text={fenced(300)} />);

      await user.click(screen.getByRole("button", EXPAND));

      expect(visible()).toContain("value_299");
      expect(visible()).toContain("После блока");
    });
  });
});

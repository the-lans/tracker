import { describe, expect, it } from "vitest";
import { CODE_PREVIEW_MAX, collapsedPreview, previewOf } from "@/lib/textPreview";

const LIMIT = 40;

describe("previewOf", () => {
  it("короткий текст возвращается целиком", () => {
    expect(previewOf("коротко", LIMIT)).toBe("коротко");
  });

  it("обычный текст режется по пределу", () => {
    const text = "а".repeat(100);
    expect(previewOf(text, LIMIT)).toBe("а".repeat(LIMIT));
  });

  it("предел внутри блока кода — превью доходит до закрывающей ограды", () => {
    const code = "```python\nprint(1)\nprint(2)\nprint(3)\nprint(4)\n```";
    const text = `Вот код:\n${code}\nИ ещё абзац после блока кода.`;

    const preview = previewOf(text, LIMIT);

    expect(preview).toBe(`Вот код:\n${code}`);
    expect(preview.split("```").length - 1).toBe(2);
  });

  it("предел после закрытого блока — обычная обрезка", () => {
    const text = `\`\`\`js\nx\n\`\`\`\n${"б".repeat(100)}`;

    expect(previewOf(text, LIMIT)).toBe(text.slice(0, LIMIT));
  });

  it("незакрытый блок кода — обрыв перед его началом", () => {
    const text = `Вступление\n\n\`\`\`python\n${"x = 1\n".repeat(30)}`;

    expect(previewOf(text, LIMIT)).toBe("Вступление");
  });

  it("незакрытый блок в самом начале — обычная обрезка", () => {
    const text = `\`\`\`python\n${"x = 1\n".repeat(30)}`;

    expect(previewOf(text, LIMIT)).toBe(text.slice(0, LIMIT));
  });

  it("то, что отрисовка не считает оградой, блоком кода не считается", () => {
    const text = `Текст\n~~~\n${"y\n".repeat(30)}~~~\n\`\`\`\`md\n${"z\n".repeat(30)}`;

    expect(previewOf(text, LIMIT)).toBe(text.slice(0, LIMIT));
  });

  it("огромный текст без блоков кода не разбирается целиком", () => {
    const text = "строка\n".repeat(500_000);

    const started = performance.now();
    const preview = previewOf(text);

    expect(preview).toBe(text.slice(0, 320));
    expect(performance.now() - started).toBeLessThan(50);
  });

  it("слишком длинный блок кода обрезается по строке и закрывается своей оградой", () => {
    const code = Array.from({ length: 200 }, (_, i) => `value_${i} = compute(${i})`).join("\n");
    const text = `Вот код:\n\`\`\`python\n${code}\n\`\`\`\nХвост`;

    const preview = previewOf(text);

    expect(preview.length).toBeLessThanOrEqual(CODE_PREVIEW_MAX + 4);
    expect(preview.startsWith("Вот код:\n```python\nvalue_0")).toBe(true);
    expect(preview.endsWith("\n```")).toBe(true);
    expect(preview).not.toContain("value_199");
    expect(preview.split("\n").at(-2)).toMatch(/^value_\d+ = compute\(\d+\)$/);
    expect(collapsedPreview(text).endsWith("```\n…")).toBe(true);
  });

  it("блок чуть длиннее предела превью, но короче CODE_PREVIEW_MAX — показывается целиком", () => {
    const code = Array.from({ length: 15 }, (_, i) => `value_${i} = compute(${i})`).join("\n");
    const text = `\`\`\`python\n${code}\n\`\`\`\n${"абзац ".repeat(50)}`;

    expect(previewOf(text).endsWith("```")).toBe(true);
    expect(previewOf(text)).toContain("value_14");
  });
});

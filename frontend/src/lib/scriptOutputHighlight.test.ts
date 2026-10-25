import { describe, expect, it } from "vitest";
import { highlightScriptOutput } from "@/lib/scriptOutputHighlight";

const toneOf = (line: string) => highlightScriptOutput(line)[0].tone;

describe("highlightScriptOutput", () => {
  it.each([
    ["tests/test_export.py::test_csv FAILED", "error"],
    ["Traceback (most recent call last):", "error"],
    ["E   AssertionError: 3 != 4", "error"],
    ["ValueError: bad code", "error"],
    ["DeprecationWarning: use new API", "warning"],
    ["===== 5 passed in 0.12s =====", "success"],
    ["✓ build", "success"],
    ["===== 5 passed, 0 failed in 0.12s =====", "success"],
    ["===== 1 failed, 5 passed in 0.31s =====", "error"],
    ["Build failed, cleanup done", "error"],
    ["Found 0 errors", "plain"],
    ["✔ No errors found", "success"],
    ["eslint: no errors, no warnings", "plain"],
    ["All checks passed! (no errors)", "success"],
    ["1 warning in 0.3s", "warning"],
    ["Found 2 errors", "error"],
    ["collected 5 items", "plain"],
  ])("%s → %s", (line, tone) => {
    expect(toneOf(line)).toBe(tone);
  });

  it("пути, строки и числа в обычной строке", () => {
    const [line] = highlightScriptOutput('read "data.csv" from src/reports/export.py in 12 ms');

    expect(line.tokens.filter((token) => token.kind !== "text")).toEqual([
      { kind: "string", text: '"data.csv"' },
      { kind: "path", text: "src/reports/export.py" },
      { kind: "number", text: "12" },
    ]);
  });

  it("строки сохраняются по одной, текст не теряется", () => {
    const text = "a\n\nb/c.py 1";

    const lines = highlightScriptOutput(text);

    expect(lines).toHaveLength(3);
    expect(lines.map((line) => line.tokens.map((token) => token.text).join("")).join("\n")).toBe(text);
  });
});

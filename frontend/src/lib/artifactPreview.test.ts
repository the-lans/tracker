import { describe, expect, test } from "vitest";
import {
  canOpenInNewTab,
  previewKindOf,
  previewMimeOf,
  previewSizeLimit,
} from "@/lib/artifactPreview";

describe("previewKindOf", () => {
  test.for([
    ["схема.png", "image"],
    ["docs/Фото.JPG", "image"],
    ["logo.svg", "image"],
    ["report.pdf", "pdf"],
    ["notes.md", "markdown"],
    ["README.MARKDOWN", "markdown"],
    ["log/app.log", "text"],
    ["config.yaml", "text"],
    ["page.html", "text"],
    ["data.csv", "text"],
    ["archive.zip", null],
    ["table.xlsx", null],
    ["Makefile", null],
    [".gitignore", null],
    ["noext.", null],
  ] as const)("%s → %s", ([path, kind]) => {
    expect(previewKindOf(path)).toBe(kind);
  });
});

describe("previewMimeOf", () => {
  test.for([
    ["a.png", "image/png"],
    ["a.JPG", "image/jpeg"],
    ["a.svg", "image/svg+xml"],
    ["a.pdf", "application/pdf"],
    ["a.log", "text/plain;charset=utf-8"],
  ] as const)("%s → %s", ([path, mime]) => {
    expect(previewMimeOf(path)).toBe(mime);
  });
});

describe("canOpenInNewTab", () => {
  test.for([
    ["logo.svg", false],
    ["LOGO.SVG", false],
    ["a.png", true],
    ["a.pdf", true],
    ["a.html", true],
    ["a.md", true],
  ] as const)("%s → %s", ([path, allowed]) => {
    expect(canOpenInNewTab(path)).toBe(allowed);
  });
});

describe("previewSizeLimit", () => {
  test("у картинок и PDF предел выше, чем у текста", () => {
    expect(previewSizeLimit("image")).toBe(previewSizeLimit("pdf"));
    expect(previewSizeLimit("image")).toBeGreaterThan(previewSizeLimit("text"));
    expect(previewSizeLimit("markdown")).toBe(previewSizeLimit("text"));
  });
});

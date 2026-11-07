import { describe, expect, test } from "vitest";
import {
  readTemplateFile,
  TEMPLATE_FILE_MAX_BYTES,
  TEMPLATE_FILE_NOT_TEXT,
  TEMPLATE_FILE_TOO_LARGE,
} from "@/lib/templateFiles";

function fileOf(parts: BlobPart[], name = "CLAUDE.md"): File {
  return new File(parts, name, { type: "text/markdown" });
}

describe("readTemplateFile", () => {
  test.for([
    { title: "текст с кириллицей", parts: ["# Правила\nПиши тесты"], content: "# Правила\nПиши тесты" },
    { title: "пустой файл", parts: [], content: "" },
    { title: "ровно предельный размер", parts: ["a".repeat(TEMPLATE_FILE_MAX_BYTES)], content: "a".repeat(TEMPLATE_FILE_MAX_BYTES) },
  ])("принимает: $title", async ({ parts, content }) => {
    const file = fileOf(parts);

    expect(await readTemplateFile(file)).toEqual({ ok: true, content, name: "CLAUDE.md", size: file.size });
  });

  test.for([
    { title: "на байт больше предела", parts: ["a".repeat(TEMPLATE_FILE_MAX_BYTES + 1)], error: TEMPLATE_FILE_TOO_LARGE },
    { title: "не UTF-8", parts: [new Uint8Array([0x89, 0x50, 0xff, 0xfe])], error: TEMPLATE_FILE_NOT_TEXT },
    { title: "символ NUL", parts: ["text\u0000more"], error: TEMPLATE_FILE_NOT_TEXT },
  ])("отклоняет: $title", async ({ parts, error }) => {
    expect(await readTemplateFile(fileOf(parts))).toEqual({ ok: false, error });
  });
});

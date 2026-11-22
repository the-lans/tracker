import { describe, expect, it } from "vitest";
import { highlightCode, parseInline, parseMarkdown } from "@/lib/agentMarkdown";

describe("parseInline", () => {
  it("сохраняет скобки внутри адреса markdown-ссылки", () => {
    expect(parseInline("[Документация](https://example.com/a_(b))")).toEqual([
      { kind: "link", text: "Документация", href: "https://example.com/a_(b)" },
    ]);
  });
  it("не превращает обрезанную ссылку в превью в неправильный адрес", () => {
    expect(parseInline("Открыть https://example.com/unfinished…")).toEqual([
      { kind: "text", text: "Открыть https://example.com/unfinished…" },
    ]);
  });
  it.each([
    ["просто текст", [{ kind: "text", text: "просто текст" }]],
    [
      "Готово: **3 файла** изменено",
      [
        { kind: "text", text: "Готово: " },
        { kind: "bold", text: "3 файла" },
        { kind: "text", text: " изменено" },
      ],
    ],
    [
      "Запусти `make check`",
      [
        { kind: "text", text: "Запусти " },
        { kind: "code", text: "make check" },
      ],
    ],
    ["`a**b**c`", [{ kind: "code", text: "a**b**c" }]],
    ["**незакрытый жирный", [{ kind: "text", text: "**незакрытый жирный" }]],
    ["**`calc.py`**", [{ kind: "code", text: "calc.py", bold: true }]],
    [
      "**Файл `calc.py` готов**",
      [
        { kind: "bold", text: "Файл " },
        { kind: "code", text: "calc.py", bold: true },
        { kind: "bold", text: " готов" },
      ],
    ],
    ["<b>не HTML</b>", [{ kind: "text", text: "<b>не HTML</b>" }]],
  ])("%s", (text, expected) => {
    expect(parseInline(text)).toEqual(expected);
  });
});

describe("parseMarkdown", () => {
  it("заголовки, абзацы и списки разделяются на блоки", () => {
    const blocks = parseMarkdown("## План\nСделаю так:\n\n1. Кнопка\n2. Тесты\n- проверить CSV");

    expect(blocks.map((block) => block.kind)).toEqual(["heading", "paragraph", "list", "list"]);
    expect(blocks[0]).toMatchObject({ level: 2 });
    expect(blocks[2]).toMatchObject({ ordered: true, items: [[{ text: "Кнопка" }], [{ text: "Тесты" }]] });
    expect(blocks[3]).toMatchObject({ ordered: false });
  });

  it("соседние строки абзаца склеиваются, пустая строка его закрывает", () => {
    expect(parseMarkdown("первая\nвторая\n\nтретья")).toEqual([
      { kind: "paragraph", parts: [{ kind: "text", text: "первая\nвторая" }] },
      { kind: "paragraph", parts: [{ kind: "text", text: "третья" }] },
    ]);
  });

  it.each([
    ["```Python\ndef f():\n    return 1\n```\nпосле", "python", "def f():\n    return 1", 2],
    ["```\nнезакрытый блок\n# не заголовок", "", "незакрытый блок\n# не заголовок", 1],
  ])("блок кода: %j", (text, language, code, count) => {
    const blocks = parseMarkdown(text);

    expect(blocks).toHaveLength(count);
    expect(blocks[0]).toEqual({ kind: "code", language, code });
  });

  it.each([
    ["**Итог:** готово", "paragraph"],
    ["##### пятый уровень", "paragraph"],
    ["* пункт", "list"],
  ])("«%s» → %s", (text, kind) => {
    expect(parseMarkdown(text)[0].kind).toBe(kind);
  });
});

describe("parseMarkdown: таблицы", () => {
  const cellTexts = (cells: { text: string }[][]) => cells.map((cell) => cell.map((part) => part.text).join(""));

  it("шапка, выравнивание и строки", () => {
    const [table] = parseMarkdown("| Файл | Строк | Статус |\n|:---|---:|:---:|\n| calc.py | 12 | ок |");

    expect(table).toMatchObject({ kind: "table", align: ["left", "right", "center"] });
    if (table.kind !== "table") throw new Error("ожидалась таблица");
    expect(cellTexts(table.header)).toEqual(["Файл", "Строк", "Статус"]);
    expect(table.rows.map(cellTexts)).toEqual([["calc.py", "12", "ок"]]);
  });

  it.each([
    ["без крайних |", "a | b\n--- | ---\n1 | 2", [["1", "2"]]],
    ["экранированный \\|", "| a | b |\n|---|---|\n| x \\| y | 2 |", [["x | y", "2"]]],
    ["неполная строка дополняется", "| a | b |\n|---|---|\n| 1 |", [["1", ""]]],
    ["лишние ячейки отбрасываются", "| a | b |\n|---|---|\n| 1 | 2 | 3 |", [["1", "2"]]],
  ])("%s", (_name, text, rows) => {
    const [table] = parseMarkdown(text);

    if (table.kind !== "table") throw new Error("ожидалась таблица");
    expect(table.rows.map(cellTexts)).toEqual(rows);
  });

  it("форматирование в ячейках", () => {
    const [table] = parseMarkdown("| Что | Где |\n|---|---|\n| **важно** | `calc.py` |");

    if (table.kind !== "table") throw new Error("ожидалась таблица");
    expect(table.rows[0]).toEqual([[{ kind: "bold", text: "важно" }], [{ kind: "code", text: "calc.py" }]]);
  });

  it("таблица заканчивается на пустой строке, дальше — обычный текст", () => {
    const blocks = parseMarkdown("Итог:\n| a | b |\n|---|---|\n| 1 | 2 |\n\nГотово");

    expect(blocks.map((block) => block.kind)).toEqual(["paragraph", "table", "paragraph"]);
  });

  it.each([
    ["| без разделителя |\n| вторая |"],
    ["a | b\n--- | --- | ---"],
    ["a | b"],
  ])("не таблица: %j", (text) => {
    expect(parseMarkdown(text).every((block) => block.kind !== "table")).toBe(true);
  });
});

describe("highlightCode", () => {
  it("ключевые слова, строки, числа и комментарии", () => {
    const tokens = highlightCode('return "ok" # 42 тут не число\nx = 42');

    expect(tokens.filter((token) => token.kind !== "text")).toEqual([
      { kind: "keyword", text: "return" },
      { kind: "string", text: '"ok"' },
      { kind: "comment", text: "# 42 тут не число" },
      { kind: "number", text: "42" },
    ]);
    expect(tokens.map((token) => token.text).join("")).toBe('return "ok" # 42 тут не число\nx = 42');
  });
});

describe("нумерованные списки", () => {
  const starts = (text: string) =>
    parseMarkdown(text).flatMap((block) => (block.kind === "list" && block.ordered ? [block.start] : []));

  it("пункты с блоком кода внутри продолжают нумерацию, а не начинают с «1.» заново", () => {
    const text = [
      "Что нужно сделать:",
      "",
      "1. **Создать очередь**",
      "   ```python",
      "   queue = Queue()",
      "   ```",
      "2. **Добавить элемент**",
      "   ```python",
      "   queue.put(1)",
      "   ```",
      "3. **Взять элемент**",
    ].join("\n");

    expect(starts(text)).toEqual([1, 2, 3]);
  });

  it("вложенный маркированный список и абзац внутри пункта не сбрасывают нумерацию", () => {
    const text = [
      "1. Подготовка",
      "   - поставить зависимости",
      "   - настроить окружение",
      "2. Запуск",
      "   Команда запускается из корня проекта.",
      "3. Проверка",
    ].join("\n");

    expect(starts(text)).toEqual([1, 2, 3]);
  });

  it("пункты, которые модель пронумеровала одной «1.», нумеруются по порядку", () => {
    const text = ["1. Первый", "1. Второй", "1. Третий"].join("\n");
    const blocks = parseMarkdown(text);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ ordered: true, start: 1 });
    expect((blocks[0] as { items: unknown[] }).items).toHaveLength(3);
  });

  it("«1.» у каждого пункта через блоки кода — тоже 1, 2, 3", () => {
    const text = ["1. Шаг", "```bash", "a", "```", "1. Шаг", "```bash", "b", "```", "1. Шаг"].join("\n");

    expect(starts(text)).toEqual([1, 2, 3]);
  });

  it("список, начатый не с единицы, сохраняет начальный номер", () => {
    expect(starts("3. третий\n4. четвёртый")).toEqual([3]);
  });

  it("новый список после заголовка или абзаца отсчитывается заново", () => {
    const text = ["1. a", "2. b", "", "## Другое", "", "1. c", "2. d", "", "Итог.", "", "5. e"].join("\n");

    expect(starts(text)).toEqual([1, 1, 5]);
  });
});

import { describe, expect, test } from "vitest";
import {
  ARTIFACT_ATTRIBUTE,
  prepareDescriptionHtml,
} from "@/lib/descriptionHtml";

const JIRA_URL = "https://example.atlassian.net/browse/RR-1";

function render(html: string, artifacts: string[] = []): HTMLElement {
  const root = document.createElement("div");
  root.append(
    prepareDescriptionHtml(html, {
      artifacts: new Set(artifacts),
      jiraUrl: JIRA_URL,
    }),
  );
  return root;
}

describe("prepareDescriptionHtml", () => {
  test("форматирование сохраняется", () => {
    const root = render(
      "<h2>Скоуп</h2><ul><li>один</li></ul><p><b>важно</b></p>",
    );

    expect(root.querySelector("h2")?.textContent).toBe("Скоуп");
    expect(root.querySelectorAll("li")).toHaveLength(1);
    expect(root.querySelector("b")?.textContent).toBe("важно");
  });

  test.each([
    ["скрипт", "<p>a</p><script>alert(1)</script>", "script"],
    ["обработчик", '<p onclick="alert(1)">a</p>', "[onclick]"],
    ["стиль", '<p style="color:red">a</p>', "[style]"],
    ["форма", "<form><input name=x></form><p>a</p>", "form, input"],
    [
      "javascript-ссылка",
      '<a href="javascript:alert(1)">a</a>',
      'a[href^="javascript"]',
    ],
  ])("опасное удаляется: %s", (_, html, selector) => {
    expect(render(html).querySelector(selector)).toBeNull();
  });

  test("ссылки открываются в новой вкладке, относительные — от Jira", () => {
    const root = render(
      '<a href="/browse/RR-2">RR-2</a><a href="https://a.example/x">x</a>',
    );

    const [relative, external] = Array.from(root.querySelectorAll("a"));
    expect(relative.getAttribute("href")).toBe(
      "https://example.atlassian.net/browse/RR-2",
    );
    expect(external.getAttribute("href")).toBe("https://a.example/x");
    expect([relative.target, relative.rel]).toEqual([
      "_blank",
      "noopener noreferrer",
    ]);
  });

  test("относительная ссылка без адреса Jira не меняется", () => {
    const root = document.createElement("div");
    root.append(
      prepareDescriptionHtml('<a href="/browse/RR-2">x</a>', {
        artifacts: new Set(),
        jiraUrl: null,
      }),
    );

    expect(root.querySelector("a")?.getAttribute("href")).toBe("/browse/RR-2");
  });

  test("картинка из артефактов подгружается оттуда, без адреса Jira", () => {
    const root = render(
      '<img src="https://example.atlassian.net/secure/attachment/1/макет.png" data-attachment-name="макет.png">',
      ["макет.png"],
    );

    const image = root.querySelector("img");
    expect(image?.getAttribute(ARTIFACT_ATTRIBUTE)).toBe("макет.png");
    expect(image?.hasAttribute("src")).toBe(false);
  });

  test.each([
    ["по src", '<img src="/secure/attachment/1/a%20b.png">', ["a b.png"], true],
    ["по alt", '<img alt="scheme.png" src="/x">', ["scheme.png"], true],
  ])("имя картинки берётся %s", (_, html, artifacts, bound) => {
    expect(
      render(html, artifacts).querySelector(`img[${ARTIFACT_ATTRIBUTE}]`) !==
        null,
    ).toBe(bound);
  });

  test("картинка не из артефактов заменяется подписью", () => {
    const root = render('<p><img src="/secure/attachment/1/lost.png"></p>');

    expect(root.querySelector("img")).toBeNull();
    expect(root.textContent).toBe("[lost.png]");
  });
});

import DOMPurify from "dompurify";

/** Теги, которых в описании не бывает: формы и встроенное содержимое. */
const FORBIDDEN_TAGS = [
  "style",
  "form",
  "input",
  "button",
  "textarea",
  "select",
  "svg",
  "math",
];
const FORBIDDEN_ATTRIBUTES = ["style"];
const IMAGE_SELECTOR = "img";
const LINK_SELECTOR = "a[href]";

/** Атрибут картинки, чей файл лежит в артефактах задачи (подставляется вместо src). */
export const ARTIFACT_ATTRIBUTE = "data-artifact";

export interface DescriptionHtmlOptions {
  /** Имена артефактов задачи — вложения Jira, скопированные при импорте. */
  artifacts: ReadonlySet<string>;
  /** Адрес задачи Jira: от него считаются относительные ссылки описания. */
  jiraUrl: string | null;
}

function fileNameOf(image: Element): string | null {
  const named =
    image.getAttribute("data-attachment-name") ?? image.getAttribute("alt");
  if (named) return named;
  const src = image.getAttribute("src");
  if (!src) return null;
  const last = src.split("?")[0].split("/").pop();
  try {
    return last ? decodeURIComponent(last) : null;
  } catch {
    return last ?? null;
  }
}

/**
 * Картинка Jira лежит за авторизацией Jira и в трекере не откроется: если её
 * файл скопирован в артефакты, она подгружается оттуда, иначе заменяется подписью.
 */
function bindImage(image: Element, artifacts: ReadonlySet<string>): void {
  const name = fileNameOf(image);
  if (name !== null && artifacts.has(name)) {
    image.removeAttribute("src");
    image.removeAttribute("srcset");
    image.setAttribute(ARTIFACT_ATTRIBUTE, name);
    return;
  }
  image.replaceWith(
    document.createTextNode(name ? `[${name}]` : "[изображение]"),
  );
}

function absoluteHref(href: string, jiraUrl: string | null): string {
  if (jiraUrl === null || !href.startsWith("/")) return href;
  try {
    return new URL(href, jiraUrl).href;
  } catch {
    return href;
  }
}

function openInNewTab(link: Element, jiraUrl: string | null): void {
  link.setAttribute(
    "href",
    absoluteHref(link.getAttribute("href") ?? "", jiraUrl),
  );
  link.setAttribute("target", "_blank");
  link.setAttribute("rel", "noopener noreferrer");
}

/**
 * HTML описания задачи Jira (раздел 15.6) → безопасный фрагмент для показа:
 * без скриптов, обработчиков и стилей Jira; ссылки — в новой вкладке, картинки —
 * из артефактов задачи.
 */
export function prepareDescriptionHtml(
  html: string,
  { artifacts, jiraUrl }: DescriptionHtmlOptions,
): DocumentFragment {
  const fragment = DOMPurify.sanitize(html, {
    RETURN_DOM_FRAGMENT: true,
    FORBID_TAGS: FORBIDDEN_TAGS,
    FORBID_ATTR: FORBIDDEN_ATTRIBUTES,
  });
  fragment
    .querySelectorAll(IMAGE_SELECTOR)
    .forEach((image) => bindImage(image, artifacts));
  fragment
    .querySelectorAll(LINK_SELECTOR)
    .forEach((link) => openInNewTab(link, jiraUrl));
  return fragment;
}

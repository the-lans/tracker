/** Предел превью свёрнутого вывода (раздел 15.2), символов. */
export const PREVIEW_LENGTH = 320;
/** Предел превью с блоком кода: слишком длинный блок обрезается, а не растягивает превью. */
export const CODE_PREVIEW_MAX = 600;

/** Ограда блока кода — та же, что понимает отрисовка ответа агента (`agentMarkdown`). */
const FENCE = /^\s*```\s*[\w+-]*\s*$/;

/**
 * Превью свёрнутого текста: первые `limit` символов, но обрезка не попадает
 * внутрь блока кода — иначе в конце остался бы кусок «```python…» без закрытия.
 * Если предел приходится на блок кода, превью доходит до его закрывающей
 * ограды, а слишком длинный блок (дальше `CODE_PREVIEW_MAX`) обрезается по строке
 * и закрывается оградой; у незакрытого блока превью обрывается перед ним.
 * Возвращает видимую часть без многоточия; короче `text` — значит, текст свёрнут.
 * Строки просматриваются лениво: огромный вывод целиком не разбирается.
 */
export function previewOf(text: string, limit: number = PREVIEW_LENGTH): string {
  if (text.length <= limit) return text;
  let openStart: number | null = null;
  let offset = 0;
  while (offset <= text.length) {
    // Дальше предела просматриваем текст, только пока не закрыт начатый блок.
    if (offset >= limit && openStart === null) break;
    const newline = text.indexOf("\n", offset);
    const lineEnd = newline === -1 ? text.length : newline;
    if (FENCE.test(text.slice(offset, lineEnd))) {
      if (openStart === null) {
        openStart = offset;
      } else {
        // Закрывающая ограда: если предел внутри блока — превью доходит до неё.
        if (lineEnd >= limit) {
          return lineEnd <= CODE_PREVIEW_MAX ? text.slice(0, lineEnd) : cutLongBlock(text, openStart);
        }
        openStart = null;
      }
    }
    if (newline === -1) break;
    offset = newline + 1;
  }
  if (openStart === null) return text.slice(0, limit);
  // Блок не закрыт до конца текста: обрыв перед его началом.
  const before = text.slice(0, openStart).trimEnd();
  return before.length > 0 ? before : text.slice(0, limit);
}

/** Длинный блок кода: строки до предела и закрывающая ограда. */
function cutLongBlock(text: string, openStart: number): string {
  const cutAt = text.lastIndexOf("\n", CODE_PREVIEW_MAX);
  const firstLineEnd = text.indexOf("\n", openStart);
  // Ни одной строки кода не влезло — блок целиком не показываем.
  if (cutAt <= firstLineEnd) return text.slice(0, openStart).trimEnd() || text.slice(0, PREVIEW_LENGTH);
  return `${text.slice(0, cutAt)}\n\`\`\``;
}

/** Свёрнутый вид: превью и многоточие; после закрывающей ограды — на новой строке, чтобы ограда осталась оградой. */
export function collapsedPreview(text: string, limit: number = PREVIEW_LENGTH): string {
  const preview = previewOf(text, limit);
  const lastLine = preview.slice(preview.lastIndexOf("\n") + 1);
  return FENCE.test(lastLine) ? `${preview}\n…` : `${preview}…`;
}

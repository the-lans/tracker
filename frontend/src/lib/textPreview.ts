/** Предел превью свёрнутого вывода (раздел 15.2), символов. */
export const PREVIEW_LENGTH = 320;
/** Предел превью с блоком кода: слишком длинный блок обрезается, а не растягивает превью. */
export const CODE_PREVIEW_MAX = 600;

const FENCE = /^ {0,3}(`{3,}|~{3,})/;

/**
 * Превью свёрнутого текста: первые `limit` символов, но обрезка не попадает
 * внутрь блока кода — иначе в конце остался бы кусок «```python…» без закрытия.
 * Если предел приходится на блок кода, превью доходит до его закрывающей
 * ограды, а слишком длинный блок (дальше `CODE_PREVIEW_MAX`) обрезается по строке
 * и закрывается своей оградой; у незакрытого блока превью обрывается перед ним.
 * Возвращает видимую часть
 * без многоточия; короче `text` — значит, текст свёрнут.
 */
export function previewOf(text: string, limit: number = PREVIEW_LENGTH): string {
  if (text.length <= limit) return text;
  let openStart: number | null = null;
  let openFence = "";
  let offset = 0;
  for (const line of text.split("\n")) {
    // Дальше предела просматриваем текст, только пока не закрыт начатый блок.
    if (offset >= limit && openStart === null) break;
    const lineEnd = offset + line.length;
    const fence = FENCE.exec(line)?.[1];
    if (openStart === null) {
      if (fence) {
        openStart = offset;
        openFence = fence;
      }
    } else if (fence && fence[0] === openFence[0] && fence.length >= openFence.length && line.trim() === fence) {
      // Закрывающая ограда: если предел внутри блока — превью доходит до неё.
      if (lineEnd >= limit) return lineEnd <= CODE_PREVIEW_MAX ? text.slice(0, lineEnd) : cutLongBlock(text, openStart, openFence);
      openStart = null;
    }
    offset = lineEnd + 1;
  }
  if (openStart === null) return text.slice(0, limit);
  // Блок не закрыт до конца текста: обрыв перед его началом.
  const before = text.slice(0, openStart).trimEnd();
  return before.length > 0 ? before : text.slice(0, limit);
}

/** Длинный блок кода: строки до предела и закрывающая ограда того же вида. */
function cutLongBlock(text: string, openStart: number, openFence: string): string {
  const cutAt = text.lastIndexOf("\n", CODE_PREVIEW_MAX);
  const firstLineEnd = text.indexOf("\n", openStart);
  // Ни одной строки кода не влезло — блок целиком не показываем.
  if (cutAt <= firstLineEnd) return text.slice(0, openStart).trimEnd() || text.slice(0, PREVIEW_LENGTH);
  return `${text.slice(0, cutAt)}\n${openFence}`;
}

/** Свёрнутый вид: превью и многоточие; после закрывающей ограды — на новой строке, чтобы ограда осталась оградой. */
export function collapsedPreview(text: string, limit: number = PREVIEW_LENGTH): string {
  const preview = previewOf(text, limit);
  const lastLine = preview.slice(preview.lastIndexOf("\n") + 1);
  return FENCE.test(lastLine) ? `${preview}\n…` : `${preview}…`;
}

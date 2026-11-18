/** Зазор между левым текстом шапки (название, аккаунт) и надписью под кнопками. */
export const NOTE_GAP_PX = 24;

export interface NotePlacementInput {
  /** Кнопки управления ушли под название — на свою строку. */
  buttonsWrapped: boolean;
  /** Ширина текста слева (название, строка аккаунта) целиком, без обрезки. */
  leftNeeded: number;
  /** Ширина левого блока шапки. */
  leftWidth: number;
  /** Ширина надписи в одну строку и ширина группы кнопок. */
  noteWidth: number;
  buttonsWidth: number;
}

/**
 * Где стоит надпись о просмотре в claude.ai/code: под кнопками справа, пока слева
 * ничего не обрезается и кнопки не ушли под название; иначе — под строкой аккаунта.
 * Надпись шире кнопок выступает влево и забирает у левого текста это место.
 */
export function noteBelowButtons(input: NotePlacementInput): boolean {
  if (input.buttonsWrapped) return false;
  const overhang = Math.max(0, input.noteWidth - input.buttonsWidth);
  return input.leftNeeded + overhang + NOTE_GAP_PX <= input.leftWidth;
}

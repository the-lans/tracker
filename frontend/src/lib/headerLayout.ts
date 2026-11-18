/** Зазор между строкой аккаунта слева и надписью под кнопками. */
export const NOTE_GAP_PX = 24;

export interface NotePlacementInput {
  /** Кнопки управления ушли под название — на свою строку. */
  buttonsWrapped: boolean;
  /** Ширина строки аккаунта слева целиком, без обрезки (название надписи не мешает). */
  leftNeeded: number;
  /** Ширина левого блока шапки. */
  leftWidth: number;
  /** Ширина надписи в одну строку и ширина группы кнопок. */
  noteWidth: number;
  buttonsWidth: number;
}

/**
 * Где стоит надпись о просмотре в claude.ai/code: под кнопками справа, пока строка
 * аккаунта слева не подступила к ней и кнопки не ушли под название; иначе — под
 * строкой аккаунта. Надпись шире кнопок выступает влево и забирает это место.
 */
export function noteBelowButtons(input: NotePlacementInput): boolean {
  if (input.buttonsWrapped) return false;
  const overhang = Math.max(0, input.noteWidth - input.buttonsWidth);
  return input.leftNeeded + overhang + NOTE_GAP_PX <= input.leftWidth;
}

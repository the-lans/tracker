/** `null` — пользователь не менял: для новой ноды значение возьмёт backend из «Системных настроек». */
export interface NodeExecutionValues {
  timeoutSeconds: number | null;
  maxRetries: number | null;
  retryBaseDelaySeconds: number | null;
  isSkipped: boolean;
}

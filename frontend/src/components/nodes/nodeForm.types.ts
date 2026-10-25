/** `null` — поле пустое: backend возьмёт значение из «Системных настроек» и у новой ноды, и при правке. */
export interface NodeExecutionValues {
  timeoutSeconds: number | null;
  maxRetries: number | null;
  retryBaseDelaySeconds: number | null;
  isSkipped: boolean;
}

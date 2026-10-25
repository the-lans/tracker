import { toast } from "sonner";
import { test as base, vi, type MockInstance } from "vitest";
import { mockApi, type MockedApi } from "@/test/apiMock";

interface Toasts {
  success: MockInstance;
  error: MockInstance;
}

interface Fixtures {
  /** Подменённый API: по умолчанию GET — пустой список, изменения — 204. */
  api: MockedApi;
  /** Перехваченные уведомления: тест проверяет текст, а не разметку Toaster. */
  toasts: Toasts;
}

/**
 * `test` с фикстурами проекта — аналог фикстур pytest из `backend/tests/conftest.py`:
 * тест объявляет нужные ему аргументы, подготовка и уборка — здесь.
 */
export const test = base.extend<Fixtures>({
  // Автоматическая: настоящий fetch не уходит в сеть ни из одного теста,
  // даже если тест не проверяет запросы.
  api: [
    // eslint-disable-next-line no-empty-pattern -- Vitest требует деструктуризацию первого аргумента
    async ({}, provide) => {
      await provide(mockApi());
      vi.unstubAllGlobals();
    },
    { auto: true },
  ],
  // eslint-disable-next-line no-empty-pattern -- то же
  toasts: async ({}, provide) => {
    const success = vi.spyOn(toast, "success");
    const error = vi.spyOn(toast, "error");
    await provide({ success, error });
    success.mockRestore();
    error.mockRestore();
  },
});

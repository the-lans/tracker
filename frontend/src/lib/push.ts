import { api } from "@/lib/apiClient";

/**
 * Web Push (раздел 18.1 ТЗ): "подписка запрашивается при первом входе".
 * Вызывается один раз из `AppShell` после успешной аутентификации —
 * best-effort, никогда не бросает наружу и не блокирует рендер: браузер
 * без поддержки Push API (или пользователь, отклонивший разрешение)
 * просто не получит уведомлений при закрытой вкладке, но приложение
 * работает как обычно (WebSocket-канал `api/ws.py`/`ws/tasks.py` покрывает
 * открытую вкладку независимо от этого).
 */
export async function ensurePushSubscription(): Promise<void> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return;
  }

  try {
    const registration = await navigator.serviceWorker.register("/service-worker.js");

    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        return;
      }
    }
    if (Notification.permission !== "granted") {
      return;
    }

    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(await fetchVapidPublicKey()),
      }));

    const json = subscription.toJSON();
    if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) {
      return;
    }
    await api.post("/push/subscriptions", {
      endpoint: json.endpoint,
      keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
    });
  } catch (error) {
    // Best-effort: пользователь мог отклонить разрешение, браузер — не
    // поддерживать Push API за прокси/в приватном режиме и т.п. — ни один
    // из этих случаев не должен ломать остальное приложение.
    console.warn("Не удалось оформить push-подписку", error);
  }
}

async function fetchVapidPublicKey(): Promise<string> {
  const { public_key: publicKey } = await api.get<{ public_key: string }>(
    "/push/vapid-public-key",
  );
  return publicKey;
}

/** `PushManager.subscribe` ожидает `applicationServerKey` как `Uint8Array`,
 * backend отдаёт urlsafe-base64 (см. `services/push_notifications.py`). */
function urlBase64ToUint8Array(base64Url: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64Url.length % 4)) % 4);
  const base64 = (base64Url + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(rawData.length));
  for (let i = 0; i < rawData.length; i += 1) {
    bytes[i] = rawData.charCodeAt(i);
  }
  return bytes;
}

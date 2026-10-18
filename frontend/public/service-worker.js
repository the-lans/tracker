// Service Worker для Web Push (раздел 18.1 ТЗ) — минимальный: показывает
// уведомление, полученное через Push API, и открывает/фокусирует вкладку
// приложения на нужной задаче по клику. Никакого offline-кеширования не
// делает — это не PWA-задача, а обязательный носитель для push-подписки
// (без активного Service Worker `PushManager.subscribe()` недоступен).

self.addEventListener("push", (event) => {
  let payload = { title: "Tracker", body: "" };
  try {
    if (event.data) {
      payload = event.data.json();
    }
  } catch {
    // Полезная нагрузка не JSON — покажем дефолтное уведомление, не падаем.
  }

  const data = payload.data || {};
  event.waitUntil(
    self.registration.showNotification(payload.title || "Tracker", {
      body: payload.body || "",
      data,
      tag: data.task_id ? `task-${data.task_id}` : undefined,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const taskId = event.notification.data && event.notification.data.task_id;
  const targetUrl = taskId ? `/tasks/${taskId}` : "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        const clientUrl = new URL(client.url);
        if (clientUrl.origin === self.location.origin && "focus" in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
      return undefined;
    }),
  );
});

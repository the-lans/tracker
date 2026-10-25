import { vi } from "vitest";

/**
 * Подмена `WebSocket`: тест сам открывает соединение, присылает события и
 * закрывает его с нужным кодом; отправленные сообщения записываются.
 */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(message: string) {
    this.sent.push(message);
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.onclose?.({ code: 1000 });
  }

  /** Сервер принял соединение. */
  open() {
    this.onopen?.();
  }

  /** Сервер прислал событие. */
  receive(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) });
  }

  /** Соединение оборвалось с кодом `code`. */
  drop(code = 1006) {
    this.closed = true;
    this.onclose?.({ code });
  }

  static latest(): FakeWebSocket {
    const socket = FakeWebSocket.instances.at(-1);
    if (!socket) throw new Error("WebSocket ещё не открывался");
    return socket;
  }
}

export function stubWebSocket() {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
}

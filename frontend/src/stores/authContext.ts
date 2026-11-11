import { createContext } from "react";
import type { CurrentUser } from "@/lib/types";

const STORAGE_KEY = "tracker.session";
const SESSION_EXPIRED_EVENT = "tracker:session-expired";

export interface StoredSession {
  token: string;
  user: CurrentUser;
}

export interface AuthContextValue {
  token: string | null;
  user: CurrentUser | null;
  isAuthenticated: boolean;
  login: (session: StoredSession) => void;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function readStoredSession(): StoredSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredSession;
  } catch {
    return null;
  }
}

export function writeStoredSession(session: StoredSession | null): void {
  try {
    if (session === null) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    }
  } catch {
    // localStorage недоступен (приватный режим и т.п.) — сессия останется
    // только в памяти на время текущей вкладки.
  }
}

export function getStoredToken(): string | null {
  return readStoredSession()?.token ?? null;
}

/**
 * Сервер отверг токен (401: истёк, подписан прежним ключом, пользователь
 * заблокирован) или запрос ушёл без токена, потому что сессию уже сбросила
 * другая вкладка. Сессия сбрасывается, только если её не сменил новый вход,
 * пока шёл запрос.
 */
export function expireStoredSession(token: string | null): void {
  const stored = getStoredToken();
  if (stored !== null && stored !== token) return;
  writeStoredSession(null);
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

/** Подписка на сброс сессии из `expireStoredSession`; возвращает отписку. */
export function onSessionExpired(listener: () => void): () => void {
  window.addEventListener(SESSION_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
}

/**
 * Вход и выход в другой вкладке: событие `storage` приходит только во вкладки,
 * которые запись не делали. `key === null` — хранилище очищено целиком.
 */
export function onStoredSessionChange(listener: () => void): () => void {
  const handler = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === null) listener();
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}

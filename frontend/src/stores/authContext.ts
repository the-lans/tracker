import { createContext } from "react";
import type { CurrentUser } from "@/lib/types";

const SESSION_EXPIRED_EVENT = "tracker:session-expired";
const CHANGE_KEY = "tracker.auth-change";
let generation = 0;

export const sessionGeneration = () => generation;

export function advanceSession() {
  generation += 1;
}

export interface AuthContextValue {
  user: CurrentUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (user: CurrentUser) => void;
  logout: () => Promise<void>;
  clearSession: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function announceSessionChange() {
  try {
    localStorage.setItem(CHANGE_KEY, crypto.randomUUID());
  } catch {
    // Хранилище недоступно — вход продолжает работать в текущей вкладке.
  }
}

export function expireStoredSession(expectedGeneration: number) {
  if (expectedGeneration !== generation) return;
  advanceSession();
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

export function onSessionExpired(listener: () => void) {
  window.addEventListener(SESSION_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
}

export function onStoredSessionChange(listener: () => void) {
  const handler = (event: StorageEvent) => {
    if (event.key === CHANGE_KEY || event.key === null) listener();
  };
  window.addEventListener("storage", handler);
  return () => window.removeEventListener("storage", handler);
}

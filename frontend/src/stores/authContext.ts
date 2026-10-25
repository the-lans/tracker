import { createContext } from "react";
import type { CurrentUser } from "@/lib/types";

const STORAGE_KEY = "tracker.session";

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

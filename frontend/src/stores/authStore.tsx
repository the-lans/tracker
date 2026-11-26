import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/apiClient";
import type { CurrentUser } from "@/lib/types";
import {
  AuthContext,
  advanceSession,
  announceSessionChange,
  onSessionExpired,
  onStoredSessionChange,
  sessionGeneration,
  type AuthContextValue,
} from "@/stores/authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const refreshSequence = useRef(0);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const replaceUser = useCallback((next: CurrentUser | null) => {
    refreshSequence.current += 1;
    advanceSession();
    queryClient.clear();
    setLoading(false);
    setError(false);
    setUser(next);
  }, [queryClient]);
  const clearSession = useCallback(() => {
    replaceUser(null);
    announceSessionChange();
  }, [replaceUser]);
  const login = useCallback((next: CurrentUser) => {
    replaceUser(next);
    announceSessionChange();
  }, [replaceUser]);
  const logout = useCallback(async () => {
    await api.post("/auth/logout");
    clearSession();
  }, [clearSession]);
  useEffect(() => {
    try {
      localStorage.removeItem("tracker.session");
    } catch {
      // Старое хранилище недоступно.
    }
    let mounted = true;
    async function refresh() {
      advanceSession();
      const expected = sessionGeneration();
      const sequence = ++refreshSequence.current;
      setLoading(true);
      setError(false);
      try {
        const next = await api.get<CurrentUser>("/auth/me");
        if (mounted && expected === sessionGeneration()) replaceUser(next);
      } catch (err) {
        if (mounted && sequence === refreshSequence.current) {
          if (err instanceof ApiError && err.status === 401) setUser(null);
          else if (expected === sessionGeneration()) setError(true);
        }
      } finally {
        if (mounted && sequence === refreshSequence.current) setLoading(false);
      }
    }
    void refresh();
    const offExpired = onSessionExpired(() => {
      refreshSequence.current += 1;
      queryClient.clear();
      setUser(null);
      setLoading(false);
    });
    const offStorage = onStoredSessionChange(() => {
      queryClient.clear();
      setUser(null);
      void refresh();
    });
    return () => {
      mounted = false;
      offExpired();
      offStorage();
    };
  }, [queryClient, replaceUser]);
  const value = useMemo<AuthContextValue>(
    () => ({ user, isAuthenticated: user !== null, isLoading, login, logout, clearSession }),
    [user, isLoading, login, logout, clearSession],
  );
  if (error) return <div role="alert">Не удалось проверить сессию. Обновите страницу.</div>;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

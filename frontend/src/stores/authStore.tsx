import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  AuthContext,
  readStoredSession,
  writeStoredSession,
  type AuthContextValue,
  type StoredSession,
} from "@/stores/authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(() => readStoredSession());

  const login = useCallback((next: StoredSession) => {
    writeStoredSession(next);
    setSession(next);
  }, []);

  const logout = useCallback(() => {
    writeStoredSession(null);
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      token: session?.token ?? null,
      user: session?.user ?? null,
      isAuthenticated: session !== null,
      login,
      logout,
    }),
    [session, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

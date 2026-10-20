import { useEffect, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { toast } from "sonner";
import { BrandMark } from "@/components/layout/BrandMark";
import { api, ApiError } from "@/lib/apiClient";
import { useAuth } from "@/stores/authStore";
import type { LoginResponse } from "@/lib/types";

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

export function LoginPage() {
  const { isAuthenticated, login } = useAuth();
  const buttonRef = useRef<HTMLDivElement>(null);
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || !buttonRef.current) return;

    let cancelled = false;
    function renderWhenReady() {
      if (cancelled) return;
      if (!window.google?.accounts.id) {
        setTimeout(renderWhenReady, 200);
        return;
      }
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID!,
        callback: (response) => {
          setSigningIn(true);
          api
            .post<LoginResponse>("/auth/google", { id_token: response.credential })
            .then((data) => login({ token: data.session_token, user: data.user }))
            .catch((error: unknown) => {
              toast.error(
                error instanceof ApiError ? error.message : "Не удалось войти через Google",
              );
            })
            .finally(() => setSigningIn(false));
        },
      });
      if (buttonRef.current) {
        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: "outline",
          size: "large",
          width: 280,
        });
      }
    }
    renderWhenReady();
    return () => {
      cancelled = true;
    };
  }, [login]);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="flex h-dvh w-full flex-col items-center justify-center gap-6 bg-bg px-4">
      <div className="flex items-center gap-3">
        <BrandMark size={40} />
        <span className="text-display font-extrabold tracking-tight">Tracker</span>
      </div>
      <p className="max-w-xs text-center text-body-lg text-text-2">
        Войдите с помощью учётной записи Google, разрешённой администратором.
      </p>
      {GOOGLE_CLIENT_ID ? (
        <div ref={buttonRef} />
      ) : (
        <div className="max-w-sm rounded-lg border border-warning-border bg-warning-tint p-3 text-center text-note text-warning-text">
          Не задан VITE_GOOGLE_CLIENT_ID — вход через Google недоступен. Заполните переменную
          окружения (см. frontend/.env.example) и пересоберите фронтенд.
        </div>
      )}
      {signingIn && <p className="text-note text-text-3">Выполняется вход…</p>}
    </div>
  );
}

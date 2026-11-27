import { useMutation } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/apiClient";

/**
 * Раздел 19.1: токены пользователя на всех устройствах недействительны —
 * в том числе на этом, поэтому после ответа выход и здесь.
 */
export function useLogoutEverywhere() {
  const { clearSession } = useAuth();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout-all"),
    onSuccess: clearSession,
  });
}

import { useAuth } from "@/hooks/useAuth";
import { UserRole } from "@/lib/types";

export function useIsAdmin(): boolean {
  const { user } = useAuth();
  return user?.role === UserRole.ADMIN;
}

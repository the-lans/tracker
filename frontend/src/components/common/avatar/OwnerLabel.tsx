import { useUsers } from "@/hooks/useAdmin";
import { useIsAdmin } from "@/hooks/useIsAdmin";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

/**
 * Автор чужой записи — видит только `admin` (раздел 19.2 ТЗ: ему доступны
 * записи всех пользователей). На своих записях и у `user` не показывается.
 */
export function OwnerLabel({ ownerId, className }: { ownerId: string; className?: string }) {
  const { user } = useAuth();
  const isAdmin = useIsAdmin();
  const { data: users } = useUsers({ enabled: isAdmin });
  if (!isAdmin || ownerId === user?.id) return null;
  const email = users?.find((candidate) => candidate.id === ownerId)?.email ?? "другой пользователь";
  return (
    <span className={cn("block truncate text-caption text-text-3", className)} title={email}>
      Автор: {email}
    </span>
  );
}

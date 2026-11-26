import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmActionButton } from "@/components/common/actions/ConfirmActionButton";
import { useAuth } from "@/hooks/useAuth";
import { useLogoutEverywhere } from "@/hooks/useLogoutEverywhere";
import { toastError } from "@/lib/errors";

/**
 * Раздел 19.1: «Выйти» — только на этом устройстве; «Выйти на всех
 * устройствах» отзывает все выданные токены, например если токен мог утечь.
 */
export function LogoutActions() {
  const { logout } = useAuth();
  const logoutEverywhere = useLogoutEverywhere();

  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="secondary" onClick={() => { void logout().catch(toastError("Не удалось выйти")); }}>
        <LogOut className="size-4" />
        Выйти
      </Button>
      <ConfirmActionButton
        title="Выйти на всех устройствах?"
        description="Вход завершится во всех браузерах и на телефоне, включая этот. Задачи продолжат выполняться."
        confirmLabel="Выйти везде"
        pending={logoutEverywhere.isPending}
        onConfirm={() =>
          logoutEverywhere.mutate(undefined, {
            onError: toastError("Не удалось выйти на всех устройствах"),
          })
        }
      >
        Выйти на всех устройствах
      </ConfirmActionButton>
    </div>
  );
}

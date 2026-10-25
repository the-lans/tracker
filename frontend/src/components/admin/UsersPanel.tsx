import { useUsers } from "@/hooks/useAdmin";
import { AllowedEmailsCard } from "@/components/admin/AllowedEmailsCard";
import { UserRow } from "@/components/admin/UserRow";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { SectionTitle } from "@/components/common/typography/SectionTitle";

export function UsersPanel() {
  const { data: users, isLoading } = useUsers();

  return (
    <div className="flex flex-col gap-5">
      <div>
        <SectionTitle className="mb-2">Пользователи</SectionTitle>
        {isLoading && <LoadingState />}
        <div className="flex flex-col gap-2">
          {(users ?? []).map((user) => (
            <UserRow key={user.id} user={user} />
          ))}
        </div>
      </div>

      <AllowedEmailsCard />
    </div>
  );
}

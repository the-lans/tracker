import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EventsList } from "@/components/events/EventsList";
import { useIsAdmin } from "@/hooks/useIsAdmin";
import {
  ADMIN_EVENT_CATEGORIES,
  EventAudience,
  USER_EVENT_CATEGORIES,
} from "@/lib/events.types";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

const TAB_PARAM = "tab";

const MY_EVENTS_HINT =
  "Здесь появятся завершение и сбои ваших задач, запросы решений и события LLM-аккаунтов.";
const SYSTEM_EVENTS_HINT = "Здесь появятся итоги бэкапов и сбои периодических задач.";

/**
 * Раздел 18.4: «События» — лента своих задач, LLM-аккаунтов и профиля;
 * администратору — ещё и системная лента (бэкапы, периодические задачи).
 */
export function EventsPage() {
  const isAdmin = useIsAdmin();
  const [searchParams, setSearchParams] = useSearchParams();
  // Вкладки — только у администратора; у пользователя всегда своя лента.
  const tab =
    searchParams.get(TAB_PARAM) === EventAudience.ADMINS ? EventAudience.ADMINS : EventAudience.USER;
  const mine = (
    <EventsList audience={EventAudience.USER} categories={USER_EVENT_CATEGORIES} emptyHint={MY_EVENTS_HINT} />
  );

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="События" />
      <div className={PAGE_BODY}>
        <div className="mx-auto w-full max-w-3xl">
          {isAdmin ? (
            <Tabs
              value={tab}
              onValueChange={(value) => setSearchParams({ [TAB_PARAM]: value }, { replace: true })}
            >
              <TabsList className="mb-4">
                <TabsTrigger value={EventAudience.USER}>Мои</TabsTrigger>
                <TabsTrigger value={EventAudience.ADMINS}>Системные</TabsTrigger>
              </TabsList>
              <TabsContent value={EventAudience.USER}>{mine}</TabsContent>
              <TabsContent value={EventAudience.ADMINS}>
                <EventsList
                  audience={EventAudience.ADMINS}
                  categories={ADMIN_EVENT_CATEGORIES}
                  emptyHint={SYSTEM_EVENTS_HINT}
                />
              </TabsContent>
            </Tabs>
          ) : (
            mine
          )}
        </div>
      </div>
    </div>
  );
}

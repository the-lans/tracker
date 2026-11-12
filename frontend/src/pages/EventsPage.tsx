import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs, type PageTab } from "@/components/common/navigation/PageTabs";
import { EventsList } from "@/components/events/EventsList";
import { useIsAdmin } from "@/hooks/useIsAdmin";
import {
  ADMIN_EVENT_CATEGORIES,
  EventAudience,
  USER_EVENT_CATEGORIES,
} from "@/lib/events.types";
import { PAGE_BODY, PAGE_ROOT } from "@/styles/classes";

const MY_EVENTS_HINT =
  "Здесь появятся завершение и сбои ваших задач, запросы решений и события LLM-аккаунтов.";
const SYSTEM_EVENTS_HINT = "Здесь появятся итоги бэкапов и сбои периодических задач.";

const MY_EVENTS = (
  <EventsList audience={EventAudience.USER} categories={USER_EVENT_CATEGORIES} emptyHint={MY_EVENTS_HINT} />
);

const ADMIN_EVENT_TABS: PageTab[] = [
  { value: EventAudience.USER, label: "Мои", content: MY_EVENTS },
  {
    value: EventAudience.ADMINS,
    label: "Системные",
    content: (
      <EventsList
        audience={EventAudience.ADMINS}
        categories={ADMIN_EVENT_CATEGORIES}
        emptyHint={SYSTEM_EVENTS_HINT}
      />
    ),
  },
];

/**
 * Раздел 18.4: «События» — лента своих задач, LLM-аккаунтов и профиля;
 * администратору — ещё и системная лента (бэкапы, периодические задачи).
 */
export function EventsPage() {
  const isAdmin = useIsAdmin();

  return (
    <div className={PAGE_ROOT}>
      <PageHeader title="События" />
      <div className={PAGE_BODY}>
        <div className="mx-auto w-full max-w-3xl">
          {/* Вкладки — только у администратора; у пользователя всегда своя лента. */}
          {isAdmin ? <PageTabs tabs={ADMIN_EVENT_TABS} /> : MY_EVENTS}
        </div>
      </div>
    </div>
  );
}

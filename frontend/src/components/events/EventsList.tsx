import { useState } from "react";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { LoadingState } from "@/components/common/feedback/LoadingState";
import { EventRow } from "@/components/events/EventRow";
import { useEvents } from "@/hooks/useEvents";
import type { EventAudience, EventCategory } from "@/lib/events.types";
import { EVENT_CATEGORY_LABEL } from "@/lib/labels";

const ALL_CATEGORIES = "all";

/** Раздел 18.4: лента одной аудитории с фильтром категории и подгрузкой старых событий. */
export function EventsList({
  audience,
  categories,
  emptyHint,
}: {
  audience: EventAudience;
  categories: EventCategory[];
  emptyHint: string;
}) {
  const [category, setCategory] = useState<EventCategory | typeof ALL_CATEGORIES>(ALL_CATEGORIES);
  const { data, isLoading, isError, hasNextPage, fetchNextPage, isFetchingNextPage } = useEvents({
    audience,
    category: category === ALL_CATEGORIES ? undefined : category,
  });
  const events = data?.pages.flat() ?? [];

  return (
    <div className="flex flex-col gap-3">
      <Select value={category} onValueChange={(value) => setCategory(value as EventCategory | typeof ALL_CATEGORIES)}>
        <SelectTrigger className="w-full sm:w-60" aria-label="Категория">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_CATEGORIES}>Все категории</SelectItem>
          {categories.map((value) => (
            <SelectItem key={value} value={value}>
              {EVENT_CATEGORY_LABEL[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isLoading && <LoadingState />}
      {isError && <div className="text-body text-danger-text">Не удалось загрузить события</div>}
      {!isLoading && !isError && events.length === 0 && (
        <EmptyState icon={Bell} title="Событий нет" hint={emptyHint} />
      )}
      {events.length > 0 && (
        <ul className="flex flex-col gap-2">
          {events.map((event) => (
            <EventRow key={event.id} event={event} />
          ))}
        </ul>
      )}
      {hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          disabled={isFetchingNextPage}
          onClick={() => void fetchNextPage()}
        >
          {isFetchingNextPage ? "Загрузка…" : "Показать ещё"}
        </Button>
      )}
    </div>
  );
}

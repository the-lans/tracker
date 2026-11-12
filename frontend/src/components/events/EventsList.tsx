import { useState } from "react";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/feedback/EmptyState";
import { QueryState } from "@/components/common/feedback/QueryState";
import { FilterSelect } from "@/components/common/filters/FilterSelect";
import { EventRow } from "@/components/events/EventRow";
import { useEvents } from "@/hooks/useEvents";
import type { EventAudience, EventCategory } from "@/lib/events.types";
import { EVENT_CATEGORY_LABEL } from "@/lib/labels";

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
  const [category, setCategory] = useState<EventCategory>();
  const { data, isLoading, isError, hasNextPage, fetchNextPage, isFetchingNextPage } = useEvents({
    audience,
    category,
  });
  const events = data?.pages.flat() ?? [];

  return (
    <div className="flex flex-col gap-3">
      <FilterSelect
        value={category}
        onChange={setCategory}
        values={categories}
        labels={EVENT_CATEGORY_LABEL}
        allLabel="Все категории"
        label="Категория"
        className="w-full sm:w-60"
      />
      <QueryState isLoading={isLoading} isError={isError} errorLabel="Не удалось загрузить события">
        {events.length === 0 ? (
          <EmptyState icon={Bell} title="Событий нет" hint={emptyHint} />
        ) : (
          <ul className="flex flex-col gap-2">
            {events.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </ul>
        )}
      </QueryState>
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

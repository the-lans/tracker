import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { pageCountOf } from "@/lib/utils";

/** Постраничный список: «Назад» / «Вперёд» и номер страницы; одна страница — ничего. */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const pageCount = pageCountOf(total, pageSize);
  if (pageCount <= 1) return null;

  return (
    <nav aria-label="Страницы" className="flex items-center justify-center gap-2">
      <Button
        variant="outline"
        aria-label="Предыдущая страница"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft className="size-4" />
        <span className="hidden sm:inline">Назад</span>
      </Button>
      <span className="min-w-0 px-1 text-center text-small text-text-2" aria-live="polite">
        Страница {page} из {pageCount}
      </span>
      <Button
        variant="outline"
        aria-label="Следующая страница"
        disabled={page >= pageCount}
        onClick={() => onPageChange(page + 1)}
      >
        <span className="hidden sm:inline">Вперёд</span>
        <ChevronRight className="size-4" />
      </Button>
    </nav>
  );
}

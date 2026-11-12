import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { SearchSelectOption } from "@/components/common/inputs/searchSelect.types";

/** Сколько вариантов показывать сразу: длинный список уточняют поиском. */
export const SEARCH_SELECT_LIMIT = 50;

function matches(option: SearchSelectOption, query: string): boolean {
  return option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}

/**
 * Выбор из длинного списка с поиском по подписи: поле ввода фильтрует
 * варианты, стрелки двигают выделение, Enter выбирает, Escape закрывает.
 * `clearLabel` — первый пункт, который снимает выбор (`null`).
 */
export function SearchSelect({
  id,
  value,
  options,
  onChange,
  clearLabel,
  placeholder = "Поиск",
}: {
  id: string;
  value: string | null;
  options: readonly SearchSelectOption[];
  onChange: (value: string | null) => void;
  clearLabel: string;
  placeholder?: string;
}) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const found = options.filter((option) => matches(option, query));
  const shown: SearchSelectOption[] = [
    { value: null, label: clearLabel },
    ...found.slice(0, SEARCH_SELECT_LIMIT),
  ];
  const selectedLabel = options.find((option) => option.value === value)?.label ?? clearLabel;

  useEffect(() => {
    if (!open) return;
    // Диалог Radix ловит Escape на document в фазе перехвата — раньше поля —
    // и не закрывается, если событие уже отменено. Перехват на window
    // срабатывает ещё раньше: Escape закрывает только список.
    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape, { capture: true });
    return () => window.removeEventListener("keydown", closeOnEscape, { capture: true });
  }, [open]);

  function openList() {
    setQuery("");
    setActive(0);
    setOpen(true);
  }

  function choose(option: SearchSelectOption) {
    onChange(option.value);
    setOpen(false);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "Enter") {
        event.preventDefault();
        openList();
      }
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) => (current + step + shown.length) % shown.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(shown[active]);
    }
  }

  return (
    <div className="relative">
      <Input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        placeholder={placeholder}
        value={open ? query : selectedLabel}
        onFocus={openList}
        onClick={() => !open && openList()}
        onBlur={() => setOpen(false)}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={handleKeyDown}
      />
      {open && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-surface py-1 shadow-lg"
        >
          {shown.map((option, index) => (
            <li
              key={option.value ?? ""}
              role="option"
              aria-selected={option.value === value}
              className={cn(
                "cursor-pointer break-words px-3 py-2 text-sm text-text",
                index === active && "bg-surface-2",
                option.value === value && "font-bold",
              )}
              // mousedown, а не click: иначе blur поля закроет список раньше выбора.
              onMouseDown={(event) => {
                event.preventDefault();
                choose(option);
              }}
              // mousemove, а не mouseenter: пункты, сдвинувшиеся под неподвижный
              // курсор при вводе, не перехватывают выделение у клавиатуры.
              onMouseMove={() => setActive(index)}
            >
              {option.label}
            </li>
          ))}
          {found.length === 0 && <li className="px-3 py-2 text-small text-text-3">Ничего не найдено</li>}
          {found.length > SEARCH_SELECT_LIMIT && (
            <li className="px-3 py-2 text-small text-text-3">
              Показаны первые {SEARCH_SELECT_LIMIT} из {found.length} — уточните поиск
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

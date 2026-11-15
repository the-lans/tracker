import { forwardRef, type FocusEventHandler, type InputHTMLAttributes } from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

type SearchInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "value"> & {
  value: string;
  onClear: () => void;
  clearVisible?: boolean;
  containerClassName?: string;
  onContainerBlur?: FocusEventHandler<HTMLDivElement>;
};

/** Единое оформление поля поиска и доступная кнопка очистки. */
export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(
  ({ value, onClear, clearVisible = Boolean(value), containerClassName, onContainerBlur, className, type = "text", ...props }, ref) => (
    <div className={cn(
      "flex min-h-11 min-w-0 items-center gap-2 rounded-md border border-text-3/40 bg-surface-2 pl-3 text-text-3 focus-within:border-accent focus-within:ring-1 focus-within:ring-accent",
      containerClassName,
    )} onBlur={onContainerBlur}>
      <Search aria-hidden="true" className="size-4 shrink-0" />
      <input
        {...props}
        ref={ref}
        type={type}
        value={value}
        className={cn("h-11 min-w-0 flex-1 bg-transparent text-body-lg text-text outline-none placeholder:text-text-3 [&::-webkit-search-cancel-button]:appearance-none", className)}
      />
      {clearVisible ? (
        <button
          type="button"
          aria-label="Очистить поиск"
          title="Очистить поиск"
          className="flex size-10 shrink-0 items-center justify-center rounded-md text-text-3 hover:bg-surface hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
          onMouseDown={(event) => event.preventDefault()}
          onClick={onClear}
        >
          <X aria-hidden="true" className="size-4" />
        </button>
      ) : <span aria-hidden="true" className="w-3 shrink-0" />}
    </div>
  ),
);
SearchInput.displayName = "SearchInput";

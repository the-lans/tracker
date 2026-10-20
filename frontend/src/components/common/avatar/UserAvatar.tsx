import { USER_AVATAR_GRADIENT } from "@/styles/classes";
import { cn, initialsFromEmail } from "@/lib/utils";

const SIZE_CLASS = {
  md: "size-[34px] text-body-lg",
  lg: "size-12 text-title",
} as const;

/** Круглый аватар с инициалами по e-mail. */
export function UserAvatar({
  email,
  size = "md",
  className,
}: {
  email: string | null | undefined;
  size?: keyof typeof SIZE_CLASS;
  className?: string;
}) {
  return (
    <div
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-full font-extrabold",
        USER_AVATAR_GRADIENT,
        SIZE_CLASS[size],
        className,
      )}
    >
      {email ? initialsFromEmail(email) : "?"}
    </div>
  );
}

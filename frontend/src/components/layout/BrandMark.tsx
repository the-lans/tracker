/** Фирменный знак: восходящие узлы пайплайна (docs/design/references/*.html, .brand-mark). */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-[10px]"
      style={{
        width: size,
        height: size,
        background: "linear-gradient(135deg,#5259dd,#8b5cf0 62%,#ab72f5)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,.28), 0 3px 8px rgba(88,73,224,.32)",
      }}
    >
      <svg viewBox="0 0 24 24" fill="none" width={size * 0.625} height={size * 0.625}>
        <path
          d="M4 17c4 0 4-7 8-7s4-4 8-4"
          stroke="rgba(255,255,255,.55)"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx="4" cy="17" r="1.6" fill="rgba(255,255,255,.6)" />
        <circle cx="12" cy="10" r="2" fill="rgba(255,255,255,.85)" />
        <circle cx="20" cy="6" r="2.7" fill="#ffffff" />
      </svg>
    </div>
  );
}

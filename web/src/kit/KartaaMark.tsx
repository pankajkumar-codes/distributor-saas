/** The Kartaa mark: a rounded square holding a K whose upper arm ends in a small dot. Colours come from the theme tokens. */
export function KartaaMark({ size = 32 }: { size?: number }) {
  const stroke = { fill: "none", stroke: "var(--accent-ink)", strokeWidth: 4.2, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" focusable="false" className="kartaa-mark">
      <rect width="48" height="48" rx="13" fill="var(--accent)" />
      <path d="M16.5 11.5v25" {...stroke} />
      <path d="M17.5 25.5 30 13.5" {...stroke} />
      <path d="M23 24.5 32 36.5" {...stroke} />
      <circle cx="34.5" cy="12" r="2.6" fill="var(--accent-ink)" />
    </svg>
  );
}

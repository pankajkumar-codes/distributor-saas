import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export type Tab = { label: ReactNode; panel: ReactNode; key?: string };

/**
 * Tabs for a long page (mocks v16 one-screen rule): only the chosen panel is drawn. The parent
 * owns which tab is open, so a page can keep it in the URL. Arrow keys, Home and End move
 * between tabs, as the ARIA tabs pattern expects. With `keepMounted`, every panel stays drawn and the others
 * are hidden, so what a person typed or started in one tab (a form, a file being made) survives a switch.
 */
export function Tabs({ tabs, current, onChange, label, keepMounted = false }: { tabs: Tab[]; current: number; onChange: (i: number) => void; label: string; keepMounted?: boolean }) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const at = Math.min(Math.max(current, 0), tabs.length - 1);
  const move = (e: KeyboardEvent) => {
    const n = tabs.length;
    const to = e.key === "ArrowRight" ? (at + 1) % n : e.key === "ArrowLeft" ? (at - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    onChange(to);
    refs.current[to]?.focus();
  };
  return (
    <>
      <div className="ltabs" role="tablist" aria-label={label} onKeyDown={move}>
        {tabs.map((t, i) => (
          <button
            key={t.key ?? i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${id}-t${i}`}
            aria-controls={`${id}-p${i}`}
            aria-selected={i === at}
            tabIndex={i === at ? 0 : -1}
            onClick={() => onChange(i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {keepMounted ? (
        tabs.map((t, i) => (
          <div key={t.key ?? i} role="tabpanel" id={`${id}-p${i}`} aria-labelledby={`${id}-t${i}`} className="ltabpanel" hidden={i !== at}>
            {t.panel}
          </div>
        ))
      ) : (
        <div role="tabpanel" id={`${id}-p${at}`} aria-labelledby={`${id}-t${at}`} className="ltabpanel">
          {tabs[at]?.panel}
        </div>
      )}
    </>
  );
}

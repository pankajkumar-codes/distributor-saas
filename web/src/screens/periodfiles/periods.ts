const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export type PeriodKind = "month" | "quarter";
export type PeriodChoice = { start: string; label: string };

const iso = (y: number, m: number, d: number) => `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

const label = (kind: PeriodKind, y: number, m: number) =>
  kind === "month" ? `${MONTHS[m - 1]} ${y}` : `${MONTHS[m - 1]}–${MONTHS[m + 1]} ${y}`;

/**
 * The finished months, or quarters, newest first, to choose from: only a period that has wholly ended is offered
 * (the server refuses anything else too). `today` is a plain ISO date so a test can fix it.
 */
export function finishedPeriods(kind: PeriodKind, today: string, count = 12, withCurrent = false): PeriodChoice[] {
  const [ty, tm] = today.split("-").map(Number);
  const step = kind === "month" ? 1 : 3;
  // the first month of the period that today falls in; the one before it is the newest finished period
  let y = ty;
  let m = kind === "month" ? tm : tm - ((tm - 1) % 3);
  const out: PeriodChoice[] = [];
  if (withCurrent) out.push({ start: iso(y, m, 1), label: label(kind, y, m) });
  for (let i = 0; i < count; i++) {
    m -= step;
    if (m < 1) {
      m += 12;
      y -= 1;
    }
    out.push({ start: iso(y, m, 1), label: label(kind, y, m) });
  }
  return out;
}

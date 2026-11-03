const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;

/** Today's date in India as YYYY-MM-DD, whatever the browser's own time zone. */
export function todayIst(now: Date = new Date()): string {
  return new Date(now.getTime() + IST_OFFSET_MS).toISOString().slice(0, 10);
}

/** The first day of the quarter (Apr, Jul, Oct, Jan) that today in India falls in. */
export function quarterStartIst(now: Date = new Date()): string {
  const [year, month] = todayIst(now).split("-").map(Number);
  const first = Math.floor((month - 1) / 3) * 3 + 1;
  return `${year}-${String(first).padStart(2, "0")}-01`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** YYYY-MM-DD as DD-MMM-YYYY (LLD-1 §11.1), straight from the string: no time zone involved. */
export function formatDate(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && month ? `${m[3]}-${month}-${m[1]}` : day;
}

/** The hour of the day in India, 0 to 23. */
export function hourIst(now: Date = new Date()): number {
  return new Date(now.getTime() + IST_OFFSET_MS).getUTCHours();
}

/** The calendar day before an ISO date ("2026-03-01" → "2026-02-28"); a malformed value as is. */
export function dayBefore(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!m) return day;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) - 1));
  return d.toISOString().slice(0, 10);
}

/** An instant as DD-MMM-YYYY, HH:MM in India ("25-Oct-2026, 14:20"), whatever the browser's time zone. */
export function formatDateTimeIst(instant: string): string {
  const t = Date.parse(instant);
  if (Number.isNaN(t)) return instant;
  const ist = new Date(t + IST_OFFSET_MS).toISOString();
  return `${formatDate(ist.slice(0, 10))}, ${ist.slice(11, 16)}`;
}

/** The Indian financial year (April to March) that today in India falls in, as "2026-27". */
export function fyIst(now: Date = new Date()): string {
  const [year, month] = todayIst(now).split("-").map(Number);
  const start = month >= 4 ? year : year - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/** The financial year before `fy` ("2026-27" → "2025-26"); a malformed value as is. */
export function previousFy(fy: string): string {
  const m = /^(\d{4})-\d{2}$/.exec(fy);
  if (!m) return fy;
  const start = Number(m[1]) - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

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

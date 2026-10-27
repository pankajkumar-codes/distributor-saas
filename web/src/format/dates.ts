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
  return m ? `${m[3]}-${MONTHS[Number(m[2]) - 1]}-${m[1]}` : day;
}

/** The hour of the day in India, 0 to 23. */
export function hourIst(now: Date = new Date()): number {
  return new Date(now.getTime() + IST_OFFSET_MS).getUTCHours();
}

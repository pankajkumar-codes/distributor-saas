// Home's "Your next step" card (mocks v16, Ledger + the guided card from direction B). The card is
// worked out here from data the app already has: the setup checklist from GET /home, the
// server's return periods and, for the GSTR-1 path, the read-only build of that return. Nothing
// here invents a date or a count; a step it cannot judge is shown as not done.

import { formatDate } from "../../format/dates";
import { screenPath } from "./links";

export type StepState = "done" | "cur" | "todo";
export type PathStep = { label: string; sub?: string; state: StepState };
export type NextStep = {
  kind: "setup" | "gstr1" | "clear";
  title: string;
  hint: string;
  steps: PathStep[];
  /** Index of the current step in `steps`, or -1 when there is none. */
  current: number;
  action: { label: string; to: string } | null;
  /** A plain link beside the button for a second way forward (a month with no sales goes on to a nil return, #406). */
  alt?: { label: string; to: string } | null;
};

export type ChecklistItem = { key: string; done: boolean; href: string };
export type Gstr1Row = { instance_id: string; period_label: string; due_date?: string | null; due_date_confirmed: boolean };
/** The parts of the return build the path reads (GET …/returns/{instance}). */
export type Gstr1Build = {
  members_count: number;
  findings: { code: string; level: "block" | "warn" | "info"; accepted: boolean }[];
  export: { to_accept: number };
};

/** M3's setup steps, in order, with the button each one gets when it is the current step. */
export const SETUP: Record<string, { label: string; action: string; optional?: boolean }> = {
  business_profile: { label: "Business details", action: "Fill in your business details" },
  filing_frequency: { label: "Filing frequency", action: "Choose how often you file" },
  marketplaces: { label: "Marketplaces you sell on", action: "Choose your marketplaces" },
  first_product: { label: "Add your first product", action: "Add your first product" },
  first_customer: { label: "Add your first customer", action: "Add your first customer" },
  invite_ca_or_teammate: { label: "Invite your CA or a teammate", action: "Invite your CA or a teammate", optional: true },
};

/** The check that asks for Table 13; it is its own step on the path, not one of the things to fix. */
export const TABLE13_CHECK = "C-08";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Whole days from `today` to `day` (both YYYY-MM-DD); negative when `day` has passed. */
export function daysUntil(day: string, today: string): number {
  return Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

export function dueWords(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days > 1) return `in ${days} days`;
  return days === -1 ? "1 day ago" : `${-days} days ago`;
}

function setupPath(items: ChecklistItem[], businessId: string): NextStep {
  const known = items.filter((i) => i.key in SETUP);
  const current = known.findIndex((i) => !i.done);
  const at = known[current];
  const to = at ? screenPath(at.href, businessId) : null;
  return {
    kind: "setup",
    title: "Finish setting up your business",
    hint: "Your business is saved. A few more details and your deadlines are ready.",
    steps: known.map((i, n) => ({ label: SETUP[i.key].label, sub: SETUP[i.key].optional ? "Optional" : undefined, state: i.done ? "done" : n === current ? "cur" : "todo" })),
    current,
    action: at && to ? { label: SETUP[at.key].action, to } : null,
  };
}

/**
 * The GSTR-1 path: sales gathered, fix what the checks found, confirm documents issued
 * (Table 13), make the file, file on the portal and mark it filed. `fileTaken` is whether a
 * file was made for this return (null when this role can't ask). Without the build, the steps
 * are listed and the button opens the return.
 */
function gstr1Path(row: Gstr1Row, build: Gstr1Build | undefined, fileTaken: boolean | null, businessId: string, today: string, canUpload: boolean): NextStep {
  const ret = `/b/${businessId}/filing/${row.instance_id}`;
  const due = row.due_date && row.due_date_confirmed ? row.due_date : null;
  const hint = `${due ? `Due ${formatDate(due)}, ${dueWords(daysUntil(due, today))}. ` : ""}You file it on the GST portal yourself; we prepare the file.`;
  const base = { kind: "gstr1" as const, title: `Get your ${row.period_label} GSTR-1 file ready`, hint };
  const labels = ["Sales gathered", "Fix what the checks found", "Confirm documents issued", "Make the file", "File on the portal, then mark it filed"];
  if (!build) {
    return { ...base, steps: labels.map((label) => ({ label, state: "todo" })), current: -1, action: { label: "Open the return", to: ret } };
  }
  const toFix = build.findings.filter((f) => f.level === "block" && f.code !== TABLE13_CHECK).length + build.export.to_accept;
  const table13 = !build.findings.some((f) => f.code === TABLE13_CHECK);
  const done = [build.members_count > 0, toFix === 0, table13, fileTaken === true, false];
  const subs = [
    build.members_count > 0 ? plural(build.members_count, "invoice or note", "invoices and notes") : "None found yet",
    toFix > 0 ? `${toFix} to fix` : "Nothing to fix",
    "Table 13",
    "JSON for the portal",
    "You file it yourself",
  ];
  const current = done.findIndex((d) => !d);
  const actions = [
    canUpload ? { label: "Upload your reports", to: `/b/${businessId}/uploads` } : { label: "Open the return", to: ret },
    { label: toFix === 1 ? "Fix 1 thing" : `Fix ${toFix} things`, to: ret },
    { label: "Confirm documents issued", to: ret },
    { label: "Make the file", to: ret },
    { label: "Mark it filed", to: ret },
  ];
  return {
    ...base,
    steps: labels.map((label, i) => ({ label, sub: subs[i], state: done[i] ? "done" : i === current ? "cur" : "todo" })),
    current,
    action: actions[current] ?? null,
    // No sales found: the seller may simply have had none. The return page takes a nil return through the same steps.
    alt: current === 0 && canUpload ? { label: `No sales in ${row.period_label}? Go on to a nil return`, to: ret } : null,
  };
}

/**
 * Which card Home shows. Setup comes first while a step that isn't optional is still to do;
 * then the earliest GSTR-1 still open; otherwise there is nothing waiting.
 */
export function nextStep(input: {
  businessId: string;
  today: string;
  checklist: ChecklistItem[];
  gstr1?: Gstr1Row | null;
  build?: Gstr1Build;
  fileTaken?: boolean | null;
  canUpload?: boolean;
  canInvoice?: boolean;
}): NextStep {
  const { businessId, checklist } = input;
  if (checklist.some((i) => i.key in SETUP && !i.done && !SETUP[i.key].optional)) return setupPath(checklist, businessId);
  if (input.gstr1) return gstr1Path(input.gstr1, input.build, input.fileTaken ?? null, businessId, input.today, !!input.canUpload);
  return {
    kind: "clear",
    title: "Nothing is waiting for you",
    hint: "Your setup is done and no return needs you right now.",
    steps: [],
    current: -1,
    action: input.canInvoice ? { label: "New invoice", to: `/b/${businessId}/invoices/new` } : null,
  };
}

export type Marker = { key: string; label: string; day: string; due: boolean };

/**
 * The month timeline: today and the confirmed GSTR-1 and GSTR-3B due dates (national calendar,
 * from the server). Only confirmed dates are drawn; a marker outside this month stays in the
 * list but not on the track.
 */
export function timeline(today: string, rows: { form: string; due_date?: string | null; due_date_confirmed: boolean }[]) {
  const [y, m] = today.split("-").map(Number);
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const markers: Marker[] = [{ key: "today", label: "Today", day: today, due: false }];
  for (const [form, label] of [["GSTR1", "GSTR-1"], ["GSTR3B", "GSTR-3B"]] as const) {
    const r = rows.find((x) => x.form === form);
    if (r?.due_date && r.due_date_confirmed) markers.push({ key: form, label, day: r.due_date, due: true });
  }
  const month = today.slice(0, 7);
  const at = (day: string) => (Number(day.slice(8, 10)) - 1) / Math.max(daysInMonth - 1, 1);
  return {
    month: new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en-IN", { month: "long", timeZone: "UTC" }),
    markers,
    onTrack: markers.filter((k) => k.day.slice(0, 7) === month).map((k) => ({ ...k, at: at(k.day) })),
    todayAt: at(today),
  };
}

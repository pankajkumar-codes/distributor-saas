import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText, type ApiError } from "../../api/errors";
import { useStateCodes } from "../../api/useStateCodes";
import { canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, formatDateTimeIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { Loading } from "../../kit/Loading";
import { NoAccess } from "../../kit/NoAccess";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { Pager } from "../../kit/Pager";
import { Tabs } from "../../kit/Tabs";
import { TopBar } from "../../kit/TopBar";
import { LedgerHead } from "../filing/ledger";
import { useDecide, useHeldRows, useRun, type Action, type HeldRow } from "./useHeldRows";

const NOTE_MAX = 500;
/** The server's own sentence for a refused decision (its rules are written in plain words); the generic text for anything else. */
const said = (e: ApiError) => (e.status >= 400 && e.status < 500 && e.status !== 429 && e.code !== "session_invalid" && e.message ? e.message : errorText(e));
const CELLS: [string, string][] = [
  ["invoice_number", "Invoice"],
  ["invoice_date", "Invoice date"],
  ["order_id", "Order"],
  ["buyer_gstin", "Buyer GSTIN (Bill To)"],
  ["ship_to_state", "Ship To state"],
  ["hsn", "HSN"],
  ["taxable_value", "Taxable value"],
  ["invoice_amount", "Invoice amount"],
];
const MONEY = new Set(["taxable_value", "invoice_amount"]);
const shown = (key: string, v: string) => (MONEY.has(key) ? formatRupees(v) : key === "invoice_date" && /^\d{4}-\d{2}-\d{2}/.test(v) ? formatDate(v.slice(0, 10)) : v);
const ACTION_NAME: Record<string, string> = { set_aside: "Left out", accept: "Used as the file states it", enter_hsn: "HSN entered", pick_state: "State picked" };

/** Reuses one Idempotency-Key for an unchanged decision (a retry after a dropped answer), a new one when anything changes. */
function useKey() {
  const last = useRef<{ payload: string; key: string }>({ payload: "", key: "" });
  return (payload: string) => {
    if (last.current.payload !== payload) last.current = { payload, key: crypto.randomUUID() };
    return last.current.key;
  };
}

/**
 * Held rows of one uploaded file (#369, D-102). The server lists each row with its reason, effect note, CA flag and
 * the actions it offers; this page offers exactly those and shows the server's words for anything it refuses.
 * Nothing about states, HSNs or tax is decided here. A decision is kept with its note and cannot be changed.
 */
export function HeldRowsPage() {
  const { businessId = "", runId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canViewUploads(business.role));
  const run = useRun(businessId, runId, allowed);
  const rows = useHeldRows(businessId, runId, allowed);
  const states = useStateCodes();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState(false);
  const [tab, setTab] = useState(0);
  const [pages, setPages] = useState<Record<number, number>>({}); // the page each reason tab is on

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || run.error?.status === 404 || rows.error?.status === 404) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;

  const mayDecide = canUpload(business.role);
  const closed = run.data ? run.data.status !== "staged" : false;
  const open = mayDecide && !closed;
  const list: HeldRow[] = rows.data?.flatMap((p) => p.rows) ?? [];
  const undecided = list.filter((r) => !r.resolution);
  const caRows = list.filter((r) => r.needs_ca_check);
  const groups = [...new Set(list.map((r) => r.reason_label ?? "Other"))].map((label) => ({ label, rows: list.filter((r) => (r.reason_label ?? "Other") === label) }));
  const toggle = (id: string) =>
    setSelected((prev) => {
      const out = new Set(prev);
      if (out.has(id)) out.delete(id);
      else out.add(id);
      return out;
    });
  const chosen = undecided.filter((r) => selected.has(r.row_id));

  const tabs = groups.map((g, i) => {
    const left = g.rows.filter((r) => !r.resolution).length;
    return {
      key: String(i),
      label: (
        <>
          {g.label} <span className={`chip ${left > 0 ? "chip-warn" : "chip-ok"}`}>{left > 0 ? `${left} to decide` : "Decided"}</span>
        </>
      ),
      panel: (
        <GroupRows
          label={g.label}
          rows={g.rows}
          page={pages[i] ?? 0}
          onPage={(p) => setPages((cur) => ({ ...cur, [i]: p }))}
          render={(r) => (
            <HeldRowCard
              key={r.row_id}
              businessId={businessId}
              runId={runId}
              row={r}
              open={open}
              bulk={bulk}
              states={states.data ?? []}
              ticked={selected.has(r.row_id)}
              onTick={() => toggle(r.row_id)}
            />
          )}
        />
      ),
    };
  });
  const at = Math.min(tab, Math.max(tabs.length - 1, 0));
  // Selected rows the person cannot see now (on another tab or page): the bulk step names their reasons (#419).
  const inView = new Set(groups[at] ? pageOf(groups[at].rows, pages[at] ?? 0).map((r) => r.row_id) : []);
  const hidden = chosen.filter((r) => !inView.has(r.row_id));
  const closeBulk = () => {
    setBulk(false);
    setSelected(new Set()); // a closed bulk step keeps no selection (#419)
  };

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide ledger">
        <LedgerHead
          trail={
            <>
              <Link to={`/b/${businessId}/filing`}>GST filing</Link> / <Link to={`/b/${businessId}/uploads`}>Upload your reports</Link> / Held rows
            </>
          }
          title={
            <>
              Held rows {rows.data && <span className="muted num">{undecided.length}</span>}
            </>
          }
          lead="Rows we could not use as the file states them. Decide each one; every choice is kept with its note, and your file is never changed."
          actions={
            <>
              {open && undecided.length > 0 && (
                <Button type="button" variant="secondary" aria-expanded={bulk} onClick={() => (bulk ? closeBulk() : setBulk(true))}>
                  Decide several rows
                </Button>
              )}
              <Link className="btn btn-secondary" to={`/b/${businessId}/uploads`}>
                Back to uploads
              </Link>
            </>
          }
        />
        {(run.isPending || rows.isPending) && !run.error && !rows.error && <Loading query={rows.isPending ? rows : run} />}
        {(run.error || rows.error) && (
          <Banner tone="error">
            We couldn't load these rows. {errorText((run.error ?? rows.error) as ApiError)}{" "}
            <Button type="button" variant="link" onClick={() => { void run.refetch(); void rows.refetch(); }}>
              Try again
            </Button>
          </Banner>
        )}
        {caRows.length > 0 && (
          <Banner tone="warn">
            <b>Needs a CA check.</b> How these rows are treated is not yet confirmed by a chartered accountant. Your choice and note are kept for your CA to review.
          </Banner>
        )}
        {closed && <Banner>This file's preview is closed, so its rows can't be changed.</Banner>}
        {!closed && !mayDecide && rows.data && list.length > 0 && <Banner>Only an owner or admin can decide these rows.</Banner>}
        {rows.data && list.length === 0 && (
          <section className="panel">
            <p className="pad">No rows are held. Nothing to decide.</p>
          </section>
        )}
        {open && bulk && undecided.length > 0 && (
          <BulkBar
            businessId={businessId}
            runId={runId}
            chosen={chosen}
            hidden={hidden}
            total={undecided.length}
            states={states.data ?? []}
            onAll={() => setSelected(new Set(undecided.map((r) => r.row_id)))}
            onNone={() => setSelected(new Set())}
            onDone={() => setSelected(new Set())}
          />
        )}
        {tabs.length > 0 && <Tabs label="Why the rows are held" tabs={tabs} current={at} onChange={setTab} keepMounted />}
        {rows.hasNextPage && (
          <div className="toolbar">
            <Button type="button" variant="secondary" className="btn-sm" busy={rows.isFetchingNextPage} onClick={() => rows.fetchNextPage()}>
              Show more rows
            </Button>
          </div>
        )}
      </main>
    </>
  );
}

const HELD_PAGE = 2; // held rows a page, so a group with its decide form stays on one laptop screen

const lastPage = (rows: HeldRow[]) => Math.max(Math.ceil(rows.length / HELD_PAGE) - 1, 0);
/** The rows shown on a page of one reason's tab. */
const pageOf = (rows: HeldRow[], page: number) => {
  const at = Math.min(page, lastPage(rows));
  return rows.slice(at * HELD_PAGE, (at + 1) * HELD_PAGE);
};

/** "Bill To and Ship To in different states (2), HSN missing (1)": the reasons of some rows, with counts. */
function reasonsOf(rows: HeldRow[]): string {
  const count = new Map<string, number>();
  for (const r of rows) count.set(r.reason_label ?? "Other", (count.get(r.reason_label ?? "Other") ?? 0) + 1);
  return [...count].map(([label, n]) => `${label} (${n})`).join(", ");
}

/** One reason's rows, a page at a time. */
function GroupRows({ label, rows, page, onPage, render }: { label: string; rows: HeldRow[]; page: number; onPage: (p: number) => void; render: (r: HeldRow) => ReactNode }) {
  const at = Math.min(page, lastPage(rows));
  const slice = pageOf(rows, page);
  return (
    <section className="panel" aria-label={label}>
      <ul className="list held-rows">{slice.map(render)}</ul>
      {rows.length > HELD_PAGE && <Pager page={at} size={HELD_PAGE} shown={slice.length} total={rows.length} noun="rows" onPage={onPage} />}
    </section>
  );
}

type StateOption = { code: string; name: string };
const stateOptions = (states: StateOption[]) => states.map((s) => ({ value: s.code, label: `${s.name} (${s.code})` }));

function HeldRowCard({ businessId, runId, row, open, bulk, states, ticked, onTick }: { businessId: string; runId: string; row: HeldRow; open: boolean; bulk: boolean; states: StateOption[]; ticked: boolean; onTick: () => void }) {
  const decided = row.resolution;
  const cells = CELLS.filter(([k]) => row.values[k]);
  const label = `Row ${row.row_number} of ${row.file_name}`;
  return (
    <li className="held-row">
      <div className="held-h">
        <h3>
          {open && bulk && !decided && <input type="checkbox" checked={ticked} onChange={onTick} aria-label={`Select ${label}`} />} {label}
        </h3>
        {decided ? <span className="chip chip-ok">Decided</span> : row.needs_ca_check && <span className="chip chip-warn">Needs a CA check</span>}
      </div>
      {cells.length > 0 && (
        <dl className="facts">
          {cells.map(([k, name]) => (
            <div key={k}>
              <dt>{name}</dt>
              <dd className="num">{shown(k, row.values[k])}</dd>
            </div>
          ))}
        </dl>
      )}
      {row.ca_check_note && !bulk && <p className="hint">{row.ca_check_note}</p>}
      {decided ? (
        <p role="status">
          <b>{ACTION_NAME[decided.action] ?? decided.action}</b>
          {decided.value ? `: ${decided.value}` : ""} · {formatDateTimeIst(decided.at)}
          <br />
          <span className="hint">Your note: {decided.note}</span>
        </p>
      ) : (
        <>
          {open && !bulk && row.allowed_actions.length > 0 && <Decide businessId={businessId} runId={runId} row={row} states={states} />}
        </>
      )}
    </li>
  );
}

function Decide({ businessId, runId, row, states }: { businessId: string; runId: string; row: HeldRow; states: StateOption[] }) {
  const [action, setAction] = useState<Action | null>(null);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<{ field: string; message: string }>();
  const [sure, setSure] = useState(false);
  const decide = useDecide(businessId, runId);
  const keyFor = useKey();
  const offered = row.allowed_actions.find((a) => a.action === action);

  const pick = (a: Action) => {
    setAction(a);
    setProblem(undefined);
    setSure(false);
    decide.reset();
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!action) return;
    const needsValue = action === "pick_state" || action === "enter_hsn";
    if (needsValue && !value.trim()) return setProblem({ field: "value", message: action === "pick_state" ? "Choose a state." : "Enter an HSN." });
    if (!note.trim()) return setProblem({ field: "note", message: "Add a note saying why." });
    if (note.length > NOTE_MAX) return setProblem({ field: "note", message: `Keep the note to ${NOTE_MAX} characters.` });
    if (action === "set_aside" && !sure) return setSure(true);
    setProblem(undefined);
    const v = needsValue ? value.trim() : undefined;
    decide.mutate({ rowId: row.row_id, action, note: note.trim(), value: v, key: keyFor(`${row.row_id}|${action}|${v ?? ""}|${note.trim()}`) });
  };
  const err = decide.error as ApiError | null;
  const fieldErr = (f: string) => (problem?.field === f ? problem.message : err?.field === f ? said(err) : undefined);

  return (
    <div className="stack">
      <div className="row">
        {row.allowed_actions.map((a) => (
          <Button key={a.action} type="button" className="btn-sm" variant={a.action === "set_aside" ? "secondary" : "primary"} aria-pressed={action === a.action} onClick={() => pick(a.action)}>
            {a.label}
          </Button>
        ))}
      </div>
      {action && offered && (
        <form onSubmit={submit} noValidate aria-label={offered.label} className="f-line">
          {action === "pick_state" && (
            <SelectField label="Place of supply" placeholder="Choose a state…" options={stateOptions(states)} value={value} onChange={(e) => setValue(e.target.value)} error={fieldErr("value")} />
          )}
          {action === "enter_hsn" && <Field label="HSN" inputMode="numeric" value={value} onChange={(e) => setValue(e.target.value)} hint="4, 6 or 8 digits." error={fieldErr("value")} />}
          <Field label="Note (why)" value={note} maxLength={NOTE_MAX} onChange={(e) => setNote(e.target.value)} error={fieldErr("note")} />
          <p className="hint">{offered.effect_note}</p>
          {err && !err.field && <Banner tone="error">{said(err)}</Banner>}
          {err && err.field && !["value", "note"].includes(err.field) && <Banner tone="error">{said(err)}</Banner>}
          <Button type="submit" variant={action === "set_aside" ? "danger" : "primary"} busy={decide.isPending}>
            {action === "set_aside" ? (sure ? "Yes, leave it out" : "Leave this row out") : action === "pick_state" ? "Use this state" : action === "enter_hsn" ? "Use this HSN" : "Use the row as it is"}
          </Button>
        </form>
      )}
    </div>
  );
}

function BulkBar({ businessId, runId, chosen, hidden, total, states, onAll, onNone, onDone }: { businessId: string; runId: string; chosen: HeldRow[]; hidden: HeldRow[]; total: number; states: StateOption[]; onAll: () => void; onNone: () => void; onDone: () => void }) {
  const [action, setAction] = useState<"pick_state" | "set_aside">("pick_state");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<string>();
  const [result, setResult] = useState<{ done: number; failed: { row: HeldRow; message: string }[] }>();
  const [busy, setBusy] = useState(false);
  const [sure, setSure] = useState(false);
  const decide = useDecide(businessId, runId);
  const keys = useRef(new Map<string, string>());
  const every = (a: string) => chosen.length > 0 && chosen.every((r) => r.allowed_actions.some((x) => x.action === a));
  const canPick = every("pick_state");
  const canAside = every("set_aside");
  const effective = action === "pick_state" && !canPick && canAside ? "set_aside" : action;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (effective === "pick_state" && !value) return setProblem("Choose a state.");
    if (!note.trim()) return setProblem("Add a note saying why.");
    if (note.length > NOTE_MAX) return setProblem(`Keep the note to ${NOTE_MAX} characters.`);
    setProblem(undefined);
    if (effective === "set_aside" && !sure) return setSure(true);
    setSure(false);
    setBusy(true);
    const failed: { row: HeldRow; message: string }[] = [];
    let done = 0;
    for (const row of chosen) {
      const id = `${row.row_id}|${effective}|${effective === "pick_state" ? value : ""}|${note.trim()}`;
      if (!keys.current.has(id)) keys.current.set(id, crypto.randomUUID());
      try {
        await decide.mutateAsync({ rowId: row.row_id, action: effective, note: note.trim(), value: effective === "pick_state" ? value : undefined, key: keys.current.get(id) ?? "" });
        done += 1;
      } catch (err) {
        failed.push({ row, message: said(err as ApiError) });
      }
    }
    setBusy(false);
    setResult({ done, failed });
    if (failed.length === 0) {
      setNote("");
      setValue("");
      onDone();
    }
  };

  return (
    <section className="panel bulk" aria-label="Decide several rows">
      <div className="panel-h">
        <h2>Decide several rows</h2>
        <span className="row-actions">
          <span className="chip">{chosen.length} selected</span>
          <Button type="button" variant="secondary" className="btn-sm" onClick={onAll}>
            Select all {total}
          </Button>
          <Button type="button" variant="secondary" className="btn-sm" onClick={onNone} disabled={chosen.length === 0}>
            Clear
          </Button>
        </span>
      </div>
      {chosen.length === 0 && <p className="pad hint">Tick the rows to decide together, or select all. Pick rows of one kind.</p>}
      {chosen.length > 0 && !canPick && !canAside && <p className="pad hint">The selected rows don't offer the same action. Select rows of one kind.</p>}
      {chosen.length > 0 && (canPick || canAside) && (
        <form onSubmit={submit} noValidate aria-label="Decide the selected rows" className="pad f-line">
          <div className="field">
            <label htmlFor="bulk-action">What to do</label>
            <select id="bulk-action" value={effective} onChange={(e) => { setAction(e.target.value as "pick_state" | "set_aside"); setSure(false); }}>
              {canPick && <option value="pick_state">Pick one state for the selected rows</option>}
              {canAside && <option value="set_aside">Leave the selected rows out</option>}
            </select>
          </div>
          {effective === "pick_state" && <SelectField label="Place of supply" placeholder="Choose a state…" options={stateOptions(states)} value={value} onChange={(e) => setValue(e.target.value)} />}
          <Field label="Note (why)" value={note} maxLength={NOTE_MAX} onChange={(e) => setNote(e.target.value)} error={problem} />
          {(hidden.length > 0 || effective === "set_aside") && (
            <p className="hint">
              {hidden.length > 0 && (
                <>
                  {hidden.length === 1 ? "1 selected row is" : `${hidden.length} selected rows are`} not on screen: {reasonsOf(hidden)}.{" "}
                </>
              )}
              {effective === "set_aside" && "Leaving rows out cannot be undone: to bring one back, discard this file and upload it again."}
            </p>
          )}
          <Button type="submit" variant={effective === "set_aside" ? "danger" : "primary"} busy={busy}>
            {effective === "pick_state" ? `Use this state for ${chosen.length} row${chosen.length === 1 ? "" : "s"}` : sure ? `Yes, leave ${chosen.length} row${chosen.length === 1 ? "" : "s"} out` : `Leave ${chosen.length} row${chosen.length === 1 ? "" : "s"} out`}
          </Button>
        </form>
      )}
      {result && (
        <Banner tone={result.failed.length > 0 ? "error" : "info"}>
          {result.done} row{result.done === 1 ? "" : "s"} decided.
          {result.failed.length > 0 && (
            <>
              {" "}
              {result.failed.length} could not be decided:
              <ul>
                {result.failed.map((f) => (
                  <li key={f.row.row_id}>
                    Row {f.row.row_number} of {f.row.file_name}: {f.message}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Banner>
      )}
    </section>
  );
}

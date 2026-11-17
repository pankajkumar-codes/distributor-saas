import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText } from "../../api/errors";
import type { components } from "../../api/schema";
import { canPrepareReturns } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate } from "../../format/dates";
import { formatRate, formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { ExportPanel } from "./ExportPanel";
import { useAccept } from "./export";
import { FiledPanel } from "./FiledPanel";
import { returnKey, useReturnDetail, useSectionRows, type SectionName } from "./returns";

type Heads = components["schemas"]["Heads"];
type Group = components["schemas"]["FindingGroupOut"];
type Finding = components["schemas"]["FindingOut"];

const FORM: Record<string, string> = { GSTR1: "GSTR-1", IFF: "Invoice furnishing facility (IFF)" };

/** What a business owner reads for each check the server runs. The code stays as a small tag, never the only label. */
const CHECKS: Record<string, string> = {
  "C-01": "HSN code missing",
  "C-02": "Customer GSTIN not valid",
  "C-03": "Invoice number too long or has characters the portal rejects",
  "C-04": "Same invoice number used more than once",
  "C-05": "Place of supply is not a known state",
  "C-10": "HSN code has too few digits",
  "C-12": "Net sales to consumers in one state came out negative",
  "C-16": "Rules not yet confirmed by a CA",
  "A-01": "Tax does not equal taxable value times rate",
  "A-02": "Tax heads do not fit the place of supply",
  "A-03": "CGST and SGST are not equal",
  "A-04": "Invoice number also used in another financial year",
};
const LEVEL: Record<string, { label: string; chip: string; order: number }> = {
  block: { label: "Look at this first", chip: "chip chip-bad", order: 0 },
  warn: { label: "Please check", chip: "chip chip-warn", order: 1 },
  info: { label: "For your information", chip: "chip chip-info", order: 2 },
};

const SECTIONS: { name: SectionName; title: string; hint: string }[] = [
  { name: "b2b", title: "Sales to businesses (B2B)", hint: "Table 4A: one row per invoice and tax rate." },
  { name: "b2cl", title: "Large inter-state sales to consumers (B2CL)", hint: "Table 5: one row per invoice and tax rate." },
  { name: "b2cs", title: "Other sales to consumers (B2CS)", hint: "Table 7: one row per state and tax rate." },
  { name: "cdnr", title: "Credit notes to businesses", hint: "Table 9B: one row per note and tax rate." },
  { name: "cdnur", title: "Credit notes to consumers", hint: "Table 9B: notes against large inter-state consumer sales." },
  { name: "hsn_b2b", title: "HSN summary: business sales", hint: "Table 12: one row per HSN, unit and rate." },
  { name: "hsn_b2c", title: "HSN summary: consumer sales", hint: "Table 12: one row per HSN, unit and rate." },
];

type Kind = "text" | "date" | "money" | "rate";
type Col = { label: string; key: string; kind: Kind };
const col = (label: string, key: string, kind: Kind = "text"): Col => ({ label, key, kind });
const TAX = [col("Taxable value", "taxable_value", "money"), col("IGST", "igst", "money"), col("CGST", "cgst", "money"), col("SGST", "sgst", "money"), col("Cess", "cess", "money")];
const COLUMNS: Record<SectionName, Col[]> = {
  b2b: [col("Invoice", "invoice_number"), col("Date", "invoice_date", "date"), col("Customer", "recipient_name"), col("GSTIN", "recipient_gstin"), col("Invoice value", "invoice_value", "money"), col("State code", "pos_state_code"), col("Rate", "rate", "rate"), ...TAX],
  b2cl: [col("Invoice", "invoice_number"), col("Date", "invoice_date", "date"), col("Invoice value", "invoice_value", "money"), col("State code", "pos_state_code"), col("Rate", "rate", "rate"), ...TAX],
  b2cs: [col("State code", "pos_state_code"), col("Rate", "rate", "rate"), ...TAX],
  cdnr: [col("Note", "note_number"), col("Date", "note_date", "date"), col("Customer", "recipient_name"), col("GSTIN", "recipient_gstin"), col("Note value", "note_value", "money"), col("Against invoice", "original_doc_number"), col("Rate", "rate", "rate"), ...TAX],
  cdnur: [col("Note", "note_number"), col("Date", "note_date", "date"), col("Note value", "note_value", "money"), col("Against invoice", "original_doc_number"), col("Rate", "rate", "rate"), ...TAX],
  hsn_b2b: [col("HSN", "hsn"), col("Unit", "uqc"), col("Rate", "rate", "rate"), col("Quantity", "quantity"), ...TAX],
  hsn_b2c: [col("HSN", "hsn"), col("Unit", "uqc"), col("Rate", "rate", "rate"), col("Quantity", "quantity"), ...TAX],
};

function show(value: unknown, kind: Kind): string {
  if (value === null || value === undefined || value === "") return "—";
  const s = String(value);
  return kind === "money" ? formatRupees(s) : kind === "rate" ? formatRate(s) : kind === "date" ? formatDate(s) : s;
}

function HeadsLine({ heads }: { heads: Heads }) {
  return (
    <dl className="totals">
      {(
        [
          ["Taxable value", heads.taxable_value],
          ["IGST", heads.igst],
          ["CGST", heads.cgst],
          ["SGST", heads.sgst],
          ["Cess", heads.cess],
        ] as const
      ).map(([label, v]) => (
        <div className="row" key={label}>
          <dt>{label}</dt>
          <dd>{formatRupees(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function FindingGroup({ group, findings, businessId, instanceId, canAccept }: { group: Group; findings: Finding[]; businessId: string; instanceId: string; canAccept: boolean }) {
  const level = LEVEL[group.level] ?? LEVEL.info;
  const mine = findings.filter((f) => f.code === group.code);
  const accept = useAccept(businessId, instanceId);
  const [note, setNote] = useState("");
  const waiting = group.level === "warn" ? group.count - group.accepted : 0;
  return (
    <details className="card" open={group.level === "block"}>
      <summary>
        <b>{CHECKS[group.code] ?? "Check"}</b> <span className="tag">{group.code}</span>{" "}
        <span className={level.chip}>{level.label}</span> <span className="chip">{group.count === 1 ? "1 item" : `${group.count} items`}</span>
        {group.needs_ca_check && <span className="chip chip-warn">Needs a CA check</span>}
        {group.level === "warn" && waiting === 0 && <span className="chip chip-ok">Accepted</span>}
      </summary>
      <ul>
        {mine.map((f) => (
          <li key={f.subject_fp}>
            {f.message}
            {f.source_refs.length > 0 && <span className="hint"> From {f.source_refs.join(", ")}.</span>}
            {f.level === "warn" && f.accepted && <span className="chip chip-ok">Accepted</span>}
          </li>
        ))}
      </ul>
      {group.level === "block" && <p className="hint">This has to be fixed in your uploads. It can't be accepted.</p>}
      {canAccept && waiting > 0 && (
        <form
          className="stack"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            accept.mutate({ check_code: group.code, note: note.trim() });
          }}
        >
          <Field label="Why is this fine to file as it is?" value={note} onChange={(e) => setNote(e.target.value)} hint="Your reason is kept with the return. If these rows change later you will be asked again." />
          {accept.isError && <Banner tone="error">{errorText(accept.error)}</Banner>}
          <Button type="submit" variant="secondary" busy={accept.isPending} disabled={!note.trim()}>
            Accept as shown
          </Button>
        </form>
      )}
    </details>
  );
}

function Section({ businessId, instanceId, name, title, hint, count, fingerprint }: { businessId: string; instanceId: string; name: SectionName; title: string; hint: string; count: number; fingerprint: string }) {
  const [open, setOpen] = useState(false);
  const rows = useSectionRows(businessId, instanceId, name, open && count > 0);
  const queryClient = useQueryClient();
  const pages = rows.data?.pages ?? [];
  const changed = pages.some((p) => p.fingerprint !== fingerprint);
  const cols = COLUMNS[name];
  return (
    <details className="card" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <b>{title}</b> <span className="chip">{count === 1 ? "1 row" : `${count} rows`}</span>
      </summary>
      <p className="hint">{hint}</p>
      {count === 0 && <p>Nothing in this section for this period.</p>}
      {rows.isError && <Banner tone="error">We couldn't load these rows. {errorText(rows.error)}</Banner>}
      {changed ? (
        <Banner tone="error">
          This return changed while you were reading it, so these rows are not shown.{" "}
          <Button onClick={() => void queryClient.resetQueries({ queryKey: returnKey(businessId, instanceId) })}>Reload the return</Button>
        </Banner>
      ) : (
        pages.length > 0 && (
          <div className="tablewrap">
            <table className="products">
              <thead>
                <tr>
                  {cols.map((c) => (
                    <th scope="col" key={c.key}>{c.label}</th>
                  ))}
                  <th scope="col">Where it came from</th>
                </tr>
              </thead>
              <tbody>
                {pages.flatMap((p, i) =>
                  // The columns are table-driven per section, so the typed rows are read by key here.
                  (p.rows as unknown as Record<string, unknown>[]).map((r, j) => (
                    <tr key={`${i}-${j}`}>
                      {cols.map((c) => (
                        <td data-label={c.label} key={c.key}>{show(r[c.key], c.kind)}</td>
                      ))}
                      <td data-label="Where it came from">{(r.source_refs as string[]).join(", ")}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        )
      )}
      {!changed && rows.hasNextPage && (
        <Button onClick={() => void rows.fetchNextPage()} disabled={rows.isFetchingNextPage}>
          {rows.isFetchingNextPage ? "Loading…" : "Show more rows"}
        </Button>
      )}
      {open && rows.isPending && count > 0 && <p aria-busy="true">Loading…</p>}
    </details>
  );
}

/**
 * /b/:id/filing/:instanceId (R1-M7 S6). A read-only look at the return the server builds from the
 * confirmed uploads: what it contains, what the checks found and where each figure came from. It
 * files nothing and offers no download (that is R1-M8). Mocks v12/v13 show no such screen, only
 * the guide and the GSTR-3B worksheet, so this follows the design kit alone.
 */
export function ReturnPage() {
  const { businessId = "", instanceId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const detail = useReturnDetail(businessId, instanceId);

  if (businesses.isPending) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || (detail.isError && detail.error.status === 404)) return <NotFound />;
  const d = detail.data;
  const groups = [...(d?.finding_groups ?? [])].sort((a, b) => (LEVEL[a.level]?.order ?? 9) - (LEVEL[b.level]?.order ?? 9) || a.code.localeCompare(b.code));
  const blocking = groups.filter((g) => g.level === "block").reduce((n, g) => n + g.count, 0);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="step">
          <Link to={`/b/${businessId}/filing`}>Your GST filing</Link>
        </p>
        {detail.isPending && <p aria-busy="true">Loading…</p>}
        {detail.isError && <Banner tone="error">We couldn't load this return. {errorText(detail.error)}</Banner>}
        {d && (
          <>
            <h1>
              {FORM[d.instance.form] ?? d.instance.form} for {d.instance.period_label}
            </h1>
            {d.banner && <Banner>{d.banner}</Banner>}
            <p className="hint">
              This is a read-only look. Nothing is filed and nothing here changes your invoices. {d.line_items === 1 ? "1 line" : `${d.line_items} lines`} from {d.members_count === 1 ? "1 invoice or note" : `${d.members_count} invoices and notes`}.
            </p>
            {d.debit_notes.notice && <Banner tone="error">{d.debit_notes.notice}</Banner>}
            {d.ca_flags.length > 0 && (
              <section className="card" aria-labelledby="ca-flags">
                <h2 id="ca-flags">Rules waiting for a CA to confirm</h2>
                <ul>
                  {d.ca_flags.map((f) => (
                    <li key={f.code}>{f.text}</li>
                  ))}
                </ul>
              </section>
            )}
            <section className="card" aria-labelledby="totals">
              <h2 id="totals">Totals</h2>
              <h3>Tax in this return</h3>
              <HeadsLine heads={d.totals.liability} />
              <h3>Total of the HSN summary</h3>
              <HeadsLine heads={d.totals.table_12} />
              <h3>Difference between the two</h3>
              <HeadsLine heads={d.totals.gap} />
              <p className="hint">The difference should be nil when every sale has an HSN code.</p>
            </section>
            <section aria-labelledby="checks">
              <h2 id="checks">Checks</h2>
              {groups.length === 0 ? (
                <p>The checks found nothing to look at.</p>
              ) : (
                <>
                  {blocking > 0 && <Banner tone="error">{blocking === 1 ? "1 item" : `${blocking} items`} to look at first. Some of these checks rest on rules a CA has not confirmed yet.</Banner>}
                  {groups.map((g) => (
                    <FindingGroup key={g.code} group={g} findings={d.findings} businessId={businessId} instanceId={instanceId} canAccept={canPrepareReturns(business.role) && d.instance.status !== "filed_locked"} />
                  ))}
                </>
              )}
            </section>
            {d.export && d.instance.status !== "filed_locked" && <ExportPanel businessId={businessId} instanceId={instanceId} gate={d.export} fingerprint={d.fingerprint} />}
            <FiledPanel businessId={businessId} instance={d.instance} role={business.role} />
            <section aria-labelledby="sections">
              <h2 id="sections">What is in the return</h2>
              {SECTIONS.map((s) => {
                const info = d.sections.find((x) => x.name === s.name);
                return (
                  <div key={s.name}>
                    <Section businessId={businessId} instanceId={instanceId} name={s.name} title={s.title} hint={s.hint} count={info?.rows_count ?? 0} fingerprint={d.fingerprint} />
                    {info && info.rows_count > 0 && <p className="hint">Section total: {formatRupees(info.totals.taxable_value)} taxable, {formatRupees(info.totals.igst)} IGST, {formatRupees(info.totals.cgst)} CGST, {formatRupees(info.totals.sgst)} SGST.</p>}
                  </div>
                );
              })}
            </section>
          </>
        )}
      </main>
    </>
  );
}

import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { errorText, type ApiError } from "../../api/errors";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatDate, todayIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { useFormKey } from "../../kit/formKey";
import { Loading } from "../../kit/Loading";
import { NoAccess } from "../../kit/NoAccess";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { SelectField } from "../../kit/SelectField";
import { useSingleFlight } from "../../kit/singleFlight";
import { TopBar } from "../../kit/TopBar";
import { CancelForm } from "./CancelForm";
import { useCreateCreditNote, useCreditState, type CreditNoteIn } from "./useCredit";
import { useDocument } from "./useFinalize";

type Reason = CreditNoteIn["reason"];
// The server's own rule text for a refused note ("At most 2 can be credited on this line"), else the usual sentence.
const words = (e: ApiError) => e.fix ?? (e.status === 422 && e.message ? e.message : errorText(e));
type Stock = "restock" | "write_off";

/**
 * Adjust invoice (mocks v17, R.adjust; #456): a credit note against an issued invoice. Goods returned are credited by
 * quantity, a price that was too high or deficient goods by taxable value; never more than is left on a line. The
 * invoice itself never changes. The server works out every amount, the tax from the invoice's own rates and the
 * closing note takes the exact remainder, so the page shows only what is left and the note it made.
 */
export function AdjustPage() {
  const { businessId = "", documentId = "" } = useParams();
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [mode, setMode] = useState<"credit" | "cancel">(hash === "#cancel" ? "cancel" : "credit");
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const allowed = Boolean(business && canCreateDocuments(business.role));
  const doc = useDocument(businessId, documentId);
  const credit = useCreditState(businessId, documentId, allowed);
  const key = useFormKey(`credit-note:${documentId}`);
  const once = useSingleFlight();
  const [reason, setReason] = useState<Reason>("goods_returned");
  const [stock, setStock] = useState<Stock>("restock");
  const [date, setDate] = useState(todayIst());
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const create = useCreateCreditNote(businessId, documentId, key.current, (note) => {
    key.reset();
    navigate(`/b/${businessId}/documents/${note.id}`);
  });
  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!business) return <NotFound />;
  if (!allowed) return <NoAccess businessId={businessId} />;
  if (doc.error?.status === 404 || credit.error?.status === 404) return <NotFound />;
  const byQty = reason === "goods_returned";
  const s = credit.data;
  const lines = Object.entries(amounts)
    .filter(([, v]) => v.trim() !== "")
    .map(([id, v]) => (byQty ? { original_line_id: id, quantity: v.trim() } : { original_line_id: id, taxable: v.trim() }));
  const submit = () =>
    once((done) => {
      create
        .mutateAsync({ reason, stock_treatment: byQty ? stock : null, doc_date: date, lines })
        .catch(() => undefined)
        .finally(done);
    });
  const fieldError = create.error?.field;
  const docError = create.error && fieldError !== "doc_date" ? words(create.error) : null;
  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <p className="eyebrow">
          <Link to={`/b/${businessId}/documents`}>Sell / Issued invoices</Link> /{" "}
          <Link className="num" to={`/b/${businessId}/documents/${documentId}`}>
            {s?.doc_number ?? "Invoice"}
          </Link>{" "}
          / Adjust
        </p>
        <div className="between docact">
          <h1>
            Adjust invoice <span className="muted num">{s?.doc_number}</span>
          </h1>
          {s && !s.cancelled && (
            <RadioGroup<"credit" | "cancel">
              legend="What do you want to do?"
              name="adjust"
              value={mode}
              onChange={setMode}
              options={[
                { value: "credit", label: "Credit note", sub: "lowers what the buyer owes" },
                { value: "cancel", label: "Cancel the invoice", sub: "it should never have been made" },
              ]}
            />
          )}
        </div>
        {doc.data && (
          <p className="lead">
            {doc.data.counterparty_name ?? "Cash sale"} · {formatDate(doc.data.doc_date)} · {formatRupees(doc.data.doc_total)}. The invoice itself never
            changes. <Link to={`/b/${businessId}/documents/${documentId}`}>Back to the invoice</Link>
          </p>
        )}
        {(credit.isPending || doc.isPending) && <Loading query={credit.isPending ? credit : doc} />}
        {credit.error && credit.error.status !== 404 && <Banner tone="error">{errorText(credit.error)}</Banner>}
        {s?.cancelled && <Banner tone="info">This invoice is cancelled. It can't be adjusted again.</Banner>}
        {s && !s.cancelled && mode === "cancel" && s.notes.length > 0 && (
          <Banner tone="error">
            <strong>{s.doc_number} can't be cancelled.</strong> Credit note {s.notes[0].doc_number} already exists for it, and cancelling would undo a sale the note treats
            as made. Use a credit note instead.
          </Banner>
        )}
        {s && !s.cancelled && mode === "cancel" && s.notes.length === 0 && (
          <CancelForm businessId={businessId} documentId={documentId} number={s.doc_number} onCancelled={() => navigate(`/b/${businessId}/documents/${documentId}`)} />
        )}
        {s && !s.cancelled && mode === "credit" && s.remaining_total === "0.00" && (
          <Banner tone="info">This invoice has been credited in full. There is nothing left to credit.</Banner>
        )}
        {s && !s.cancelled && mode === "credit" && s.remaining_total !== "0.00" && (
          <>
            <div className="grid2 adjgrid">
              <section className="panel" aria-labelledby="what">
                <div className="panel-h">
                  <h2 id="what">What to credit</h2>
                  <span className="hint">{byQty ? "By quantity" : "By taxable value"}</span>
                </div>
                <div className="tablewrap">
                  <table className="products">
                    <thead>
                      <tr>
                        <th scope="col">Item</th>
                        <th scope="col" className="r">Left to credit</th>
                        <th scope="col" className="r">{byQty ? "Credit qty" : "Credit taxable (₹)"}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.lines.map((l) => {
                        const left = byQty ? l.remaining_quantity : l.remaining_taxable;
                        const full = byQty ? !l.remaining_quantity || /^0(\.0+)?$/.test(l.remaining_quantity) : !/[1-9]/.test(l.remaining_taxable);
                        return (
                          <tr key={l.original_line_id}>
                            <td data-label="Item" className="pname">
                              {l.name}
                              <div className="sub2 num">
                                HSN {l.hsn} · {l.rate}%
                              </div>
                            </td>
                            <td data-label="Left to credit" className="r num">
                              {left === null ? "—" : byQty ? `${left} ${l.uqc}` : formatRupees(left)}
                            </td>
                            <td data-label={byQty ? "Credit qty" : "Credit taxable"} className="r">
                              {full ? (
                                <span className="hint">Credited in full</span>
                              ) : (
                                <input
                                  className="qty num"
                                  inputMode="decimal"
                                  placeholder="0"
                                  aria-label={`${byQty ? "Quantity" : "Taxable value"} to credit, ${l.name}`}
                                  value={amounts[l.original_line_id] ?? ""}
                                  onChange={(e) => setAmounts({ ...amounts, [l.original_line_id]: e.target.value })}
                                />
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="pad">
                  <div className="kv">
                    <span>Left on the invoice now</span>
                    <span className="num">{formatRupees(s.remaining_total)}</span>
                  </div>
                  <p className="hint">The note's tax is worked out from the invoice's own rates when you create it.</p>
                </div>
              </section>
              <section className="panel pad" aria-label="Note details">
                <SelectField
                  label="Reason"
                  options={Object.entries(s.reasons).map(([value, label]) => ({ value, label }))}
                  value={reason}
                  onChange={(e) => {
                    if (!e.target.value) return;
                    setReason(e.target.value as Reason);
                    setAmounts({});
                  }}
                  hint="Only reasons the GST law allows."
                />
                {byQty && (
                  <RadioGroup<Stock>
                    legend="Returned goods"
                    name="stock"
                    value={stock}
                    onChange={setStock}
                    options={[
                      { value: "restock", label: "Back to stock" },
                      { value: "write_off", label: "Returned and written off" },
                    ]}
                  />
                )}
                <div className="f2">
                  <Field
                    label="Note date"
                    type="date"
                    value={date}
                    max={todayIst()}
                    onChange={(e) => setDate(e.target.value)}
                    error={fieldError === "doc_date" && create.error ? words(create.error) : undefined}
                  />
                  <Field label="Last date" value={formatDate(s.last_date)} disabled hint="Or your GSTR-9 date, if earlier" />
                </div>
                <Banner tone="warn">
                  Your tax goes down only if {doc.data?.counterparty_name ?? "the buyer"} reverses the matching input tax credit. We can't check that.
                </Banner>
              </section>
            </div>
            {docError && <Banner tone="error">{docError}</Banner>}
            <div className="adjbar">
              <Button type="button" variant="primary" busy={create.isPending} disabled={lines.length === 0} onClick={submit}>
                {s.is_practice ? "Create practice credit note" : "Create credit note"}
              </Button>
              <span className="hint">
                {s.is_practice
                  ? "Gets a PR-CN- number: practice, not in GST filing."
                  : "Gets the next number in your credit note series and goes in GSTR-1 for its month."}
                {byQty && stock === "restock" ? " Returned goods go back to stock." : ""}
              </span>
            </div>
          </>
        )}
        {s && mode === "credit" && s.notes.length > 0 && (
          <section className="panel" aria-labelledby="made">
            <div className="panel-h">
              <h2 id="made">Credit notes already made</h2>
            </div>
            <div className="pad">
              {s.notes.map((n) => (
                <div className="kv" key={n.id}>
                  <span>
                    <Link className="num" to={`/b/${businessId}/documents/${n.id}`}>
                      {n.doc_number}
                    </Link>{" "}
                    <span className="sub2">{formatDate(n.doc_date)}</span>
                  </span>
                  <span className="num">−{formatRupees(n.doc_total)}</span>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    </>
  );
}

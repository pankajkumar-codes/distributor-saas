import { useState } from "react";

import { errorText, type ApiError } from "../../api/errors";
import { formatRupees } from "../../format/money";
import { todayIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { useFormKey } from "../../kit/formKey";
import { SelectField } from "../../kit/SelectField";
import { useSingleFlight } from "../../kit/singleFlight";
import { useCreateDebitNote, type CreditState, type DebitNoteIn } from "./useCredit";
import type { Document } from "./useFinalize";

type Reason = DebitNoteIn["reason"];
const words = (e: ApiError) => e.fix ?? (e.status === 422 && e.message ? e.message : errorText(e));

/**
 * Debit note (mocks v17, R.adjust "Debit note"; #456 part 3, CGST s.34(3)): required when an invoice charged too little.
 * By taxable value for a value charged too low, by quantity for more goods sent than invoiced (at the line's own value
 * per unit; the goods leave stock). The server works out the tax from each line's own rate and has no cap.
 */
export function DebitForm({ businessId, documentId, state, onDone }: { businessId: string; documentId: string; state: CreditState; onDone: (note: Document) => void }) {
  const key = useFormKey(`debit-note:${documentId}`);
  const once = useSingleFlight();
  const reasons = state.debit_reasons ?? {};
  const [reason, setReason] = useState<Reason>("value_too_low");
  const [date, setDate] = useState(todayIst());
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const create = useCreateDebitNote(businessId, documentId, key.current, (note) => {
    key.reset();
    onDone(note);
  });
  const byQty = reason === "more_goods";
  const lines = Object.entries(amounts)
    .filter(([, v]) => v.trim() !== "")
    .map(([id, v]) => (byQty ? { original_line_id: id, quantity: v.trim() } : { original_line_id: id, taxable: v.trim() }));
  const submit = () =>
    once((done) => {
      create
        .mutateAsync({ reason, doc_date: date, lines })
        .catch(() => undefined)
        .finally(done);
    });
  const fieldError = create.error?.field;
  return (
    <>
      <div className="grid2 adjgrid">
        <section className="panel" aria-labelledby="what-add">
          <div className="panel-h">
            <h2 id="what-add">What to add</h2>
            <span className="hint">{byQty ? "By quantity" : "By taxable value"}</span>
          </div>
          <div className="tablewrap">
            <table className="products">
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col" className="r">
                    Invoiced
                  </th>
                  <th scope="col" className="r">
                    {byQty ? "Extra qty" : "Extra taxable (₹)"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {state.lines.map((l) => {
                  const noQty = byQty && !l.quantity;
                  return (
                    <tr key={l.original_line_id}>
                      <td data-label="Item" className="pname">
                        {l.name}
                        <div className="sub2 num">
                          HSN {l.hsn} · {l.rate}%
                        </div>
                      </td>
                      <td data-label="Invoiced" className="r num">
                        {byQty ? (l.quantity ? `${l.quantity} ${l.uqc}` : "—") : formatRupees(l.taxable)}
                      </td>
                      <td data-label={byQty ? "Extra qty" : "Extra taxable"} className="r">
                        {noQty ? (
                          <span className="hint">No quantity</span>
                        ) : (
                          <input
                            className="qty num"
                            inputMode="decimal"
                            placeholder="0"
                            aria-label={`${byQty ? "Extra quantity" : "Extra taxable value"}, ${l.name}`}
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
            <p className="hint">The note's tax is worked out from each line's own rate when you create it.</p>
          </div>
        </section>
        <section className="panel pad" aria-label="Debit note details">
          <SelectField
            label="Reason"
            options={Object.entries(reasons).map(([value, label]) => ({ value, label }))}
            value={reason}
            onChange={(e) => {
              if (!e.target.value) return;
              setReason(e.target.value as Reason);
              setAmounts({});
            }}
            hint={byQty ? "Enter the extra quantity sent. It is valued at the invoice's own price and leaves stock." : "Enter the taxable value you should have charged on top."}
          />
          <Field
            label="Note date"
            type="date"
            value={date}
            max={todayIst()}
            onChange={(e) => setDate(e.target.value)}
            error={fieldError === "doc_date" && create.error ? words(create.error) : undefined}
          />
          <Banner tone="info">Required when an invoice charged too little. Its tax goes in GSTR-1 and GSTR-3B for the note's month.</Banner>
        </section>
      </div>
      {create.error && fieldError !== "doc_date" && <Banner tone="error">{words(create.error)}</Banner>}
      <div className="adjbar">
        <Button type="button" variant="primary" busy={create.isPending} disabled={lines.length === 0} onClick={submit}>
          {state.is_practice ? "Create practice debit note" : "Create debit note"}
        </Button>
        <span className="hint">
          {state.is_practice ? "Gets a PR-DN- number: practice, not in GST filing." : "Gets the next number in your debit note series and goes in GSTR-1 Table 9B for its month."}
          {byQty ? " The extra goods leave stock." : ""}
        </span>
      </div>
    </>
  );
}

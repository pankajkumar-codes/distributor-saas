import { useState } from "react";

import { errorText, type ApiError } from "../../api/errors";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { useFormKey } from "../../kit/formKey";
import { RadioGroup } from "../../kit/RadioGroup";
import { useSingleFlight } from "../../kit/singleFlight";
import { useCancelInvoice, type CancelIn } from "./useCredit";

type Reason = CancelIn["reason"];
const words = (e: ApiError) => e.fix ?? (e.status === 422 && e.message ? e.message : errorText(e));

/**
 * Cancel the invoice (mocks v17, R.adjust "Cancel"; #456). Allowed while the invoice's GSTR-1 or IFF is not filed and no
 * credit or debit note exists; the server checks both. "Raised by mistake" and "did not happen" need the declaration that
 * the goods were not dispatched or delivered; a duplicate doesn't, but names the invoice it duplicates, which the server
 * checks exists and is not cancelled (GST CA wording check). The number stays used and the invoice stays in the records.
 */
export function CancelForm({ businessId, documentId, number, onCancelled }: { businessId: string; documentId: string; number: string; onCancelled: () => void }) {
  const key = useFormKey(`cancel:${documentId}`);
  const once = useSingleFlight();
  const [reason, setReason] = useState<Reason>("raised_in_error");
  const [declared, setDeclared] = useState(false);
  const [duplicateOf, setDuplicateOf] = useState("");
  const cancel = useCancelInvoice(businessId, documentId, key.current, () => {
    key.reset();
    onCancelled();
  });
  const needsDeclaration = reason !== "duplicate";
  const submit = () =>
    once((done) => {
      cancel
        .mutateAsync({ reason, declared_not_delivered: needsDeclaration ? declared : false, duplicate_of: reason === "duplicate" && duplicateOf.trim() ? duplicateOf.trim() : null })
        .catch(() => undefined)
        .finally(done);
    });
  return (
    <>
      <div className="grid2">
        <section className="panel pad" aria-label="Why cancel">
          <RadioGroup<Reason>
            legend="Why are you cancelling it?"
            name="cancel-reason"
            value={reason}
            onChange={setReason}
            options={[
              { value: "raised_in_error", label: "Raised by mistake" },
              { value: "duplicate", label: "Duplicate of another invoice" },
              { value: "did_not_happen", label: "The sale did not happen" },
            ]}
          />
          {needsDeclaration ? (
            <>
              <label className="radio">
                <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} /> I confirm the goods on this invoice were not dispatched
                or delivered to the buyer.
              </label>
              <p className="hint">If they were delivered, the sale happened: use a credit note instead.</p>
            </>
          ) : (
            <Field
              label="The invoice you are keeping"
              value={duplicateOf}
              onChange={(e) => setDuplicateOf(e.target.value)}
              hint="Its number, exactly as issued. It must not be cancelled."
              error={cancel.error?.field === "duplicate_of" ? words(cancel.error) : undefined}
            />
          )}
        </section>
        <section className="panel" aria-labelledby="what-cancel">
          <div className="panel-h">
            <h2 id="what-cancel">What cancel does</h2>
          </div>
          <div className="pad">
            <div className="kv">
              <span>Number</span>
              <span className="num">{number} stays used, never given again</span>
            </div>
            <div className="kv">
              <span>GSTR-1</span>
              <span>Counted as cancelled in Table 13, left out of Tables 4 to 12</span>
            </div>
            <div className="kv">
              <span>Stock</span>
              <span>The goods go back to stock, linked to this invoice</span>
            </div>
            <div className="kv">
              <span>Allowed until</span>
              <span>GSTR-1 (or IFF) holding this invoice is filed</span>
            </div>
            <Banner tone="warn">If you made an e-way bill for this invoice, cancel it on the e-way bill portal within 24 hours of making it, and before it
              is checked in transit.</Banner>
          </div>
        </section>
      </div>
      {cancel.error && cancel.error.field !== "duplicate_of" && <Banner tone="error">{words(cancel.error)}</Banner>}
      <div className="adjbar">
        <Button type="button" variant="danger" busy={cancel.isPending} disabled={needsDeclaration ? !declared : !duplicateOf.trim()} onClick={submit}>
          Cancel invoice {number}
        </Button>
        <span className="hint">The invoice and this cancellation stay in the audit log.</span>
      </div>
    </>
  );
}

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorText, type ApiError } from "../../api/errors";
import { canUpload, canViewUploads } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { PageHead } from "../../kit/PageHead";
import { Tabs } from "../../kit/Tabs";
import { codeAvailable, useActiveProducts, useConfirmDraft, useDiscardDraft, useDraft, type Confirmed, type Draft } from "./usePurchases";
import { NoAccess } from "../../kit/NoAccess";

type Category = "taxable" | "exempt" | "nil_rated" | "non_gst";
const CATEGORIES: { value: Category; label: string }[] = [
  { value: "taxable", label: "Taxable" },
  { value: "exempt", label: "Exempt" },
  { value: "nil_rated", label: "Nil rated" },
  { value: "non_gst", label: "Non-GST" },
];

type LineState = {
  draftLineId: string | null;
  productId: string; // "" = create a new product from this line
  name: string;
  hsn: string;
  quantity: string;
  unit: string;
  taxable: string;
  rate: string;
  igst: string;
  cgst: string;
  sgst: string;
  cess: string;
  code: string;
  uqc: string;
  category: Category;
  rateFrom: string;
  codeFree: boolean | null;
  unclear: string[];
};

type Head = { gstin: string; supplierName: string; number: string; date: string; total: string };

/** The reader writes DD-MM-YYYY; the date input wants YYYY-MM-DD. Anything else is left blank to type. */
const WARNING_TEXT = {
  tax_differs_from_rate: "the tax shown doesn't match the taxable value and rate",
  unit_differs_from_product: "the unit differs from the one on your product",
} as const;

export const isoDate = (read: string | null): string => {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec(read ?? "");
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
};

const blankLine = (rateFrom: string): LineState => ({
  draftLineId: null, productId: "", name: "", hsn: "", quantity: "", unit: "", taxable: "", rate: "", igst: "", cgst: "", sgst: "", cess: "",
  code: "", uqc: "", category: "taxable", rateFrom, codeFree: null, unclear: [],
});

export function startingState(d: Draft): { head: Head; lines: LineState[] } {
  const date = isoDate(d.doc_date);
  const lines: LineState[] = d.lines.map((l) => ({
    ...blankLine(date),
    draftLineId: l.id,
    hsn: l.hsn ?? "",
    quantity: l.quantity ?? "",
    unit: l.unit ?? "",
    uqc: /^[A-Z]{3}$/.test(l.unit ?? "") ? (l.unit ?? "") : "",
    taxable: l.taxable_value ?? "",
    rate: l.gst_rate ?? "",
    igst: l.igst ?? "",
    cgst: l.cgst ?? "",
    sgst: l.sgst ?? "",
    cess: l.cess ?? "",
    unclear: l.unclear,
  }));
  return {
    head: { gstin: d.supplier_gstin ?? "", supplierName: "", number: d.doc_number ?? "", date, total: d.invoice_total ?? "" },
    lines: lines.length ? lines : [blankLine(date)],
  };
}

const zero = (v: string) => v.trim() || "0";

/** The body the server confirms: exactly what is on the screen. Nothing is worked out for the business. */
export function confirmBody(head: Head, lines: LineState[]) {
  return {
    supplier_gstin: head.gstin.trim(),
    supplier_name: head.supplierName.trim() || null,
    doc_number: head.number.trim(),
    doc_date: head.date,
    invoice_total: head.total.trim() || null,
    lines: lines.map((l) => ({
      draft_line_id: l.draftLineId,
      product_id: l.productId || null,
      new_item: l.productId
        ? null
        : {
            code: l.code.trim(),
            uqc: l.uqc.trim().toUpperCase(),
            tax_category: l.category,
            gst_rate: l.category === "taxable" ? l.rate.trim() || null : null,
            rate_valid_from: l.category === "taxable" ? l.rateFrom || null : null,
            has_cess: false,
          },
      product_name: l.name.trim(),
      hsn: l.hsn.trim(),
      quantity: l.quantity.trim(),
      unit: l.unit.trim() || null,
      taxable_value: l.taxable.trim(),
      gst_rate: zero(l.rate),
      igst: zero(l.igst),
      cgst: zero(l.cgst),
      sgst: zero(l.sgst),
      cess: zero(l.cess),
    })),
  };
}

/** The review screen (R2-M2): what we read, ready to correct, and nothing is added until you confirm. */
export function ReviewPage() {
  const { businessId = "", draftId = "" } = useParams();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const draft = useDraft(businessId, draftId);

  if (businesses.isPending || (business && draft.isPending)) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business) return <NotFound />;
  if (!canViewUploads(business.role)) return <NoAccess businessId={businessId} />;
  if (draft.error?.status === 404) return <NotFound />;
  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead
          crumbs={[{ label: "Sell" }, { label: "Purchase invoices", to: `/b/${businessId}/purchases` }, { label: "Check" }]}
          title="Check this invoice"
          sub={
            draft.data?.reader === "none"
              ? "We couldn't read this one, so please type it in from the paper. The file is kept to check against. Nothing counts until you confirm."
              : "Compare with the paper. Nothing counts until you confirm."
          }
        />
        {draft.error && <Banner tone="error">{errorText(draft.error)}</Banner>}
        {draft.data && <Review key={draft.data.id} businessId={businessId} draft={draft.data} mayEdit={canUpload(business.role)} />}
      </main>
    </>
  );
}

function Review({ businessId, draft, mayEdit }: { businessId: string; draft: Draft; mayEdit: boolean }) {
  const navigate = useNavigate();
  const start = startingState(draft);
  const [head, setHead] = useState(start.head);
  const [lines, setLines] = useState(start.lines);
  const [done, setDone] = useState<Confirmed | null>(null);
  const [lineTab, setLineTab] = useState(0);
  const confirm = useConfirmDraft(businessId, draft.id);
  const discard = useDiscardDraft(businessId, draft.id);
  const products = useActiveProducts(businessId);
  const decided = draft.decision !== null || done !== null;
  const setLine = (i: number, patch: Partial<LineState>) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  const fieldError = (e: ApiError | null, field: string) => (e?.field === field ? e.message : undefined);
  const err = confirm.error;

  const checkCode = async (i: number) => {
    const code = lines[i].code.trim();
    if (!code) return;
    try {
      setLine(i, { codeFree: await codeAvailable(businessId, code) });
    } catch {
      setLine(i, { codeFree: null }); // the confirm still refuses a taken code
    }
  };

  if (done) {
    const needPrice = done.received.filter((r) => r.price_needed).length;
    return (
      <>
        <Banner>
          Confirmed. {done.line_count} line{done.line_count === 1 ? "" : "s"} added to your products and stock.
          {needPrice > 0 && ` ${needPrice} still need${needPrice === 1 ? "s" : ""} a selling price per 1 qty.`}
        </Banner>
        {done.warnings.length > 0 && (
          <Banner>
            Saved, but worth a look:
            {done.warnings.map((w) => ` line ${w.line_no}: ${WARNING_TEXT[w.code]}.`)}
          </Banner>
        )}
        <p>
          <Link to={`/b/${businessId}/products`}>See your products</Link> · <Link to={`/b/${businessId}/purchases`}>More purchase invoices</Link>
        </p>
      </>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        confirm.mutate(confirmBody(head, lines), {
          onSuccess: setDone,
          onError: (e) => {
            const at = /^lines\.(\d+)\./.exec(e.field ?? "");
            if (at) setLineTab(Number(at[1])); // show the line the problem is on
          },
        });
      }}
    >
      {draft.decision && <Banner>This invoice was {draft.decision}. It can't be changed.</Banner>}
      {draft.unclear.length > 0 && draft.reader !== "none" && <Banner>Please check: {draft.unclear.join(", ").replaceAll("_", " ")}.</Banner>}
      <fieldset disabled={decided || !mayEdit} className="plain">
        <section className="panel" aria-label="Supplier invoice">
        <div className="f5 pad">
        <Field label="Supplier GSTIN" value={head.gstin} onChange={(e) => setHead({ ...head, gstin: e.target.value })} error={fieldError(err, "supplier_gstin")} />
        <Field label="Supplier name (optional)" value={head.supplierName} onChange={(e) => setHead({ ...head, supplierName: e.target.value })} />
        <Field label="Invoice number" value={head.number} onChange={(e) => setHead({ ...head, number: e.target.value })} error={fieldError(err, "doc_number")} />
        <Field label="Invoice date" type="date" value={head.date} onChange={(e) => setHead({ ...head, date: e.target.value })} error={fieldError(err, "doc_date")} />
        <Field label="Invoice total (optional)" inputMode="decimal" value={head.total} onChange={(e) => setHead({ ...head, total: e.target.value })} error={fieldError(err, "invoice_total")} />
        </div>
        </section>

        <section className="panel lines-panel" aria-label="Lines">
        <div className="lines-add">
          <Button
            type="button"
            variant="secondary"
            className="btn-sm"
            onClick={() => {
              setLines((ls) => [...ls, blankLine(head.date)]);
              setLineTab(lines.length);
            }}
          >
            Add a line
          </Button>
        </div>
        <div className="pad">
        <Tabs
          label="Lines"
          current={Math.min(lineTab, lines.length - 1)}
          onChange={setLineTab}
          tabs={lines.map((l, i) => {
          const e = (f: string) => fieldError(err, `lines.${i}.${f}`);
          return {
            label: l.name.trim() ? `${i + 1}. ${l.name.trim().slice(0, 24)}` : `Line ${i + 1}`,
            panel: (
            <fieldset key={i} className="plain">
              <legend className="visually-hidden">Line {i + 1}</legend>
              <div className="f6">
              {l.unclear.length > 0 && <p className="hint">Please check: {l.unclear.join(", ").replaceAll("_", " ")}.</p>}
              <Field label={`Product name, line ${i + 1}`} value={l.name} onChange={(ev) => setLine(i, { name: ev.target.value })} error={e("product_name")} />
              <Field label={`HSN, line ${i + 1}`} value={l.hsn} onChange={(ev) => setLine(i, { hsn: ev.target.value })} error={e("hsn")} />
              <Field label={`Quantity, line ${i + 1}`} inputMode="decimal" value={l.quantity} onChange={(ev) => setLine(i, { quantity: ev.target.value })} error={e("quantity")} />
              <Field label={`Unit, line ${i + 1}`} value={l.unit} onChange={(ev) => setLine(i, { unit: ev.target.value })} error={e("unit")} />
              <Field label={`Taxable value, line ${i + 1}`} inputMode="decimal" value={l.taxable} onChange={(ev) => setLine(i, { taxable: ev.target.value })} error={e("taxable_value")} />
              <Field label={`GST rate %, line ${i + 1}`} inputMode="decimal" value={l.rate} onChange={(ev) => setLine(i, { rate: ev.target.value })} error={e("gst_rate")} />
              <Field label={`IGST, line ${i + 1}`} inputMode="decimal" value={l.igst} onChange={(ev) => setLine(i, { igst: ev.target.value })} error={e("igst")} />
              <Field label={`CGST, line ${i + 1}`} inputMode="decimal" value={l.cgst} onChange={(ev) => setLine(i, { cgst: ev.target.value })} error={e("cgst")} />
              <Field label={`SGST, line ${i + 1}`} inputMode="decimal" value={l.sgst} onChange={(ev) => setLine(i, { sgst: ev.target.value })} error={e("sgst")} />
              <Field label={`Cess, line ${i + 1}`} inputMode="decimal" value={l.cess} onChange={(ev) => setLine(i, { cess: ev.target.value })} error={e("cess")} />

              <div className="field">
                <label htmlFor={`product-${i}`}>Add line {i + 1} to</label>
                <select id={`product-${i}`} value={l.productId} onChange={(ev) => setLine(i, { productId: ev.target.value })}>
                  <option value="">A new product</option>
                  {products.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} {p.name}
                    </option>
                  ))}
                </select>
              </div>
              {!l.productId && (
                <>
                  <Field
                    label={`Product code, line ${i + 1}`}
                    value={l.code}
                    onChange={(ev) => setLine(i, { code: ev.target.value, codeFree: null })}
                    onBlur={() => checkCode(i)}
                    error={e("code") ?? (l.codeFree === false ? "Another product already uses this code" : undefined)}
                    hint={l.codeFree === true ? "This code is free." : undefined}
                  />
                  <Field label={`Unit code (UQC), line ${i + 1}`} value={l.uqc} onChange={(ev) => setLine(i, { uqc: ev.target.value })} placeholder="PCS, NOS, KGS…" error={e("uqc")} />
                  <div className="field">
                    <label htmlFor={`cat-${i}`}>Tax category, line {i + 1}</label>
                    <select id={`cat-${i}`} value={l.category} onChange={(ev) => setLine(i, { category: ev.target.value as Category })}>
                      {CATEGORIES.map((c) => (
                        <option key={c.value} value={c.value}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  {l.category === "taxable" && (
                    <Field label={`GST rate applies from, line ${i + 1}`} type="date" value={l.rateFrom} onChange={(ev) => setLine(i, { rateFrom: ev.target.value })} error={e("rate_valid_from") ?? e("gst_rate")} />
                  )}
                </>
              )}
              </div>
              {lines.length > 1 && !decided && (
                <Button
                  type="button"
                  variant="link"
                  onClick={() => {
                    setLines((ls) => ls.filter((_, n) => n !== i));
                    setLineTab(Math.max(0, i - 1));
                  }}
                >
                  Remove line {i + 1}
                </Button>
              )}
            </fieldset>
            ),
          };
        })}
        />
        </div>
        </section>
      </fieldset>

      {err && <Banner tone="error">{errorText(err)}</Banner>}
      {discard.error && <Banner tone="error">{errorText(discard.error)}</Banner>}
      {!decided && mayEdit && (
        <div className="savebar">
          <Button type="submit" busy={confirm.isPending}>
            Confirm and add to my products
          </Button>
          <Button type="button" variant="secondary" busy={discard.isPending} onClick={() => discard.mutate(undefined, { onSuccess: () => navigate(`/b/${businessId}/purchases`) })}>
            Set this invoice aside
          </Button>
          <p className="hint">Nothing is added to your products or stock until you confirm.</p>
        </div>
      )}
    </form>
  );
}

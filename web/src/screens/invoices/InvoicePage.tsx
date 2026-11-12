import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { canCreateDocuments } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { formatRupees } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { blankForm, draftIn, formOf, newLine, sameForm, type Draft, type Form } from "./draftForm";
import { CustomerPicker, ProductPicker } from "./Pickers";
import { Totals } from "./Totals";
import { usePreview } from "./usePreview";

type Product = components["schemas"]["ProductOut"];

/**
 * M10 2a: a draft invoice. Everything shown about tax and totals is the server's computation
 * from the last save; the page never works out an amount. There is no Finalize here: it needs
 * the number series, which waits on the CA (LLD-4 L4-2), and stays out until its flag is on.
 */
export function InvoicePage() {
  const { businessId = "", draftId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const states = useStateCodes();
  const key = useRef(crypto.randomUUID()); // one create, however many times Save is pressed
  const [form, setForm] = useState<Form | null>(draftId ? null : blankForm());
  const [saved, setSaved] = useState<Draft | null>(null);
  const [stale, setStale] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const path = { business_id: businessId, draft_id: draftId ?? "" };

  const loaded = useQuery<Draft, ApiError>({
    queryKey: ["b", businessId, "draft", draftId],
    enabled: Boolean(business && draftId),
    staleTime: Infinity, // the page moves it on each save; a re-read is the stale banner's choice
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/drafts/{draft_id}", { params: { path } })),
  });
  const ids = [...new Set((form?.lines ?? loaded.data?.lines ?? []).map((l) => l.product_id))];
  const names = Object.fromEntries(
    useQueries({
      queries: ids.map((id) => ({
        queryKey: ["b", businessId, "product", id],
        staleTime: 5 * 60_000,
        queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/products/{product_id}", { params: { path: { business_id: businessId, product_id: id } } })),
      })),
    }).flatMap((q, i) => (q.data ? [[ids[i], (q.data as Product).name]] : [])),
  ) as Record<string, string>;

  useEffect(() => {
    if (loaded.data && !saved) {
      setSaved(loaded.data);
      setForm(formOf(loaded.data));
    }
  }, [loaded.data, saved]);

  const save = useMutation<Draft, ApiError, Form>({
    mutationFn: (f) =>
      draftId
        ? call(() => api.PUT("/api/v1/b/{business_id}/drafts/{draft_id}", { params: { path, header: { "If-Match": String(saved?.version) } }, body: draftIn(f) }))
        : call(() => api.POST("/api/v1/b/{business_id}/drafts", { params: { path: { business_id: businessId }, header: { "Idempotency-Key": key.current } }, body: draftIn(f) })),
    onMutate: () => setStale(false),
    onSuccess: (out) => {
      queryClient.setQueryData(["b", businessId, "draft", out.id], out);
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      setSaved(out);
      if (!draftId) navigate(`/b/${businessId}/invoices/${out.id}`, { replace: true });
    },
    onError: (e) => setStale(e.code === "stale_record"),
  });
  const remove = useMutation<unknown, ApiError>({
    mutationFn: () => call(() => api.DELETE("/api/v1/b/{business_id}/drafts/{draft_id}", { params: { path, header: { "If-Match": String(saved?.version) } } })),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["b", businessId, "draft", draftId] });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      navigate(`/b/${businessId}/home`, { replace: true });
    },
    onError: (e) => setStale(e.code === "stale_record"),
  });
  const preview = usePreview(businessId, draftId ?? "");

  if (businesses.isPending) return <main className="page" aria-busy="true"><p>Loading…</p></main>;
  if (!business || !canCreateDocuments(business.role) || loaded.error?.status === 404) return <NotFound />;
  if (loaded.error) return <main className="page"><Banner tone="error">{errorText(loaded.error)}</Banner></main>;
  if (!form) return <main className="page" aria-busy="true"><p>Loading…</p></main>;

  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const dirty = !saved ? true : !sameForm(form, formOf(saved, names));
  const stateOptions = (states.data ?? []).map((s) => ({ value: s.code, label: `${s.code} ${s.name}` }));
  const stateNames = Object.fromEntries((states.data ?? []).map((s) => [s.code, s.name]));
  const error = save.error ?? remove.error;
  const reload = async () => {
    const latest = (await loaded.refetch()).data;
    if (latest) {
      setSaved(latest);
      setForm(formOf(latest, names));
      setStale(false);
      save.reset();
      remove.reset();
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(form);
  };
  const setLine = (i: number, patch: Partial<Form["lines"][number]>) => set({ lines: form.lines.map((l, n) => (n === i ? { ...l, ...patch } : l)) });
  const pickProduct = (p: Product) => set({ lines: [...form.lines, { ...newLine(), product_id: p.id, name: p.name }] });
  const previewReady = preview.status.data?.status === "ready" && preview.forVersion === saved?.version;

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <h1>{draftId ? "Draft invoice" : "New invoice"}</h1>
        <p className="hint">Draft · gets its number when you finalize</p>
        {stale && (
          <Banner tone="error">
            Someone saved this draft after you opened it.{" "}
            <Button type="button" variant="link" onClick={reload}>
              Load their version
            </Button>{" "}
            (your unsaved changes here are replaced).
          </Banner>
        )}
        {error && !stale && <Banner tone="error">{error.fix ?? (error.message || errorText(error))}</Banner>}
        <form onSubmit={submit} noValidate>
          <RadioGroup<"customer" | "cash">
            legend="Bill to"
            name="buyer"
            options={[{ value: "customer", label: "A customer" }, { value: "cash", label: "Cash sale (no GSTIN)" }]}
            value={form.buyer}
            onChange={(buyer) => set({ buyer })}
          />
          {form.buyer === "customer" ? (
            <>
              {form.customer_id && <p>Customer: <strong>{form.customer_name}</strong></p>}
              <CustomerPicker businessId={businessId} label="Find a customer" onPick={(c) => set({ customer_id: c.id, customer_name: c.name })} />
            </>
          ) : (
            <>
              <SelectField label="Buyer's state" options={stateOptions} value={form.cash_state} onChange={(e) => set({ cash_state: e.target.value })} />
              <Field label="Buyer's name (optional)" value={form.cash_name} onChange={(e) => set({ cash_name: e.target.value })} />
              <Field label="Buyer's address (optional)" value={form.cash_address} onChange={(e) => set({ cash_address: e.target.value })} />
            </>
          )}
          <Field label="Invoice date" type="date" value={form.doc_date} onChange={(e) => set({ doc_date: e.target.value })} hint="Blank is today." />

          <h2>Items</h2>
          {form.lines.map((l, i) => (
            <fieldset key={l.key} className="line">
              <legend>
                {i + 1}. {l.name || names[l.product_id] || "Product"}
              </legend>
              <Field label="Quantity" inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} />
              <Field label="Rate (excl. GST)" inputMode="decimal" value={l.unit_price} onChange={(e) => setLine(i, { unit_price: e.target.value })} hint="Blank uses the product's sale rate." />
              <SelectField
                label="Discount"
                placeholder="None"
                options={[{ value: "amount", label: "Amount" }, { value: "percent", label: "Percent" }]}
                value={l.discount_kind}
                onChange={(e) => setLine(i, { discount_kind: e.target.value as Form["lines"][number]["discount_kind"] })}
              />
              {l.discount_kind && <Field label="Discount value" inputMode="decimal" value={l.discount_value} onChange={(e) => setLine(i, { discount_value: e.target.value })} />}
              <Button type="button" variant="link" onClick={() => set({ lines: form.lines.filter((_, n) => n !== i) })}>
                Remove line {i + 1}
              </Button>
            </fieldset>
          ))}
          <ProductPicker businessId={businessId} label="Add a product" onPick={pickProduct} />
          <Field label="Invoice discount (amount)" inputMode="decimal" value={form.invoice_discount} onChange={(e) => set({ invoice_discount: e.target.value })} />

          <h2>Delivery</h2>
          <label className="radio">
            <input type="checkbox" checked={form.customer_collects} onChange={(e) => set({ customer_collects: e.target.checked })} /> The customer collects the goods
          </label>
          {!form.customer_collects && (
            <label className="radio">
              <input type="checkbox" checked={form.ship_different} onChange={(e) => set({ ship_different: e.target.checked })} /> Ship to a different address
            </label>
          )}
          {form.ship_different && !form.customer_collects && (
            <>
              <Field label="Ship-to name" value={form.ship.name} onChange={(e) => set({ ship: { ...form.ship, name: e.target.value } })} />
              <Field label="Ship-to address line 1" value={form.ship.line1} onChange={(e) => set({ ship: { ...form.ship, line1: e.target.value } })} />
              <Field label="Ship-to address line 2" value={form.ship.line2} onChange={(e) => set({ ship: { ...form.ship, line2: e.target.value } })} />
              <Field label="Ship-to city" value={form.ship.city} onChange={(e) => set({ ship: { ...form.ship, city: e.target.value } })} />
              <Field label="Ship-to PIN" inputMode="numeric" value={form.ship.pin} onChange={(e) => set({ ship: { ...form.ship, pin: e.target.value } })} />
              <SelectField label="Ship-to state" options={stateOptions} value={form.ship.state_code} onChange={(e) => set({ ship: { ...form.ship, state_code: e.target.value } })} />
              {form.buyer === "customer" && (
                <label className="radio">
                  <input type="checkbox" checked={form.third_party} onChange={(e) => set({ third_party: e.target.checked })} /> Goods go to a third party, not the buyer
                </label>
              )}
            </>
          )}
          <SelectField
            label="Place of supply (only if it differs)"
            placeholder="Worked out from the buyer"
            options={stateOptions}
            value={form.pos_override}
            onChange={(e) => set({ pos_override: e.target.value })}
          />
          {form.pos_override && <Field label="Why it differs" value={form.pos_reason} onChange={(e) => set({ pos_reason: e.target.value })} />}

          <div className="actions">
            <Button type="submit" busy={save.isPending} disabled={!dirty}>
              Save draft
            </Button>
          </div>
        </form>

        {saved?.computation ? (
          <Totals c={saved.computation} states={stateNames} />
        ) : (
          saved && (
            <p>
              Total as last saved: <strong>{saved.total ? formatRupees(saved.total) : "—"}</strong>. Save to see the tax and any checks.
            </p>
          )
        )}
        {dirty && saved && <p className="hint">Totals and checks are from your last save.</p>}

        {saved && (
          <section aria-label="Preview">
            <Button type="button" busy={preview.start.isPending} disabled={dirty} onClick={() => preview.start.mutate()}>
              Preview PDF
            </Button>
            {dirty && <p className="hint">Save first: the preview shows the saved draft.</p>}
            {preview.start.error && <Banner tone="error">{errorText(preview.start.error)}</Banner>}
            {preview.start.data && preview.forVersion === saved.version && !previewReady && preview.status.data?.status !== "failed" && <p aria-busy="true">Preparing the preview…</p>}
            {preview.status.data?.status === "failed" && <Banner tone="error">The preview could not be made. Try again.</Banner>}
            {previewReady && (
              <p>
                <a href={preview.status.data?.url ?? "#"} target="_blank" rel="noopener noreferrer">
                  Open the preview (PDF)
                </a>{" "}
                <span className="hint">Draft, not a tax invoice.</span>
              </p>
            )}
          </section>
        )}

        {saved && (
          <div className="actions">
            {confirmDelete ? (
              <>
                <span>Delete this draft?</span>
                <Button type="button" busy={remove.isPending} onClick={() => remove.mutate()}>
                  Yes, delete
                </Button>
                <Button type="button" variant="link" onClick={() => setConfirmDelete(false)}>
                  Keep it
                </Button>
              </>
            ) : (
              <Button type="button" variant="link" onClick={() => setConfirmDelete(true)}>
                Delete draft
              </Button>
            )}
          </div>
        )}
      </main>
    </>
  );
}

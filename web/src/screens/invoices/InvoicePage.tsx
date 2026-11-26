import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { canCreateDocuments, canEditCatalog } from "../../auth/roles";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import {
  blankForm,
  draftIn,
  formOf,
  newLine,
  sameForm,
  type Draft,
  type Form,
} from "./draftForm";
import { todayIst } from "../../format/dates";
import { formatRupees } from "../../format/money";
import { useStockFlags } from "../stock/useStock";
import { ChosenCustomer, CustomerPicker, ProductPicker } from "./Pickers";
import { HsnFix, MrpFix } from "./HsnFix";
import { IssueText, Issues, Paper, type Issue } from "./Totals";
import { gstText, hsnText, mrpText } from "./lineFacts";
import { DeliveryDialog } from "./DeliveryDialog";
import { useFinalize } from "./useFinalize";
import { PreviewPanel } from "./PreviewPanel";
import { usePreview } from "./usePreview";
import { useFormKey } from "../../kit/formKey";
import { useSingleFlight } from "../../kit/singleFlight";
import { NoAccess } from "../../kit/NoAccess";
import { useDebounced } from "../../kit/useDebounced";

type Product = components["schemas"]["ProductOut"];
type Computation = components["schemas"]["ComputationOut"];

// Invoice numbering is off until the CA confirms it (D-010), so every invoice made here is a practice one and the button says so.
const PRACTICE_ONLY = true;

type Stock = components["schemas"]["StockPageOut"];
type SavedLine = Draft["lines"][number];
type FormLine = Form["lines"][number];

/** A form line still holds what was saved on the same line, so the server's figures for it are current. */
const sameLine = (l: FormLine, s: SavedLine | undefined) =>
  !!s &&
  s.product_id === l.product_id &&
  s.quantity === l.quantity.trim() &&
  (l.unit_price.trim() === "" || s.unit_price === l.unit_price.trim()) &&
  (s.discount_kind ?? "") === l.discount_kind &&
  (l.discount_kind
    ? (s.discount_value ?? "") === l.discount_value.trim()
    : true);

/**
 * New invoice and a draft invoice (mocks v16): one laptop screen, no page scroll. Left: buyer, date, items, Create.
 * Right: the invoice paper. Everything shown about tax and totals is the server's computation from the last save;
 * the page never works out an amount (a line changed since shows "—" until it is saved). Delivery, place of supply
 * and the invoice discount are in a small pop-up. While live numbering is off every invoice made is a practice one.
 */
export function InvoicePage() {
  const { businessId = "", draftId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const states = useStateCodes();
  const formKey = useFormKey(`invoice:${businessId}`); // one create, however many times Save is pressed or the page is rebuilt
  const once = useSingleFlight();
  const [form, setForm] = useState<Form | null>(draftId ? null : blankForm());
  const [saved, setSaved] = useState<Draft | null>(null);
  const [stale, setStale] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [cashStateMissing, setCashStateMissing] = useState(false);
  const [changingCustomer, setChangingCustomer] = useState(false);
  const [delivery, setDelivery] = useState(false);
  const cashStateRef = useRef<HTMLSelectElement>(null);
  const path = { business_id: businessId, draft_id: draftId ?? "" };

  const loaded = useQuery<Draft, ApiError>({
    queryKey: ["b", businessId, "draft", draftId],
    enabled: Boolean(business && draftId),
    staleTime: Infinity, // the page moves it on each save; a re-read is the stale banner's choice
    refetchOnMount: "always", // coming back from another page (e.g. Business setup) shows the server's checks as they are now
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/drafts/{draft_id}", {
          params: { path },
        }),
      ),
  });
  const ids = [
    ...new Set(
      (form?.lines ?? loaded.data?.lines ?? []).map((l) => l.product_id),
    ),
  ];
  const productQueries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["b", businessId, "product", id],
      staleTime: 5 * 60_000,
      queryFn: () =>
        call(() =>
          api.GET("/api/v1/b/{business_id}/products/{product_id}", {
            params: { path: { business_id: businessId, product_id: id } },
          }),
        ),
    })),
  });
  const products = Object.fromEntries(
    productQueries.flatMap((q, i) =>
      q.data ? [[ids[i], q.data as Product]] : [],
    ),
  ) as Record<string, Product | undefined>;
  const names = Object.fromEntries(
    Object.entries(products).map(([id, p]) => [id, p!.name]),
  ) as Record<string, string>;
  // Stock on hand for each product on the invoice, from the stock list searched by its code (display only).
  const codes = [...new Set(Object.values(products).map((p) => p!.code))];
  const stockQueries = useQueries({
    queries: codes.map((code) => ({
      queryKey: ["b", businessId, "stock", "code", code],
      staleTime: 30_000,
      retry: false,
      queryFn: () =>
        call(() =>
          api.GET("/api/v1/b/{business_id}/stock", {
            params: {
              path: { business_id: businessId },
              query: { q: code, limit: 20 },
            },
          }),
        ),
    })),
  });
  const onHand = Object.fromEntries(
    stockQueries.flatMap((q) =>
      ((q.data as Stock | undefined)?.items ?? []).map((i) => [
        i.product_id,
        i.on_hand,
      ]),
    ),
  ) as Record<string, string | undefined>;

  useEffect(() => {
    if (loaded.data && !saved) {
      setSaved(loaded.data);
      setForm(formOf(loaded.data));
    }
  }, [loaded.data, saved]);
  // The server recomputes a draft's checks whenever it is read (e.g. after the turnover band was set on Business setup).
  // The same version read again carries fresh checks; take them, leaving what the user has typed alone.
  useEffect(() => {
    if (
      loaded.data &&
      saved &&
      loaded.data !== saved &&
      loaded.data.id === saved.id &&
      loaded.data.version === saved.version
    )
      setSaved(loaded.data);
  }, [loaded.data, saved]);

  // The form and the version it is against are taken when Save is pressed and passed to mutate(): useMutation
  // updates its mutationFn in an effect, so one reading `saved` itself could send an old If-Match (#418).
  const save = useMutation<Draft, ApiError, { form: Form; version: string }>({
    mutationFn: ({ form: f, version }) =>
      draftId
        ? call(() =>
            api.PUT("/api/v1/b/{business_id}/drafts/{draft_id}", {
              params: { path, header: { "If-Match": version } },
              body: draftIn(f),
            }),
          )
        : call(() =>
            api.POST("/api/v1/b/{business_id}/drafts", {
              params: {
                path: { business_id: businessId },
                header: { "Idempotency-Key": formKey.current() },
              },
              body: draftIn(f),
            }),
          ),
    onMutate: () => setStale(false),
    onSuccess: (out, { form: sent }) => {
      queryClient.setQueryData(["b", businessId, "draft", out.id], out);
      // The server fills a blank rate with the product's rate on save, so show the saved draft as it is:
      // otherwise the form reads as changed straight after saving and Preview and Finalize stay off.
      setForm(
        formOf(
          out,
          Object.fromEntries(sent.lines.map((l) => [l.product_id, l.name])),
        ),
      );
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      setSaved(out);
      if (!draftId) formKey.reset();
      if (!draftId)
        navigate(`/b/${businessId}/invoices/${out.id}`, { replace: true });
    },
    onError: (e) => {
      setStale(e.code === "stale_record");
      if (e.code === "idempotency_mismatch") formKey.reset(); // the key was used by an earlier, different request: next press starts fresh
    },
  });
  const remove = useMutation<unknown, ApiError, string>({
    mutationFn: (version) =>
      call(() =>
        api.DELETE("/api/v1/b/{business_id}/drafts/{draft_id}", {
          params: { path, header: { "If-Match": version } },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({
        queryKey: ["b", businessId, "draft", draftId],
      });
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "drafts"] });
      navigate(`/b/${businessId}/home`, { replace: true });
    },
    onError: (e) => setStale(e.code === "stale_record"),
  });
  const preview = usePreview(businessId, draftId ?? "");
  const finalize = useFinalize(
    businessId,
    draftId ?? "",
    saved?.version,
    `finalize-${draftId}-${saved?.version}`,
    (doc) =>
      navigate(`/b/${businessId}/documents/${doc.id}`, { replace: true }),
  );
  const flags = useStockFlags(businessId, Boolean(business));
  // #411: the server's computation of the form as typed, so the line totals and the paper move as the seller types. It is the
  // same checks and arithmetic as a save, and nothing is stored; Save draft keeps the draft and finalize computes again. A form
  // the server can't compute yet (a half-typed amount) gets no figures, and the page shows "—" as before.
  const typed = form ? estimateBody(form) : "";
  const savedBody = saved && form ? estimateBody(formOf(saved, names)) : null;
  const settled = useDebounced(typed, 300);
  const live = useQuery<Computation, ApiError>({
    queryKey: ["b", businessId, "estimate", settled],
    enabled: Boolean(business && form && form.lines.length > 0 && settled === typed && typed !== savedBody),
    staleTime: 60_000,
    retry: false,
    queryFn: () =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/drafts/estimate", {
          params: { path: { business_id: businessId } },
          body: JSON.parse(settled),
        }),
      ),
  });

  if (businesses.isPending)
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  if (!business) return <NotFound />;
  if (!canCreateDocuments(business.role))
    return <NoAccess businessId={businessId} />;
  if (loaded.error?.status === 404) return <NotFound />;
  if (loaded.error)
    return (
      <main className="page">
        <Banner tone="error">{errorText(loaded.error)}</Banner>
      </main>
    );
  if (!form)
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );

  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const dirty = !saved ? true : !sameForm(form, formOf(saved, names));
  const stateOptions = (states.data ?? []).map((s) => ({
    value: s.code,
    label: `${s.code} ${s.name}`,
  }));
  const stateNames = Object.fromEntries(
    (states.data ?? []).map((s) => [s.code, s.name]),
  );
  const error = save.error ?? remove.error;
  // A cash sale has no customer to work the place of supply out from, so the buyer's state is required: say so beside it.
  const cashStateError =
    cashStateMissing && !form.cash_state
      ? "Choose the buyer's state for a cash sale."
      : save.error?.field?.startsWith("cash_buyer") &&
          save.error.field.endsWith("state_code")
        ? "Choose the buyer's state for a cash sale."
        : undefined;
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
    if (form.buyer === "cash" && !form.cash_state) {
      setCashStateMissing(true);
      cashStateRef.current?.focus();
      return;
    }
    save.mutate({ form, version: String(saved?.version) });
  };
  // One press: save what is on screen (if anything changed), then finalize that saved version. A failed save or
  // finalize leaves the draft saved and says why.
  const createInvoice = () => {
    if (form.buyer === "cash" && !form.cash_state) {
      setCashStateMissing(true);
      cashStateRef.current?.focus();
      return;
    }
    // One chain at a time, however fast the button is pressed: a second press while the first is still saving or
    // finalizing does nothing. The create key (one per form) and the finalize key (one per saved version) make a
    // press after a failure carry on from where it stopped.
    once((done) => {
      void (async () => {
        let target = saved;
        if (dirty || !target) {
          try {
            target = await save.mutateAsync({ form, version: String(saved?.version) });
          } catch {
            return; // the save error is shown beside the form
          }
        }
        try {
          await finalize.mutateAsync({
            draftId: target.id,
            version: target.version,
          });
        } catch {
          // the finalize error is shown under the form
        }
      })().finally(done);
    });
  };
  const setLine = (i: number, patch: Partial<Form["lines"][number]>) =>
    set({
      lines: form.lines.map((l, n) => (n === i ? { ...l, ...patch } : l)),
    });
  const pickProduct = (p: Product) =>
    set({
      lines: [...form.lines, { ...newLine(), product_id: p.id, name: p.name }],
    });
  const finalizeError = finalize.error;
  const finalizeWords = !finalizeError
    ? null
    : finalizeError.code === "finalize_blocked" &&
        saved?.computation &&
        saved.computation.blocks.length > 0
      ? null // the list under the form already says what to fix; a second generic banner only repeats it
      : finalizeError.status === 404
        ? "Finalizing isn't switched on for your business yet. Your draft is saved."
        : (finalizeError.fix ??
          (finalizeError.message || errorText(finalizeError)));

  const c = saved?.computation ?? null;
  const fresh = !dirty; // the server's figures match what is on screen
  // What the totals and the paper show: the last save while nothing changed, else the server's figures for the form as typed.
  const estimate = dirty && settled === typed && live.data && !live.isFetching ? live.data : null;
  const shown = fresh ? c : estimate;
  const lineFigures = (l: FormLine, i: number) =>
    estimate
      ? estimate.lines.find((x) => x.line_no === i + 1)
      : fresh || sameLine(l, saved?.lines?.[i])
        ? c?.lines.find((x) => x.line_no === i + 1)
        : undefined;
  const lineIssues = (n: number) =>
    [
      ...(c?.blocks ?? []).map((i) => ({ ...i, tone: "bad" })),
      ...(c?.warnings ?? []).map((i) => ({ ...i, tone: "warn" })),
    ].filter((i) => i.line_no === n);
  const docBlocks = (c?.blocks ?? []).filter((i) => !i.line_no);
  const docWarnings = (c?.warnings ?? []).filter((i) => !i.line_no);
  // What the page itself can see is missing before anything is sent; the server's checks follow on save.
  const missing = [
    form.buyer === "customer" && !form.customer_id ? "Choose a buyer." : null,
    form.buyer === "cash" && !form.cash_state
      ? "Choose the buyer's state."
      : null,
    form.lines.length === 0 ? "Add at least one item." : null,
  ].filter((x): x is string => x !== null);
  const blocks: string[] = [
    ...missing,
    ...(fresh
      ? (c?.blocks ?? []).map((i) =>
          i.line_no ? `Line ${i.line_no}: ${i.fix}` : i.fix,
        )
      : []),
  ];
  const checks = fresh
    ? (c?.warnings ?? []).map((i) =>
        i.line_no ? `Line ${i.line_no}: ${i.fix}` : i.fix,
      )
    : [];
  const createOff =
    missing.length > 0 || Boolean(saved && !dirty && saved.ready === false);
  const pos = c?.pos_state_code;
  const hsnFixFor = canEditCatalog(business.role)
    ? (_n: number, productId: string) => (
        <HsnFix
          businessId={businessId}
          productId={productId}
          productName={names[productId] ?? "this product"}
          onSaved={async () => {
            const again = await loaded.refetch();
            if (again.data) setSaved(again.data);
          }}
        />
      )
    : undefined;
  // D-107: a product without an MRP blocks its line; the MRP can be added here. The saved line keeps the rate it was saved
  // with, so it takes the rate the new MRP implies (the server's figure), and the next save or Create uses it.
  const mrpFixFor = canEditCatalog(business.role)
    ? (n: number, productId: string) => (
        <MrpFix
          businessId={businessId}
          productId={productId}
          productName={names[productId] ?? "this product"}
          onSaved={async (p) => {
            const again = await loaded.refetch();
            if (again.data) setSaved(again.data);
            if (p.rate_from_mrp)
              setForm((f) => (f ? { ...f, lines: f.lines.map((l, i) => (i === n - 1 && l.product_id === productId ? { ...l, unit_price: p.rate_from_mrp! } : l)) } : f));
          }}
        />
      )
    : undefined;
  const buyerOnPaper =
    form.buyer === "cash" ? (
      <b>{form.cash_name.trim() || "Cash sale"}</b>
    ) : form.customer_id ? (
      <b>{form.customer_name || "Customer"}</b>
    ) : (
      <span className="k inline">Buyer appears here</span>
    );

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide invpage">
        <div className="invhead">
          <h1>{draftId ? "Draft invoice" : "New invoice"}</h1>
          {PRACTICE_ONLY && (
            <span className="chip chip-warn">Practice mode</span>
          )}
          <span className="hint">
            Draft · gets its number when you create it.
            {PRACTICE_ONLY &&
              " Practice invoices get a PR- number, are not for your customers and never go into GST filing."}
          </span>
        </div>
        {stale && (
          <Banner tone="error">
            Someone saved this draft after you opened it.{" "}
            <Button type="button" variant="link" onClick={reload}>
              Load their version
            </Button>{" "}
            (your unsaved changes here are replaced).
          </Banner>
        )}
        {error && !stale && !cashStateError && (
          <Banner tone="error">
            {error.fix ?? (error.message || errorText(error))}
          </Banner>
        )}
        <div className="inv">
          <form className="invleft" onSubmit={submit} noValidate>
            <div className="invtop">
              <fieldset className="field seg2-field">
                <legend className="flabel">Buyer</legend>
                <div className="seg2">
                  {(["customer", "cash"] as const).map((b) => (
                    <label key={b}>
                      <input
                        type="radio"
                        name="buyer"
                        value={b}
                        checked={form.buyer === b}
                        onChange={() => set({ buyer: b })}
                      />
                      <span>
                        {b === "customer" ? "A customer" : "Cash sale"}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="field">
                <span className="flabel" aria-hidden="true">
                  {form.buyer === "cash" ? "Cash sale (no GSTIN)" : "Customer"}
                </span>
                {form.buyer === "customer" ? (
                  form.customer_id && !changingCustomer ? (
                    <ChosenCustomer
                      businessId={businessId}
                      customerId={form.customer_id}
                      name={form.customer_name}
                      stateNames={stateNames}
                      onChange={() => setChangingCustomer(true)}
                    />
                  ) : (
                    <div className="row-pick">
                      <CustomerPicker
                        businessId={businessId}
                        stateNames={stateNames}
                        label={
                          form.customer_id
                            ? "Find another customer"
                            : "Find a customer"
                        }
                        placeholder={
                          form.customer_id
                            ? "Find another customer: type a name or GSTIN"
                            : "Find a customer: type a name or GSTIN"
                        }
                        none={
                          <Link to={`/b/${businessId}/customers/new`}>
                            Add a new customer
                          </Link>
                        }
                        onPick={(cu) => {
                          queryClient.setQueryData(
                            ["b", businessId, "customer", cu.id],
                            cu,
                          ); // the card shows it without another read
                          set({ customer_id: cu.id, customer_name: cu.name });
                          setChangingCustomer(false);
                        }}
                      />
                      {form.customer_id && (
                        <Button
                          type="button"
                          variant="link"
                          onClick={() => setChangingCustomer(false)}
                        >
                          Keep {form.customer_name || "the customer"}
                        </Button>
                      )}
                    </div>
                  )
                ) : (
                  <div className="f2">
                    <select
                      ref={cashStateRef}
                      className="inp"
                      aria-label="Buyer's state"
                      value={form.cash_state}
                      aria-invalid={cashStateError ? true : undefined}
                      onChange={(e) => {
                        set({ cash_state: e.target.value });
                        setCashStateMissing(false);
                      }}
                    >
                      <option value="">Buyer's state…</option>
                      {stateOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <input
                      className="inp"
                      aria-label="Buyer's name (optional)"
                      placeholder="Buyer's name (optional)"
                      value={form.cash_name}
                      onChange={(e) => set({ cash_name: e.target.value })}
                    />
                    {cashStateError && (
                      <p className="error" role="alert">
                        {cashStateError}
                      </p>
                    )}
                  </div>
                )}
              </div>
              <div className="field">
                <label className="flabel" htmlFor="invoice-date">
                  Invoice date
                </label>
                <input
                  id="invoice-date"
                  className={`inp num${form.doc_date ? "" : " date-default"}`}
                  type="date"
                  value={form.doc_date || todayIst()}
                  max={todayIst()}
                  aria-describedby="invoice-date-hint"
                  title={
                    form.doc_date
                      ? "Clear the date to use the day you create it."
                      : "Today's date, in grey, until you pick one: the invoice takes the day you create it."
                  }
                  onChange={(e) => set({ doc_date: e.target.value })}
                  onClick={(e) => {
                    // Open the calendar from anywhere in the box, not only its icon. Browsers without showPicker keep their own behaviour.
                    try {
                      e.currentTarget.showPicker?.();
                    } catch {
                      // showPicker refuses outside a user gesture or in a cross-origin frame; typing the date still works
                    }
                  }}
                />
                <span id="invoice-date-hint" className="visually-hidden">
                  {form.doc_date
                    ? "Clear the date to use the day you create it."
                    : "Today's date, in grey, until you pick one: the invoice takes the day you create it."}
                </span>
              </div>
            </div>

            <div className="posline">
              {pos && fresh ? (
                <>
                  <span
                    className={`chip ${c?.is_inter_state ? "chip-blue" : "chip-ok"}`}
                  >
                    {c?.is_inter_state
                      ? "IGST"
                      : c?.utgst
                        ? "CGST + UTGST"
                        : "CGST + SGST"}
                  </span>
                  <span>
                    Place of supply{" "}
                    <b>
                      {stateNames[pos] ?? ""} ({pos})
                    </b>
                    {form.pos_override
                      ? ", chosen by hand."
                      : ", from the buyer."}
                  </span>
                </>
              ) : (
                <span className="hint">
                  {form.buyer === "cash"
                    ? "The buyer's state decides the place of supply and the tax."
                    : "The place of supply and tax type follow from the buyer."}
                </span>
              )}
              <span className="sp" />
              <Button
                type="button"
                variant="link"
                onClick={() => setDelivery(true)}
              >
                Delivery, place of supply, invoice discount
              </Button>
            </div>

            <Issues
              title="Fix before creating"
              items={docBlocks}
              tone="error"
              canLeave={!dirty}
            />
            <Issues
              title="Please check"
              items={docWarnings}
              tone="info"
              canLeave={!dirty}
            />

            <section className="panel itemsp" aria-label="Items">
              <div className="psearch">
                <ProductPicker
                  businessId={businessId}
                  label="Add a product"
                  placeholder="Add a product: type a name, code or barcode"
                  none={
                    <Link to={`/b/${businessId}/products/new`}>
                      Add a new product
                    </Link>
                  }
                  onPick={pickProduct}
                />
              </div>
              <div className="itemscroll">
                <table className="items">
                  <thead>
                    <tr>
                      <th scope="col">Product</th>
                      <th scope="col" className="r">
                        Qty
                      </th>
                      <th scope="col" className="r">
                        MRP
                      </th>
                      <th
                        scope="col"
                        className="r"
                        title="Rate per unit, excluding GST"
                      >
                        Rate
                      </th>
                      <th
                        scope="col"
                        className="r"
                        title="Discount on the line, in rupees"
                      >
                        Discount
                      </th>
                      <th scope="col" className="r">
                        Total
                      </th>
                      <th scope="col">
                        <span className="visually-hidden">Remove</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.lines.length === 0 && (
                      <tr>
                        <td colSpan={7} className="empty">
                          No items yet. Search for a product above to add it.
                        </td>
                      </tr>
                    )}
                    {form.lines.map((l, i) => {
                      const p = products[l.product_id];
                      const name = l.name || p?.name || "Product";
                      const stock = onHand[l.product_id];
                      const computed = lineFigures(l, i);
                      const percent = l.discount_kind === "percent";
                      return (
                        <tr key={l.key}>
                          <td>
                            <div className="pname">{name}</div>
                            {p && (
                              <div className="sub2 pdet">
                                {p.hsn ? (
                                  hsnText(p.hsn)
                                ) : (
                                  <span className="warn-text">HSN missing</span>
                                )}{" "}
                                · {gstText(p)} · {p.uqc}
                                {stock !== undefined && (
                                  <>
                                    {" · "}
                                    <span
                                      className={
                                        flags.noStock.has(l.product_id)
                                          ? "bad-text"
                                          : undefined
                                      }
                                    >
                                      Stock {stock}
                                    </span>
                                  </>
                                )}
                              </div>
                            )}
                            {/* #414: the page's note until the server's own no_stock check covers the line, so it shows once. */}
                            {flags.noStock.has(l.product_id) && !lineIssues(i + 1).some((x) => x.code === "no_stock") && (
                              <div className="lnote mute">
                                No stock on hand. You can still sell it; stock
                                goes below zero until you add a purchase.
                              </div>
                            )}
                            {flags.priceNeeded.has(l.product_id) &&
                              !p?.rate_from_mrp &&
                              /^0*(\.0*)?$/.test(l.unit_price.trim()) && (
                                <div className="lnote mute">
                                  This product has no selling price yet. Enter a
                                  rate here, or set its price under{" "}
                                  <Link
                                    to={`/b/${businessId}/stock?only=price_needed`}
                                  >
                                    Stock
                                  </Link>
                                  .
                                </div>
                              )}
                            {lineIssues(i + 1).map((iss, n) => (
                              <div
                                key={`${iss.code}-${n}`}
                                className={`lnote ${iss.tone}`}
                              >
                                <IssueText
                                  issue={iss as Issue}
                                  canLeave={!dirty}
                                  productId={saved?.lines?.[i]?.product_id}
                                  hsnFix={hsnFixFor}
                                  mrpFix={mrpFixFor}
                                />
                              </div>
                            ))}
                          </td>
                          <td className="r">
                            <input
                              className="qty"
                              inputMode="decimal"
                              aria-label={`Quantity of ${name}`}
                              value={l.quantity}
                              onChange={(e) =>
                                setLine(i, { quantity: e.target.value })
                              }
                            />
                          </td>
                          <td className="r num mrp">
                            {p ? mrpText(p.mrp) : "—"}
                          </td>
                          <td className="r">
                            <input
                              className="qty rate"
                              inputMode="decimal"
                              aria-label={`Rate of ${name}, excluding GST`}
                              placeholder={
                                p?.rate_from_mrp
                                  ? p.rate_from_mrp
                                  : p && !/^0*(\.0*)?$/.test(p.sale_rate)
                                    ? p.sale_rate
                                    : "—"
                              }
                              title="Blank uses the rate the MRP implies: MRP ÷ (1 + GST%)."
                              value={l.unit_price}
                              onChange={(e) =>
                                setLine(i, { unit_price: e.target.value })
                              }
                            />
                          </td>
                          <td className="r">
                            <input
                              className="qty rate"
                              inputMode="decimal"
                              aria-label={
                                percent
                                  ? `Discount on ${name} in percent`
                                  : `Discount on ${name} in rupees`
                              }
                              placeholder="—"
                              value={l.discount_value}
                              onChange={(e) => {
                                const v = e.target.value;
                                setLine(i, {
                                  discount_value: v,
                                  discount_kind: percent
                                    ? "percent"
                                    : v.trim()
                                      ? "amount"
                                      : "",
                                });
                              }}
                            />
                            {percent && <span className="sub2"> %</span>}
                          </td>
                          <td className="r num">
                            {computed && (fresh || estimate)
                              ? formatRupees(computed.base)
                              : "—"}
                          </td>
                          <td className="r">
                            <button
                              type="button"
                              className="xbtn"
                              aria-label={`Remove ${name}`}
                              onClick={() =>
                                set({
                                  lines: form.lines.filter((_, n) => n !== i),
                                })
                              }
                            >
                              ×
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="itemsfoot">
                <span>
                  {form.lines.length}{" "}
                  {form.lines.length === 1 ? "item" : "items"}
                  {dirty && !estimate && form.lines.length > 0 ? " · Totals show once the amounts are complete" : ""}
                </span>
                <span>Total = rate × qty − discount, before GST.</span>
              </div>
            </section>

            <div className="bar">
              <Button
                type="button"
                variant="primary"
                busy={save.isPending || finalize.isPending}
                disabled={createOff}
                onClick={createInvoice}
              >
                {PRACTICE_ONLY ? "Create practice invoice" : "Create invoice"}
              </Button>
              <Button
                type="submit"
                variant="secondary"
                busy={save.isPending}
                disabled={!dirty}
              >
                Save draft
              </Button>
              {blocks.length > 0 ? (
                <span className="stat bad" role="status">
                  <b>{blocks.length} to fix:</b> {blocks[0]}
                  {blocks.length > 1 && (
                    <span className="sub2"> +{blocks.length - 1} more</span>
                  )}
                </span>
              ) : checks.length > 0 ? (
                <span className="stat warn" role="status">
                  <b>Please check:</b> {checks[0]}
                </span>
              ) : (
                <span className="stat">
                  {saved && !c && !dirty
                    ? `Total as last saved: ${saved.total ? formatRupees(saved.total) : "—"}. Save to see the tax and any checks.`
                    : dirty && saved
                      ? "Totals include your changes. Save draft to keep them and see any checks."
                      : PRACTICE_ONLY
                        ? "Makes a practice invoice with a PR- number: not for your customer, locked once made."
                        : "Gives the invoice its number and locks it; later changes need a credit note."}
                </span>
              )}
            </div>
            {finalizeWords && (
              <Banner tone="error">
                {finalizeWords}
                {finalizeError?.code === "invoice_plan_required" && (
                  <>
                    {" "}
                    <Link to={`/b/${businessId}/settings/plan`}>
                      See the invoicing plan
                    </Link>
                  </>
                )}
              </Banner>
            )}
            {saved && (
              <div className="row-actions del">
                {confirmDelete ? (
                  <>
                    <span>Delete this draft?</span>
                    <Button
                      type="button"
                      variant="secondary"
                      busy={remove.isPending}
                      onClick={() => remove.mutate(String(saved?.version))}
                    >
                      Yes, delete
                    </Button>
                    <Button
                      type="button"
                      variant="link"
                      onClick={() => setConfirmDelete(false)}
                    >
                      Keep it
                    </Button>
                  </>
                ) : (
                  <Button
                    type="button"
                    variant="link"
                    onClick={() => setConfirmDelete(true)}
                  >
                    Delete draft
                  </Button>
                )}
              </div>
            )}
          </form>

          <aside className="paperwrap" aria-label="Preview">
            <Paper
              c={shown ?? c}
              stale={!shown}
              practice={PRACTICE_ONLY}
              from={{ name: business.display_name, gstin: business.gstin }}
              to={buyerOnPaper}
              date={form.doc_date || todayIst()}
              states={stateNames}
              lines={form.lines.map((l, i) => {
                const p = products[l.product_id];
                const computed = lineFigures(l, i);
                return {
                  key: l.key,
                  name: l.name || p?.name || "Product",
                  detail: p ? `${hsnText(p.hsn)} · ${gstText(p)}` : "",
                  quantity: l.quantity,
                  amount: computed?.base ?? null,
                };
              })}
            />
            {saved && (
              <PreviewPanel
                preview={preview}
                version={saved.version}
                dirty={dirty}
              />
            )}
          </aside>
        </div>
        {delivery && (
          <DeliveryDialog
            form={form}
            set={set}
            buyerIsCash={form.buyer === "cash"}
            stateOptions={stateOptions}
            onClose={() => setDelivery(false)}
          />
        )}
      </main>
    </>
  );
}

/**
 * The body sent for the live figures (#411): what a save would send, except that a cash sale whose state isn't chosen yet goes
 * without a buyer, so the lines can still be priced (the server would refuse an empty state).
 */
function estimateBody(f: Form): string {
  const body = draftIn(f);
  if (body.cash_buyer && !body.cash_buyer.state_code) body.cash_buyer = null;
  return JSON.stringify(body);
}

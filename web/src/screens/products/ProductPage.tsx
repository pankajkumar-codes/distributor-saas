import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { canConfirmRates, canEditCatalog } from "../../auth/roles";
import { todayIst } from "../../format/dates";
import { formatRate } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { ManageRecord } from "../../kit/ManageRecord";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { PageHead } from "../../kit/PageHead";
import { Tabs } from "../../kit/Tabs";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { RateHistory } from "./RateHistory";
import { mrpProblem, rateFromMrp, saleRateProblem } from "./saleRate";
import { useGstRates } from "./useGstRates";
import { NoAccess } from "../../kit/NoAccess";
import { useFormKey } from "../../kit/formKey";
import { useSingleFlight } from "../../kit/singleFlight";

type Detail = components["schemas"]["ProductDetailOut"];
type Category = components["schemas"]["ProductIn"]["tax_category"];
type Values = {
  code: string;
  name: string;
  hsn: string;
  uqc: string;
  sale_rate: string;
  mrp: string;
  barcode: string;
  tax_category: Category | "";
  has_cess: boolean;
};
const EMPTY: Values = { code: "", name: "", hsn: "", uqc: "", sale_rate: "", mrp: "", barcode: "", tax_category: "", has_cess: false };
const CATEGORIES: { value: Category; label: string }[] = [
  { value: "taxable", label: "Taxable" },
  { value: "exempt", label: "Exempt" },
  { value: "nil_rated", label: "Nil rated" },
  { value: "non_gst", label: "Non-GST" },
];

const valuesOf = (p: Detail): Values => ({
  code: p.code,
  name: p.name,
  hsn: p.hsn ?? "",
  uqc: p.uqc,
  sale_rate: p.sale_rate,
  mrp: p.mrp ?? "",
  barcode: p.barcode ?? "",
  tax_category: p.tax_category as Category,
  has_cess: p.has_cess,
});
const blank = (v: string) => v.trim() || null;

/** What PATCH sends: only the fields that differ from the version the user opened. */
export function changedFields(from: Values, to: Values): components["schemas"]["ProductPatch"] {
  const out: Record<string, string | boolean | null> = {};
  for (const key of Object.keys(to) as (keyof Values)[]) {
    const a = from[key];
    const b = to[key];
    if (typeof b === "boolean") {
      if (a !== b) out[key] = b;
    } else if ((a as string).trim() !== b.trim()) {
      out[key] = key === "hsn" || key === "barcode" || key === "mrp" ? blank(b) : b.trim();
    }
  }
  return out;
}

type SaveRequest =
  | { kind: "create"; body: components["schemas"]["ProductIn"] }
  | { kind: "patch"; version: string; body: components["schemas"]["ProductPatch"] };

/**
 * After a reload brings a newer version: the newer saved values with the user's own edits
 * (what differs from the version they opened) laid over them, so nobody else's change is
 * sent back as if the user had made it.
 */
export function rebase(opened: Values, latest: Values, values: Values): Values {
  const out = { ...latest };
  for (const key of Object.keys(changedFields(opened, values)) as (keyof Values)[]) {
    (out as Record<keyof Values, string | boolean>)[key] = values[key];
  }
  return out;
}

/** Server field paths ("rate.valid_from" from validation) to this form's fields. */
export function formField(field: string | undefined): string | undefined {
  if (!field) return undefined;
  return field.startsWith("rate.") ? field.slice(5) : field;
}

/**
 * M8 product form (LLD-3 §10) at /products/new and /products/:productId. A new product is
 * created once per form (Idempotency-Key); an edit sends only what changed, with If-Match,
 * and a 409 keeps the user's values next to the ones someone else saved.
 */
export function ProductPage() {
  const { businessId = "", productId } = useParams();
  const isNew = productId === undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const formKey = useFormKey(`product:${businessId}`);
  const path = { business_id: businessId };

  const units = useQuery<components["schemas"]["UnitOut"][], ApiError>({
    queryKey: ["b", businessId, "units"],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/units", { params: { path } })),
    enabled: Boolean(business),
    staleTime: Infinity,
  });
  const product = useQuery<Detail, ApiError>({
    queryKey: ["b", businessId, "product", productId],
    queryFn: () =>
      call(() =>
        api.GET("/api/v1/b/{business_id}/products/{product_id}", {
          params: { path: { ...path, product_id: productId ?? "" } },
        }),
      ),
    enabled: Boolean(business) && !isNew,
  });

  // Sent here from an invoice line that needs this product's HSN: offer the way back.
  const fromState = (useLocation().state as { backTo?: unknown } | null)?.backTo;
  const backTo = typeof fromState === "string" && fromState.startsWith(`/b/${businessId}/invoices/`) ? fromState : null;
  const [values, setValues] = useState<Values>(EMPTY);
  // The version the form's edits are against: the diff base and the If-Match. It moves only
  // with a save, or with the "someone changed this" banner when a reload brings a newer one.
  const [opened, setOpened] = useState<Detail | null>(null);
  const [theirFields, setTheirFields] = useState<(keyof Values)[]>([]);
  const [rate, setRate] = useState("");
  // A new product's first rate starts today (IST). An earlier start goes through Rate history after saving (#388).
  const [validFrom] = useState(todayIst());
  const [stale, setStale] = useState(false);
  const [rateMissing, setRateMissing] = useState(false);
  const [saleRateChecked, setSaleRateChecked] = useState(false); // a save was tried: a half-typed "10." is now a problem
  // D-106: the sale rate follows the MRP and GST rate (MRP / (1 + GST%)) until the person types a rate of their own.
  const [rateTyped, setRateTyped] = useState(false);
  const [tab, setTab] = useState(0);
  const latest = product.data ?? null;

  useEffect(() => {
    if (!latest || latest.version === opened?.version) return;
    if (!opened) {
      setValues(valuesOf(latest));
    } else {
      const before = valuesOf(opened);
      const now = valuesOf(latest);
      setValues(rebase(before, now, values));
      setTheirFields(Object.keys(changedFields(before, now)) as (keyof Values)[]);
      setStale(true);
    }
    setOpened(latest);
  }, [latest]); // opened and values are read to rebase onto a newer version, not to trigger it

  // A new taxable product, or a saved one changed to Taxable, needs its first rate. Later
  // rates of a product that is already taxable go through its rate history below.
  const needsRate = values.tax_category === "taxable" && (isNew || (opened !== null && opened.tax_category !== "taxable"));
  const rates = useGstRates(validFrom, needsRate);
  // A rate that isn't in the list for today is not kept, nor sent.
  const chosenRate = rates.data?.includes(rate) ? rate : "";
  useEffect(() => {
    if (rates.data && rate && !rates.data.includes(rate)) setRate("");
  }, [rates.data, rate]);

  // The rate list answers for today. Say why it is empty instead of showing a dropdown with nothing in it.
  const ratesReady = Boolean(rates.data && rates.data.length > 0);
  const ratesPlaceholder = rates.isPending ? "Loading rates…" : rates.error ? "Rates unavailable" : "Choose…";
  const ratesNote = rates.data?.length === 0 ? "No GST rates are on file for today." : undefined;

  const saved = (p: Detail) => {
    queryClient.setQueryData(["b", businessId, "product", p.id], p);
    queryClient.invalidateQueries({ queryKey: ["b", businessId, "products"] });
    setOpened(p);
    setValues(valuesOf(p));
    setStale(false);
    setTheirFields([]);
  };

  const once = useSingleFlight();
  // The request is built when Save is pressed, from what is on the screen then, and passed to the mutation. A
  // mutationFn that read `opened` itself could still hold the render before a reload's rebase, and send the old
  // version as If-Match (#409 CI).
  const saveRequest = (): SaveRequest =>
    isNew
      ? {
          kind: "create",
          body: {
            code: values.code.trim(),
            name: values.name.trim(),
            hsn: blank(values.hsn),
            uqc: values.uqc,
            sale_rate: values.sale_rate.trim(),
            mrp: values.mrp.trim(),
            barcode: blank(values.barcode),
            tax_category: values.tax_category as Category,
            has_cess: values.has_cess,
            rate: values.tax_category === "taxable" ? { rate: chosenRate, valid_from: validFrom } : null,
          },
        }
      : {
          kind: "patch",
          version: String(opened?.version),
          body: {
            ...changedFields(valuesOf(opened!), values),
            ...(needsRate ? { rate: { rate: chosenRate, valid_from: validFrom } } : {}),
          },
        };
  const save = useMutation<Detail, ApiError, SaveRequest>({
    mutationFn: (r) =>
      r.kind === "create"
        ? call(() =>
            api.POST("/api/v1/b/{business_id}/products", {
              params: { path, header: { "Idempotency-Key": formKey.current() } },
              body: r.body,
            }),
          )
        : call(() =>
            api.PATCH("/api/v1/b/{business_id}/products/{product_id}", {
              params: { path: { ...path, product_id: productId! }, header: { "If-Match": r.version } },
              body: r.body,
            }),
          ),
    onSuccess: (p) => {
      saved(p);
      if (isNew) formKey.reset();
      if (isNew) navigate(`/b/${businessId}/products`, { replace: true, state: { added: p.name } });
    },
    onError: (e) => {
      if (e.code === "stale_record") product.refetch(); // the newer version brings the banner
      if (e.code === "idempotency_mismatch") formKey.reset(); // the key was used by an earlier, different request: next press starts fresh
    },
  });

  const archive = useMutation<Detail, ApiError, boolean>({
    mutationFn: (archived) =>
      call(() =>
        archived
          ? api.POST("/api/v1/b/{business_id}/products/{product_id}/archive", { params: { path: { ...path, product_id: productId! } } })
          : api.POST("/api/v1/b/{business_id}/products/{product_id}/unarchive", { params: { path: { ...path, product_id: productId! } } }),
      ),
    onSuccess: saved,
  });

  const remove = useMutation<unknown, ApiError, string>({
    mutationFn: (version) =>
      call(() =>
        api.DELETE("/api/v1/b/{business_id}/products/{product_id}", {
          params: { path: { ...path, product_id: productId! }, header: { "If-Match": version } },
        }),
      ),
    onError: (e) => {
      if (e.code === "stale_record") product.refetch();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "products"] });
      navigate(`/b/${businessId}/products`, { replace: true });
    },
  });

  if (businesses.isPending || (!isNew && product.isPending && business)) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || product.error?.status === 404) return <NotFound />;
  const canEdit = canEditCatalog(business.role);
  if (isNew && !canEdit) return <NoAccess businessId={businessId} />;
  // Any other failure to load is not an empty form: saving one would have nothing to edit against.
  if (!isNew && !opened && product.error) {
    return (
      <>
        <TopBar title={business.display_name} gstin={business.gstin} />
        <main className="page">
          <Banner tone="error">
            We couldn't load this product. {errorText(product.error)}{" "}
            <Button type="button" variant="link" onClick={() => product.refetch()}>
              Try again
            </Button>
          </Banner>
        </main>
      </>
    );
  }

  const error = save.error && save.error.code !== "stale_record" ? save.error : null;
  const errorFor = (field: string) => {
    if (field === "sale_rate") {
      const problem = saleRateProblem(values.sale_rate, saleRateChecked);
      if (problem) return problem;
    }
    if (field === "mrp") {
      const problem = mrpProblem(values.mrp, saleRateChecked);
      if (problem) return problem;
    }
    if (field === "rate" && rateMissing && !chosenRate) return "Choose a GST rate.";
    if (!error || formField(error.field) !== field) return undefined;
    // A server check on the rate can come back as pattern text; the owner only needs to know to choose one.
    if (field === "rate") return error.fix ?? "Choose a GST rate.";
    return error.fix ?? (error.message || errorText(error));
  };
  const base = opened;
  const dirty = Boolean(opened) && Object.keys(changedFields(valuesOf(opened!), values)).length > 0;
  const warningFor = (field: string) => base?.warnings.find((w) => w.field === field)?.message;
  const theirs = (field: keyof Values) => {
    if (!stale || !base || !theirFields.includes(field)) return undefined;
    const now = valuesOf(base)[field];
    if (now === values[field]) return "Someone else changed this.";
    return `Now saved as: ${typeof now === "boolean" ? (now ? "yes" : "no") : now || "(blank)"}`;
  };
  const hint = (field: keyof Values, normal?: string) => theirs(field) ?? warningFor(field) ?? normal;
  const categoryNote = isNew
    ? undefined
    : base?.in_use
      ? "This product is on invoices, so it can't move between taxable and not taxable."
      : base?.tax_category === "taxable" && values.tax_category !== "taxable"
        ? "Its GST rates will be voided. They stay in the rate history."
        : undefined;
  const set = (field: keyof Values) => (e: { target: { value: string } }) => setValues({ ...values, [field]: e.target.value });
  // The GST rate the MRP includes: the one chosen on the form, else the product's rate today.
  const gstNow = needsRate ? chosenRate : (base?.rate_on?.rate ?? null);
  const fromMrp = (next: Values, gst: string | null) => rateFromMrp(next.mrp, gst, next.tax_category === "taxable");
  /** Values with the sale rate worked out from the MRP, unless the person typed their own rate. */
  const follow = (next: Values, gst: string | null = gstNow): Values => {
    const r = rateTyped ? null : fromMrp(next, gst);
    return r === null ? next : { ...next, sale_rate: r };
  };
  const derived = fromMrp(values, gstNow);
  const gstWords = values.tax_category === "taxable" ? (gstNow ? `the MRP without its ${formatRate(gstNow)} GST` : null) : "no GST in this MRP";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (saleRateProblem(values.sale_rate, true) || mrpProblem(values.mrp, true)) {
      setSaleRateChecked(true);
      return;
    }
    if (needsRate && !chosenRate) {
      setRateMissing(true);
      return;
    }
    const request = saveRequest();
    once((done) => save.mutate(request, { onSettled: done }));
  };
  const otherError = error && !formField(error.field) ? error : (archive.error ?? remove.error);

  const details = (
    <form onSubmit={submit} noValidate>
      <fieldset disabled={!canEdit} className="plain">
        <div className="cols2">
          <section className="panel pad" aria-label="Product details">
            <Field label="Name" value={values.name} onChange={set("name")} hint={hint("name")} error={errorFor("name")} />
            <div className="f2">
              <Field label="Product code" value={values.code} onChange={set("code")} hint={hint("code")} error={errorFor("code")} />
              <SelectField
                label="Unit"
                placeholder={units.isPending ? "Loading units…" : "Choose…"}
                options={(units.data ?? []).map((u) => ({ value: u.code, label: `${u.name} (${u.code})` }))}
                value={values.uqc}
                onChange={set("uqc")}
                hint={hint("uqc")}
                error={errorFor("uqc")}
              />
            </div>
            {units.error && (
              <Banner tone="error">
                We couldn't load the list of units. {errorText(units.error)}{" "}
                <Button type="button" variant="link" onClick={() => units.refetch()}>
                  Try again
                </Button>
              </Banner>
            )}
            <div className="f2">
              <Field label="HSN (optional)" inputMode="numeric" value={values.hsn} onChange={set("hsn")} hint={theirs("hsn")} describedBy="hsn-note" error={errorFor("hsn")} />
              <Field label="Barcode (optional)" value={values.barcode} onChange={set("barcode")} hint={hint("barcode")} error={errorFor("barcode")} />
            </div>
            {/* A warning about the HSN takes this full-width line, so the form still fits one screen. */}
            <p id="hsn-note" className="hint row-note">
              {warningFor("hsn") ?? "HSN: digits only. Needed before invoicing a buyer with a GSTIN; ask your CA if unsure."}
            </p>
            <div className="f2">
              <Field
                label="MRP per unit, incl. GST (₹)"
                inputMode="decimal"
                value={values.mrp}
                onChange={(e) => setValues(follow({ ...values, mrp: e.target.value }))}
                hint={hint("mrp")}
                describedBy="mrp-note"
                error={errorFor("mrp")}
              />
              <Field
                label="Sale rate per unit, excluding GST (₹)"
                inputMode="decimal"
                value={values.sale_rate}
                onChange={(e) => {
                  setRateTyped(true);
                  setValues({ ...values, sale_rate: e.target.value });
                }}
                hint={hint("sale_rate")}
                error={errorFor("sale_rate")}
              />
            </div>
            <p id="mrp-note" className="hint row-note">
              {derived && gstWords
                ? `From the MRP: ₹${derived} (${gstWords}). Invoices use this rate unless you type another on the invoice.`
                : "The rate is the MRP without GST: MRP ÷ (1 + GST%). Invoices use it unless you type another on the invoice."}
              {derived && rateTyped && derived !== values.sale_rate.trim() && (
                <>
                  {" "}
                  <Button
                    type="button"
                    variant="link"
                    onClick={() => {
                      setRateTyped(false);
                      setValues({ ...values, sale_rate: derived });
                    }}
                  >
                    Use ₹{derived}
                  </Button>
                </>
              )}
            </p>
          </section>
          <section className="panel pad" aria-label="GST">
            <div className="radios-inline">
              <RadioGroup<Category>
                legend="GST treatment"
                name="tax_category"
                options={CATEGORIES}
                value={values.tax_category}
                onChange={(v) => setValues({ ...values, tax_category: v })}
                hint={hint("tax_category", categoryNote)}
                error={errorFor("tax_category")}
              />
            </div>
            {needsRate && (
              <>
                <SelectField
                  label="GST rate"
                  placeholder={ratesPlaceholder}
                  disabled={!ratesReady}
                  options={(rates.data ?? []).map((r) => ({ value: r, label: formatRate(r) }))}
                  value={chosenRate}
                  onChange={(e) => {
                    setRate(e.target.value);
                    setRateMissing(false);
                    setValues(follow(values, e.target.value || null));
                  }}
                  hint={ratesNote ?? "The rate your CA advised. It applies from today; an earlier start date can be added in Rate history after saving."}
                  error={errorFor("rate") ?? errorFor("valid_from")}
                />
                {rates.error && (
                  <Banner tone="error">
                    We couldn't load the GST rates. {errorText(rates.error)}{" "}
                    <Button type="button" variant="link" onClick={() => rates.refetch()}>
                      Try again
                    </Button>
                  </Banner>
                )}
              </>
            )}
            {!isNew && base?.tax_category === "taxable" && values.tax_category === "taxable" && base.rate_on && (
              <p className="hint">
                GST rate today: {formatRate(base.rate_on.rate)}
                {base.rate_on.confirmed ? ", confirmed with your CA." : ", not confirmed with your CA yet."} Change or confirm it in Rate history.
              </p>
            )}
            <label className="radio">
              <input type="checkbox" checked={values.has_cess} onChange={(e) => setValues({ ...values, has_cess: e.target.checked })} />
              This product attracts cess
            </label>
            {warningFor("has_cess") && <p className="hint">{warningFor("has_cess")}</p>}
          </section>
        </div>
      </fieldset>
      {canEdit && (
        <div className="savebar">
          <Button type="submit" busy={save.isPending}>
            {isNew ? "Add product" : "Save changes"}
          </Button>
          <p className="hint" role="status">
            {save.isSuccess && !isNew
              ? "Saved. Invoices already finalized keep the details they were issued with."
              : "Saved changes apply to new invoices. Invoices already issued keep the details they were issued with."}
          </p>
        </div>
      )}
    </form>
  );
  const showRates = !isNew && base && (base.tax_category === "taxable" || base.rates.length > 0);
  const tabs = [{ label: "Details", panel: details }];
  if (showRates)
    tabs.push({
      label: "Rate history",
      panel: <RateHistory businessId={businessId} product={base} canEdit={canEdit} canConfirm={canConfirmRates(business.role)} locked={dirty} onSaved={saved} />,
    });
  if (canEdit && !isNew && base)
    tabs.push({
      label: base.status === "archived" ? "Unarchive or delete" : "Archive or delete",
      panel: (
        <ManageRecord
          noun="product"
          name={base.name}
          archived={base.status === "archived"}
          inUse={base.in_use}
          dirty={dirty}
          archiveBusy={archive.isPending}
          deleteBusy={remove.isPending}
          onArchive={(a) => archive.mutate(a)}
          onDelete={() => remove.mutate(String(opened?.version))}
        />
      ),
    });

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead
          crumbs={[{ label: "Sell" }, { label: "Products", to: `/b/${businessId}/products` }, { label: isNew ? "New product" : (base?.name ?? "") }]}
          title={isNew ? "New product" : base?.name}
        >
          {backTo && (
            <Link className="btn btn-secondary" to={backTo}>
              Back to your invoice
            </Link>
          )}
        </PageHead>
        {base?.status === "archived" && <Banner>This product is archived. It isn't offered on new invoices.</Banner>}
        {stale && (
          <Banner tone="error">
            Someone changed this product since you opened it. Your changes are still here; check them against what's saved
            now, then save again.
          </Banner>
        )}
        {otherError && <Banner tone="error">{otherError.fix ?? (otherError.message || errorText(otherError))}</Banner>}
        {tabs.length > 1 ? <Tabs label="Product" tabs={tabs} current={tab} onChange={setTab} /> : details}
      </main>
    </>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { todayIst } from "../../format/dates";
import { formatRate } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";
import { RateHistory } from "./RateHistory";
import { useGstRates } from "./useGstRates";

type Detail = components["schemas"]["ProductDetailOut"];
type Category = components["schemas"]["ProductIn"]["tax_category"];
type Values = {
  code: string;
  name: string;
  hsn: string;
  uqc: string;
  sale_rate: string;
  barcode: string;
  tax_category: Category | "";
  has_cess: boolean;
};
const EMPTY: Values = { code: "", name: "", hsn: "", uqc: "", sale_rate: "", barcode: "", tax_category: "", has_cess: false };
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
      out[key] = key === "hsn" || key === "barcode" ? blank(b) : b.trim();
    }
  }
  return out;
}

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
  const key = useRef(crypto.randomUUID());
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

  const [values, setValues] = useState<Values>(EMPTY);
  // The version the form's edits are against: the diff base and the If-Match. It moves only
  // with a save, or with the "someone changed this" banner when a reload brings a newer one.
  const [opened, setOpened] = useState<Detail | null>(null);
  const [theirFields, setTheirFields] = useState<(keyof Values)[]>([]);
  const [rate, setRate] = useState("");
  const [validFrom, setValidFrom] = useState(todayIst());
  const [stale, setStale] = useState(false);
  const rates = useGstRates(validFrom, isNew && values.tax_category === "taxable");
  const [confirmDelete, setConfirmDelete] = useState(false);
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

  // A rate that isn't in force on the newly chosen date is not kept, nor sent before it's cleared.
  const chosenRate = rates.data?.includes(rate) ? rate : "";
  useEffect(() => {
    if (rates.data && rate && !rates.data.includes(rate)) setRate("");
  }, [rates.data, rate]);

  const saved = (p: Detail) => {
    queryClient.setQueryData(["b", businessId, "product", p.id], p);
    queryClient.invalidateQueries({ queryKey: ["b", businessId, "products"] });
    setOpened(p);
    setValues(valuesOf(p));
    setStale(false);
    setTheirFields([]);
  };

  const save = useMutation<Detail, ApiError>({
    mutationFn: () => {
      if (isNew) {
        const body: components["schemas"]["ProductIn"] = {
          code: values.code.trim(),
          name: values.name.trim(),
          hsn: blank(values.hsn),
          uqc: values.uqc,
          sale_rate: values.sale_rate.trim(),
          barcode: blank(values.barcode),
          tax_category: values.tax_category as Category,
          has_cess: values.has_cess,
          rate: values.tax_category === "taxable" ? { rate: chosenRate, valid_from: validFrom } : null,
        };
        return call(() =>
          api.POST("/api/v1/b/{business_id}/products", {
            params: { path, header: { "Idempotency-Key": key.current } },
            body,
          }),
        );
      }
      return call(() =>
        api.PATCH("/api/v1/b/{business_id}/products/{product_id}", {
          params: { path: { ...path, product_id: productId }, header: { "If-Match": String(opened?.version) } },
          body: changedFields(valuesOf(opened!), values),
        }),
      );
    },
    onSuccess: (p) => {
      saved(p);
      if (isNew) navigate(`/b/${businessId}/products/${p.id}`, { replace: true });
    },
    onError: (e) => {
      if (e.code === "stale_record") product.refetch(); // the newer version brings the banner
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

  const remove = useMutation<unknown, ApiError>({
    mutationFn: () =>
      call(() =>
        api.DELETE("/api/v1/b/{business_id}/products/{product_id}", {
          params: { path: { ...path, product_id: productId! }, header: { "If-Match": String(opened?.version) } },
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

  const error = save.error && save.error.code !== "stale_record" ? save.error : null;
  const errorFor = (field: string) =>
    error && formField(error.field) === field ? error.fix ?? (error.message || errorText(error)) : undefined;
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
  const set = (field: keyof Values) => (e: { target: { value: string } }) => setValues({ ...values, [field]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const otherError = error && !formField(error.field) ? error : (archive.error ?? remove.error);

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/products`}>Products</Link>
        </p>
        <h1>{isNew ? "New product" : base?.name}</h1>
        {base?.status === "archived" && <Banner>This product is archived. It isn't offered on new invoices.</Banner>}
        {stale && (
          <Banner tone="error">
            Someone changed this product since you opened it. Your changes are still here; check them against what's saved
            now, then save again.
          </Banner>
        )}
        {otherError && <Banner tone="error">{otherError.fix ?? (otherError.message || errorText(otherError))}</Banner>}
        {save.isSuccess && !isNew && <Banner>Saved. Invoices already finalized keep the details they were issued with.</Banner>}

        <form onSubmit={submit} noValidate>
          <Field label="Product code" value={values.code} onChange={set("code")} hint={hint("code")} error={errorFor("code")} />
          <Field label="Name" value={values.name} onChange={set("name")} hint={hint("name")} error={errorFor("name")} />
          <Field
            label="HSN (optional)"
            inputMode="numeric"
            value={values.hsn}
            onChange={set("hsn")}
            hint={hint("hsn", "Digits only. You need it before invoicing; ask your CA if you're not sure.")}
            error={errorFor("hsn")}
          />
          <SelectField
            label="Unit"
            options={(units.data ?? []).map((u) => ({ value: u.code, label: `${u.name} (${u.code})` }))}
            value={values.uqc}
            onChange={set("uqc")}
            hint={hint("uqc")}
            error={errorFor("uqc")}
          />
          <Field
            label="Sale rate per unit, excluding GST (₹)"
            inputMode="decimal"
            value={values.sale_rate}
            onChange={set("sale_rate")}
            hint={hint("sale_rate")}
            error={errorFor("sale_rate")}
          />
          <Field label="Barcode (optional)" value={values.barcode} onChange={set("barcode")} hint={hint("barcode")} error={errorFor("barcode")} />
          <RadioGroup<Category>
            legend="GST treatment"
            name="tax_category"
            options={CATEGORIES}
            value={values.tax_category}
            onChange={(v) => setValues({ ...values, tax_category: v })}
            hint={hint("tax_category", isNew ? undefined : "A product can't move between taxable and not taxable.")}
            error={errorFor("tax_category")}
          />
          <label className="radio">
            <input type="checkbox" checked={values.has_cess} onChange={(e) => setValues({ ...values, has_cess: e.target.checked })} />
            This product attracts cess
          </label>
          {warningFor("has_cess") && <p className="hint">{warningFor("has_cess")}</p>}

          {isNew && values.tax_category === "taxable" && (
            <>
              <Field
                label="Rate applies from"
                type="date"
                value={validFrom}
                onChange={(e) => setValidFrom(e.target.value)}
                error={errorFor("valid_from")}
              />
              <SelectField
                label="GST rate"
                options={(rates.data ?? []).map((r) => ({ value: r, label: formatRate(r) }))}
                value={chosenRate}
                onChange={(e) => setRate(e.target.value)}
                hint="The rate your CA advised. The list is the GST rates in force on that date."
                error={errorFor("rate") ?? (rates.error ? errorText(rates.error) : undefined)}
              />
            </>
          )}
          <div className="actions">
            <Button type="submit" busy={save.isPending}>
              {isNew ? "Add product" : "Save changes"}
            </Button>
          </div>
        </form>

        {!isNew && base && (base.tax_category === "taxable" || base.rates.length > 0) && (
          <RateHistory
            businessId={businessId}
            product={base}
            canConfirm={business.role === "owner" || business.role === "admin"}
            locked={dirty}
            onSaved={saved}
          />
        )}

        {!isNew && base && (
          <section className="card" aria-labelledby="manage">
            <h2 id="manage">Archive or delete</h2>
            <Button
              type="button"
              variant="link"
              busy={archive.isPending}
              disabled={dirty}
              onClick={() => archive.mutate(base.status !== "archived")}
            >
              {base.status === "archived" ? "Unarchive" : "Archive"}
            </Button>
            {dirty && <p className="hint">Save or undo your changes first.</p>}
            {!base.in_use &&
              (confirmDelete ? (
                <p>
                  Delete {base.name} for good?{" "}
                  <Button type="button" variant="link" busy={remove.isPending} onClick={() => remove.mutate()}>
                    Yes, delete
                  </Button>{" "}
                  <Button type="button" variant="link" onClick={() => setConfirmDelete(false)}>
                    Keep it
                  </Button>
                </p>
              ) : (
                <Button type="button" variant="link" onClick={() => setConfirmDelete(true)}>
                  Delete
                </Button>
              ))}
            {base.in_use && <p className="hint">This product is on invoices, so it can be archived but not deleted.</p>}
          </section>
        )}
      </main>
    </>
  );
}

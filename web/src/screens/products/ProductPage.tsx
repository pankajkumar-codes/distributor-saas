import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { todayIst } from "../../format/dates";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { RadioGroup } from "../../kit/RadioGroup";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";

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
  const [base, setBase] = useState<Detail | null>(null); // the version the user is editing
  const [rate, setRate] = useState("");
  const [validFrom, setValidFrom] = useState(todayIst());
  const [stale, setStale] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!product.data) return;
    if (!base) setValues(valuesOf(product.data)); // after a 409, keep what the user typed
    setBase(product.data);
  }, [product.data]); // base is read only to tell the first load from a reload after a 409

  const saved = (p: Detail) => {
    queryClient.setQueryData(["b", businessId, "product", p.id], p);
    queryClient.invalidateQueries({ queryKey: ["b", businessId, "products"] });
    setBase(p);
    setValues(valuesOf(p));
    setStale(false);
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
          rate: values.tax_category === "taxable" ? { rate: rate.trim(), valid_from: validFrom } : null,
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
          params: { path: { ...path, product_id: productId }, header: { "If-Match": String(base?.version) } },
          body: changedFields(valuesOf(base!), values),
        }),
      );
    },
    onSuccess: (p) => {
      saved(p);
      if (isNew) navigate(`/b/${businessId}/products/${p.id}`, { replace: true });
    },
    onError: (e) => {
      if (e.code === "stale_record") {
        setStale(true);
        product.refetch();
      }
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
          params: { path: { ...path, product_id: productId! }, header: { "If-Match": String(base?.version) } },
        }),
      ),
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
  const warningFor = (field: string) => base?.warnings.find((w) => w.field === field)?.message;
  const theirs = (field: keyof Values) => {
    if (!stale || !base) return undefined;
    const now = valuesOf(base)[field];
    return now !== values[field] ? `Now saved as: ${typeof now === "boolean" ? (now ? "yes" : "no") : now || "(blank)"}` : undefined;
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
                label="GST rate (%)"
                inputMode="decimal"
                value={rate}
                onChange={(e) => setRate(e.target.value)}
                hint="As your CA advised, for example 18. We check it against the GST rates for that date."
                error={errorFor("rate")}
              />
              <Field
                label="Rate applies from"
                type="date"
                value={validFrom}
                onChange={(e) => setValidFrom(e.target.value)}
                error={errorFor("valid_from")}
              />
            </>
          )}
          <div className="actions">
            <Button type="submit" busy={save.isPending}>
              {isNew ? "Add product" : "Save changes"}
            </Button>
          </div>
        </form>

        {!isNew && base && (
          <section className="card" aria-labelledby="manage">
            <h2 id="manage">Archive or delete</h2>
            <Button type="button" variant="link" busy={archive.isPending} onClick={() => archive.mutate(base.status !== "archived")}>
              {base.status === "archived" ? "Unarchive" : "Archive"}
            </Button>
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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { NotFound } from "../../kit/NotFound";
import { SelectField } from "../../kit/SelectField";
import { TopBar } from "../../kit/TopBar";

type Customer = components["schemas"]["CustomerOut"];
type AddressIn = components["schemas"]["AddressIn"];
const PARTS = ["line1", "line2", "city", "pin", "state_code"] as const;
type Address = Record<(typeof PARTS)[number], string>;
export type Values = { name: string; gstin: string; credit_days: string; same: boolean; billing: Address; delivery: Address };
type Key = keyof Values;

const NO_ADDRESS: Address = { line1: "", line2: "", city: "", pin: "", state_code: "" };
const EMPTY: Values = { name: "", gstin: "", credit_days: "0", same: true, billing: NO_ADDRESS, delivery: NO_ADDRESS };
const addressOf = (a: components["schemas"]["AddressOut"] | null): Address =>
  a ? { line1: a.line1 ?? "", line2: a.line2 ?? "", city: a.city ?? "", pin: a.pin ?? "", state_code: a.state_code ?? "" } : NO_ADDRESS;
const valuesOf = (c: Customer): Values => ({
  name: c.name,
  gstin: c.gstin ?? "",
  credit_days: String(c.credit_days),
  same: c.delivery_same_as_billing,
  billing: addressOf(c.billing),
  delivery: addressOf(c.delivery),
});
const blank = (v: string) => v.trim() || null;
const addressIn = (a: Address): AddressIn => Object.fromEntries(PARTS.map((k) => [k, blank(a[k])]));
const equal = (a: Values[Key], b: Values[Key]) =>
  typeof a === "object" && typeof b === "object" ? PARTS.every((k) => a[k].trim() === b[k].trim()) : typeof a === "string" ? a.trim() === (b as string).trim() : a === b;

/** The form's fields that differ from `from`. An address is one field: it is sent whole. */
export function changedKeys(from: Values, to: Values): Key[] {
  return (Object.keys(to) as Key[]).filter((k) => !(k === "delivery" && to.same) && !equal(from[k], to[k]));
}

/** What PATCH sends for those fields (the server replaces a whole address it is sent). */
export function patchBody(from: Values, to: Values): components["schemas"]["CustomerPatch"] {
  const keys = changedKeys(from, to);
  const out: components["schemas"]["CustomerPatch"] = {};
  if (keys.includes("name")) out.name = to.name.trim();
  if (keys.includes("gstin")) out.gstin = blank(to.gstin);
  if (keys.includes("credit_days")) out.credit_days = Number(to.credit_days.trim());
  if (keys.includes("billing")) out.billing = addressIn(to.billing);
  if (keys.includes("same")) out.delivery_same_as_billing = to.same;
  if (!to.same && (keys.includes("same") || keys.includes("delivery"))) out.delivery = addressIn(to.delivery);
  return out;
}

/** The newer saved values with the user's own edits (against `opened`) laid over them. */
export function rebase(opened: Values, latest: Values, values: Values): Values {
  const out = { ...latest };
  for (const k of changedKeys(opened, values)) (out as Record<Key, unknown>)[k] = values[k];
  return out;
}

function AddressFields(props: {
  legend: string;
  value: Address;
  onChange: (a: Address) => void;
  states: { value: string; label: string }[];
  errorFor: (part: string) => string | undefined;
  hint?: string;
  stateHint?: string;
}) {
  const { value, onChange, errorFor } = props;
  const set = (k: keyof Address) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value });
  return (
    <fieldset className="field radios">
      <legend>{props.legend}</legend>
      {props.hint && <p className="hint">{props.hint}</p>}
      <Field label="Address line 1" value={value.line1} onChange={set("line1")} error={errorFor("line1")} />
      <Field label="Address line 2" value={value.line2} onChange={set("line2")} error={errorFor("line2")} />
      <Field label="City or town" value={value.city} onChange={set("city")} error={errorFor("city")} />
      <Field label="PIN code" inputMode="numeric" value={value.pin} onChange={set("pin")} error={errorFor("pin")} />
      <SelectField label="State" options={props.states} value={value.state_code} onChange={set("state_code")} hint={props.stateHint} error={errorFor("state_code")} />
    </fieldset>
  );
}

/**
 * M9 customer form (LLD-3 §4, §6.2) at /customers/new and /customers/:customerId. The server
 * checks the GSTIN, states and PIN; the web shows its words on the field it names. Edits use
 * the product form's rule: If-Match is the version the edits are against, and moves only with
 * a save or with the "someone changed this" banner.
 */
export function CustomerPage() {
  const { businessId = "", customerId } = useParams();
  const isNew = customerId === undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const businesses = useMyBusinesses();
  const business = businesses.data?.find((b) => b.business_id === businessId);
  const states = useStateCodes();
  const key = useRef(crypto.randomUUID());
  const path = { business_id: businessId, customer_id: customerId ?? "" };

  const customer = useQuery<Customer, ApiError>({
    queryKey: ["b", businessId, "customer", customerId],
    queryFn: () => call(() => api.GET("/api/v1/b/{business_id}/customers/{customer_id}", { params: { path } })),
    enabled: Boolean(business) && !isNew,
  });
  const [values, setValues] = useState<Values>(EMPTY);
  const [opened, setOpened] = useState<Customer | null>(null);
  const [theirs, setTheirs] = useState<Key[]>([]);
  const [stale, setStale] = useState(false);
  const [daysError, setDaysError] = useState<string | undefined>();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const latest = customer.data ?? null;

  useEffect(() => {
    if (!latest || latest.version === opened?.version) return;
    if (!opened) {
      setValues(valuesOf(latest));
    } else {
      setValues(rebase(valuesOf(opened), valuesOf(latest), values));
      setTheirs(changedKeys(valuesOf(opened), valuesOf(latest)));
      setStale(true);
    }
    setOpened(latest);
  }, [latest]); // opened and values are read to rebase onto a newer version, not to trigger it

  const saved = (c: Customer) => {
    queryClient.setQueryData(["b", businessId, "customer", c.id], c);
    queryClient.invalidateQueries({ queryKey: ["b", businessId, "customers"] });
    setOpened(c);
    setValues(valuesOf(c));
    setStale(false);
    setTheirs([]);
  };
  const refetchIfStale = (e: ApiError) => {
    if (e.code === "stale_record") customer.refetch(); // the newer version brings the banner
  };

  const save = useMutation<Customer, ApiError>({
    mutationFn: () => {
      if (isNew) {
        const body: components["schemas"]["CustomerIn"] = {
          name: values.name.trim(),
          gstin: blank(values.gstin),
          billing: addressIn(values.billing),
          delivery_same_as_billing: values.same,
          delivery: values.same ? null : addressIn(values.delivery),
          credit_days: Number(values.credit_days.trim()),
        };
        return call(() => api.POST("/api/v1/b/{business_id}/customers", { params: { path, header: { "Idempotency-Key": key.current } }, body }));
      }
      return call(() =>
        api.PATCH("/api/v1/b/{business_id}/customers/{customer_id}", {
          params: { path, header: { "If-Match": String(opened?.version) } },
          body: patchBody(valuesOf(opened!), values),
        }),
      );
    },
    onSuccess: (c) => {
      saved(c);
      if (isNew) navigate(`/b/${businessId}/customers/${c.id}`, { replace: true });
    },
    onError: refetchIfStale,
  });
  const archive = useMutation<Customer, ApiError, boolean>({
    mutationFn: (archived) =>
      call(() =>
        archived
          ? api.POST("/api/v1/b/{business_id}/customers/{customer_id}/archive", { params: { path } })
          : api.POST("/api/v1/b/{business_id}/customers/{customer_id}/unarchive", { params: { path } }),
      ),
    onSuccess: saved,
  });
  const remove = useMutation<unknown, ApiError>({
    mutationFn: () =>
      call(() => api.DELETE("/api/v1/b/{business_id}/customers/{customer_id}", { params: { path, header: { "If-Match": String(opened?.version) } } })),
    onError: refetchIfStale,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["b", businessId, "customers"] });
      navigate(`/b/${businessId}/customers`, { replace: true });
    },
  });

  if (businesses.isPending || (!isNew && customer.isPending && business)) {
    return (
      <main className="page" aria-busy="true">
        <p>Loading…</p>
      </main>
    );
  }
  if (!business || customer.error?.status === 404) return <NotFound />;
  // Any other failure to load is not an empty form: saving one would have nothing to edit against.
  if (!isNew && !opened && customer.error) {
    return (
      <>
        <TopBar title={business.display_name} gstin={business.gstin} />
        <main className="page">
          <Banner tone="error">
            We couldn't load this customer. {errorText(customer.error)}{" "}
            <Button type="button" variant="link" onClick={() => customer.refetch()}>
              Try again
            </Button>
          </Banner>
        </main>
      </>
    );
  }

  const error = save.error && save.error.code !== "stale_record" ? save.error : null;
  const words = (e: ApiError) => e.fix ?? (e.message || errorText(e));
  const errorFor = (field: string) => (error && error.field === field ? words(error) : undefined);
  const warningFor = (field: string) => opened?.warnings.find((w) => w.field === field)?.message;
  const theirHint = (k: Key) => {
    if (!stale || !opened || !theirs.includes(k)) return undefined;
    const now = valuesOf(opened)[k];
    if (equal(now, values[k])) return "Someone else changed this.";
    if (typeof now === "object") return `Now saved as: ${PARTS.map((p) => now[p].trim()).filter(Boolean).join(", ") || "(blank)"}`;
    return `Now saved as: ${typeof now === "boolean" ? (now ? "yes" : "no") : now || "(blank)"}`;
  };
  const known = ["name", "gstin", "credit_days", "delivery", "delivery_same_as_billing"];
  const onField = error && (known.includes(error.field ?? "") || /^(billing|delivery)\./.test(error.field ?? ""));
  const otherError = (error && !onField ? error : null) ?? archive.error ?? remove.error;
  const dirty = Boolean(opened) && changedKeys(valuesOf(opened!), values).length > 0;
  const stateOptions = (states.data ?? []).map((s) => ({ value: s.code, label: `${s.name} (${s.code})` }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const ok = /^\d+$/.test(values.credit_days.trim());
    setDaysError(ok ? undefined : "Use a whole number of days, such as 0 or 30.");
    if (ok) save.mutate();
  };

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page">
        <p className="step">
          <Link to={`/b/${businessId}/customers`}>Customers</Link>
        </p>
        <h1>{isNew ? "New customer" : opened?.name}</h1>
        {opened?.status === "archived" && <Banner>This customer is archived. They aren't offered on new invoices.</Banner>}
        {stale && (
          <Banner tone="error">
            Someone changed this customer since you opened it. Your changes are still here; check them against what's saved
            now, then save again.
          </Banner>
        )}
        {otherError && <Banner tone="error">{words(otherError)}</Banner>}
        {states.isError && <Banner tone="error">We couldn't load the list of states. {errorText(states.error)}</Banner>}
        {save.isSuccess && !isNew && <Banner>Saved. Invoices already finalized keep the details they were issued with.</Banner>}

        <form onSubmit={submit} noValidate>
          <Field label="Name" value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} hint={theirHint("name")} error={errorFor("name")} />
          <Field
            label="GSTIN (optional)"
            autoCapitalize="characters"
            value={values.gstin}
            onChange={(e) => setValues({ ...values, gstin: e.target.value })}
            hint={theirHint("gstin") ?? warningFor("gstin") ?? "Leave blank for an unregistered buyer. We check the format only, not registration."}
            error={errorFor("gstin")}
          />
          <AddressFields
            legend="Billing address"
            value={values.billing}
            onChange={(billing) => setValues({ ...values, billing })}
            states={stateOptions}
            errorFor={(p) => errorFor(`billing.${p}`)}
            hint={theirHint("billing")}
            stateHint={warningFor("billing.state_code") ?? "Leave it to use the GSTIN's state."}
          />
          <label className="radio">
            <input type="checkbox" checked={values.same} onChange={(e) => setValues({ ...values, same: e.target.checked })} />
            Deliver to the billing address
          </label>
          {(theirHint("same") || errorFor("delivery_same_as_billing")) && <p className="hint">{theirHint("same") ?? errorFor("delivery_same_as_billing")}</p>}
          {!values.same && (
            <AddressFields
              legend="Delivery address"
              value={values.delivery}
              onChange={(delivery) => setValues({ ...values, delivery })}
              states={stateOptions}
              errorFor={(p) => errorFor(`delivery.${p}`) ?? (p === "line1" ? errorFor("delivery") : undefined)}
              hint={theirHint("delivery")}
            />
          )}
          <Field
            label="Credit days"
            inputMode="numeric"
            value={values.credit_days}
            onChange={(e) => setValues({ ...values, credit_days: e.target.value })}
            hint={theirHint("credit_days") ?? "Days the customer has to pay. 0 means on the invoice date."}
            error={daysError ?? errorFor("credit_days")}
          />
          <div className="actions">
            <Button type="submit" busy={save.isPending}>
              {isNew ? "Add customer" : "Save changes"}
            </Button>
          </div>
        </form>

        {!isNew && opened && (
          <section className="card" aria-labelledby="manage">
            <h2 id="manage">Archive or delete</h2>
            <Button type="button" variant="link" busy={archive.isPending} disabled={dirty} onClick={() => archive.mutate(opened.status !== "archived")}>
              {opened.status === "archived" ? "Unarchive" : "Archive"}
            </Button>
            {dirty && <p className="hint">Save or undo your changes first.</p>}
            {!opened.in_use &&
              (confirmDelete ? (
                <p>
                  Delete {opened.name} for good?{" "}
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
            {opened.in_use && <p className="hint">This customer is on invoices, so they can be archived but not deleted.</p>}
          </section>
        )}
      </main>
    </>
  );
}

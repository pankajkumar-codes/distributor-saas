import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { useStateCodes } from "../../api/useStateCodes";
import { useMyBusinesses } from "../../auth/useMyBusinesses";
import { canEditCatalog } from "../../auth/roles";
import { AddressFields, NO_ADDRESS, addressIn, addressLine, addressOf, sameAddress, type Address } from "../../kit/AddressFields";
import { Banner } from "../../kit/Banner";
import { ManageRecord } from "../../kit/ManageRecord";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { PageHead } from "../../kit/PageHead";
import { Tabs } from "../../kit/Tabs";
import { NotFound } from "../../kit/NotFound";
import { TopBar } from "../../kit/TopBar";
import { NoAccess } from "../../kit/NoAccess";
import { useFormKey } from "../../kit/formKey";

type Customer = components["schemas"]["CustomerOut"];
export type Values = { name: string; gstin: string; credit_days: string; same: boolean; billing: Address; delivery: Address };
type Key = keyof Values;

const EMPTY: Values = { name: "", gstin: "", credit_days: "0", same: true, billing: NO_ADDRESS, delivery: NO_ADDRESS };
const valuesOf = (c: Customer): Values => ({
  name: c.name,
  gstin: c.gstin ?? "",
  credit_days: String(c.credit_days),
  same: c.delivery_same_as_billing,
  billing: addressOf(c.billing),
  delivery: addressOf(c.delivery),
});
const blank = (v: string) => v.trim() || null;
const equal = (a: Values[Key], b: Values[Key]) =>
  typeof a === "object" && typeof b === "object" ? sameAddress(a, b) : typeof a === "string" ? a.trim() === (b as string).trim() : a === b;

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
  const formKey = useFormKey(`customer:${businessId}`);
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
  const [tab, setTab] = useState(0);
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
        return call(() => api.POST("/api/v1/b/{business_id}/customers", { params: { path, header: { "Idempotency-Key": formKey.current() } }, body }));
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
      if (isNew) formKey.reset();
      if (isNew) navigate(`/b/${businessId}/customers`, { replace: true, state: { added: c.name } });
    },
    onError: (e) => {
      refetchIfStale(e);
      if (/^delivery/.test(e.field ?? "")) setTab(1); // the field with the problem is on the Delivery tab
      else if (e.field) setTab(0);
      if (e.code === "idempotency_mismatch") formKey.reset(); // the key was used by an earlier, different request: next press starts fresh
    },
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
  const canEdit = canEditCatalog(business.role);
  if (isNew && !canEdit) return <NoAccess businessId={businessId} />;
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
    if (typeof now === "object") return `Now saved as: ${addressLine(now)}`;
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

  const deliveryNote = theirHint("same") ?? errorFor("delivery_same_as_billing");
  const delivery = (
    <section className="panel pad" aria-label="Delivery address">
      <fieldset disabled={!canEdit} className="plain">
      <label className="radio">
        <input type="checkbox" checked={values.same} onChange={(e) => setValues({ ...values, same: e.target.checked })} />
        Deliver to the billing address
      </label>
      {deliveryNote && <p className="hint">{deliveryNote}</p>}
      {!values.same && (
        <AddressFields
          compact
          legend="Delivery address"
          value={values.delivery}
          onChange={(d) => setValues({ ...values, delivery: d })}
          states={stateOptions}
          errorFor={(p) => errorFor(`delivery.${p}`) ?? (p === "line1" ? errorFor("delivery") : undefined)}
          hint={theirHint("delivery")}
        />
      )}
      </fieldset>
    </section>
  );
  const details = (
    <fieldset disabled={!canEdit} className="plain cols2">
      <section className="panel pad" aria-label="Customer details">
        <Field label="Name" value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} hint={theirHint("name")} error={errorFor("name")} />
        <Field
          label="GSTIN (optional)"
          autoCapitalize="characters"
          value={values.gstin}
          onChange={(e) => setValues({ ...values, gstin: e.target.value })}
          hint={theirHint("gstin") ?? warningFor("gstin") ?? "Leave blank for an unregistered buyer. We check the format only, not registration."}
          error={errorFor("gstin")}
        />
        <Field
          label="Credit days"
          inputMode="numeric"
          value={values.credit_days}
          onChange={(e) => setValues({ ...values, credit_days: e.target.value })}
          hint={theirHint("credit_days") ?? "Days the customer has to pay. 0 means on the invoice date."}
          error={daysError ?? errorFor("credit_days")}
        />
        <p className="hint">Delivery: {values.same ? "to the billing address" : addressLine(values.delivery)}. Change it on the Delivery address tab.</p>
      </section>
      <section className="panel pad" aria-label="Billing address">
        <AddressFields
          compact
          legend="Billing address"
          value={values.billing}
          onChange={(billing) => setValues({ ...values, billing })}
          states={stateOptions}
          errorFor={(p) => errorFor(`billing.${p}`)}
          hint={theirHint("billing")}
          stateHint={warningFor("billing.state_code") ?? "Leave it to use the GSTIN's state."}
        />
      </section>
    </fieldset>
  );
  const tabs = [
    { label: "Details", panel: details },
    { label: "Delivery address", panel: delivery },
  ];
  if (canEdit && !isNew && opened)
    tabs.push({
      label: opened.status === "archived" ? "Unarchive or delete" : "Archive or delete",
      panel: (
        <ManageRecord
          noun="customer"
          name={opened.name}
          archived={opened.status === "archived"}
          inUse={opened.in_use}
          dirty={dirty}
          archiveBusy={archive.isPending}
          deleteBusy={remove.isPending}
          onArchive={(a) => archive.mutate(a)}
          onDelete={() => remove.mutate()}
        />
      ),
    });

  return (
    <>
      <TopBar title={business.display_name} gstin={business.gstin} />
      <main className="page page-wide">
        <PageHead
          crumbs={[{ label: "Sell" }, { label: "Customers", to: `/b/${businessId}/customers` }, { label: isNew ? "New customer" : (opened?.name ?? "") }]}
          title={isNew ? "New customer" : opened?.name}
        />
        {opened?.status === "archived" && <Banner>This customer is archived. They aren't offered on new invoices.</Banner>}
        {stale && (
          <Banner tone="error">
            Someone changed this customer since you opened it. Your changes are still here; check them against what's saved
            now, then save again.
          </Banner>
        )}
        {otherError && <Banner tone="error">{words(otherError)}</Banner>}
        {states.isError && <Banner tone="error">We couldn't load the list of states. {errorText(states.error)}</Banner>}

        <form onSubmit={submit} noValidate>
          <Tabs label="Customer" tabs={tabs} current={tab} onChange={setTab} />
          {canEdit && tab < 2 && (
            <div className="savebar">
              <Button type="submit" busy={save.isPending}>
                {isNew ? "Add customer" : "Save changes"}
              </Button>
              <p className="hint" role="status">
                {save.isSuccess && !isNew ? "Saved. Invoices already finalized keep the details they were issued with." : "Invoices already issued keep the details they were issued with."}
              </p>
            </div>
          )}
        </form>
      </main>
    </>
  );
}

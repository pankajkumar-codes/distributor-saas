import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, call } from "../../api/client";
import { errorText, type ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { dayBefore, formatDate, todayIst } from "../../format/dates";
import { formatRate } from "../../format/money";
import { Banner } from "../../kit/Banner";
import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { SelectField } from "../../kit/SelectField";
import { useGstRates } from "./useGstRates";

type Detail = components["schemas"]["ProductDetailOut"];
type Rate = components["schemas"]["RateOut"];
type Action = { kind: "void" | "confirm" | "unconfirm"; rate: Rate };

const PROMPT = {
  void: { label: "Why is this rate wrong?", button: "Void rate" },
  confirm: { label: "Your note (optional)", button: "Mark confirmed" },
  unconfirm: { label: "Why are you unmarking it?", button: "Unmark" },
} as const;

/** "Until" is the day before the next live rate starts: the server's valid_until is exclusive. */
const until = (r: Rate) => (r.valid_until ? formatDate(dayBefore(r.valid_until)) : "");

/**
 * M8 rate history (LLD-3 §5, §10). Rows are insert-only: a wrong rate is voided with a reason
 * and a new one added. "Confirmed with CA" is the owner's own statement, so only owner and
 * admin are offered it; the server decides either way.
 */
export function RateHistory(props: {
  businessId: string;
  product: Detail;
  canConfirm: boolean;
  locked: boolean; // the form above has unsaved edits, which a new version would drop
  onSaved: (p: Detail) => void;
}) {
  const { businessId, product, canConfirm, locked, onSaved } = props;
  const path = { business_id: businessId, product_id: product.id };
  const key = useRef(crypto.randomUUID());
  const [validFrom, setValidFrom] = useState(todayIst());
  const [rate, setRate] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [text, setText] = useState("");
  const rates = useGstRates(validFrom, true);
  const chosenRate = rates.data?.includes(rate) ? rate : "";
  useEffect(() => {
    if (rates.data && rate && !rates.data.includes(rate)) setRate("");
  }, [rates.data, rate]);

  const add = useMutation<Detail, ApiError>({
    mutationFn: () =>
      call(() =>
        api.POST("/api/v1/b/{business_id}/products/{product_id}/rates", {
          params: { path, header: { "Idempotency-Key": key.current } },
          body: { rate: chosenRate, valid_from: validFrom },
        }),
      ),
    onSuccess: (p) => {
      key.current = crypto.randomUUID(); // the next rate is a new request
      setRate("");
      onSaved(p);
    },
  });

  const act = useMutation<Detail, ApiError, Action>({
    mutationFn: ({ kind, rate: r }) => {
      const params = { params: { path: { ...path, rate_id: r.id } } };
      const words = text.trim() || null;
      if (kind === "confirm") return call(() => api.POST("/api/v1/b/{business_id}/products/{product_id}/rates/{rate_id}/confirm", { ...params, body: { note: words } }));
      if (kind === "unconfirm") return call(() => api.POST("/api/v1/b/{business_id}/products/{product_id}/rates/{rate_id}/unconfirm", { ...params, body: { reason: words } }));
      return call(() => api.POST("/api/v1/b/{business_id}/products/{product_id}/rates/{rate_id}/void", { ...params, body: { reason: words } }));
    },
    onSuccess: (p) => {
      setAction(null);
      setText("");
      onSaved(p);
    },
  });

  const start = (kind: Action["kind"], r: Rate) => {
    act.reset();
    setText("");
    setAction({ kind, rate: r });
  };
  const words = (e: ApiError | null) => (e ? e.fix ?? (e.message || errorText(e)) : undefined);
  const submitAdd = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  const submitAct = (e: FormEvent) => {
    e.preventDefault();
    if (action) act.mutate(action);
  };

  return (
    <section className="card" aria-labelledby="rates">
      <h2 id="rates">GST rate history</h2>
      {product.rate_changed_within_warning_window && (
        <Banner>This product's GST rate changed recently. Check invoices dated around the change.</Banner>
      )}
      {locked && <p className="hint">Save or undo your changes above before changing rates.</p>}
      <table className="products">
        <thead>
          <tr>
            <th scope="col">GST rate</th>
            <th scope="col">From</th>
            <th scope="col">Until</th>
            <th scope="col">Confirmed with CA (your note)</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {product.rates.map((r) => {
            const confirmed = r.confirmation?.state === "confirmed";
            return (
              <tr key={r.id}>
                <td data-label="GST rate">{r.voided ? <s>{formatRate(r.rate)}</s> : formatRate(r.rate)}</td>
                <td data-label="From">{formatDate(r.valid_from)}</td>
                <td data-label="Until">{r.voided ? "" : until(r)}</td>
                <td data-label="Confirmed with CA">
                  {r.voided ? (
                    <span className="tag">Voided</span>
                  ) : confirmed ? (
                    <>Yes{r.confirmation?.note ? ` (${r.confirmation.note})` : ""}</>
                  ) : (
                    <span className="tag">Not confirmed</span>
                  )}
                </td>
                <td>
                  {!r.voided && (
                    <>
                      {canConfirm && (
                        <Button type="button" variant="link" disabled={locked} onClick={() => start(confirmed ? "unconfirm" : "confirm", r)}>
                          {confirmed ? "Unmark" : "Mark confirmed"}
                        </Button>
                      )}{" "}
                      <Button type="button" variant="link" disabled={locked} onClick={() => start("void", r)}>
                        Void
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {action && (
        <form onSubmit={submitAct} noValidate aria-label={`${PROMPT[action.kind].button} ${formatRate(action.rate.rate)} from ${formatDate(action.rate.valid_from)}`}>
          <Field label={PROMPT[action.kind].label} value={text} onChange={(e) => setText(e.target.value)} error={words(act.error)} />
          <div className="actions">
            <Button type="submit" busy={act.isPending} disabled={locked}>
              {PROMPT[action.kind].button}
            </Button>{" "}
            <Button type="button" variant="link" onClick={() => setAction(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      <form onSubmit={submitAdd} noValidate aria-labelledby="add-rate">
        <h3 id="add-rate">Add a new rate from a date</h3>
        <Field label="New rate applies from" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
        <SelectField
          label="New GST rate"
          options={(rates.data ?? []).map((r) => ({ value: r, label: formatRate(r) }))}
          value={chosenRate}
          onChange={(e) => setRate(e.target.value)}
          hint="The rate your CA advised. The list is the GST rates in force on that date."
          error={words(add.error) ?? (rates.error ? errorText(rates.error) : undefined)}
        />
        <div className="actions">
          <Button type="submit" busy={add.isPending} disabled={locked}>
            Add rate
          </Button>
        </div>
      </form>
    </section>
  );
}

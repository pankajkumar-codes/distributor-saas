import { useEffect, useRef } from "react";

import { Button } from "../../kit/Button";
import { Field } from "../../kit/Field";
import { SelectField } from "../../kit/SelectField";
import type { Form } from "./draftForm";

/**
 * The small pop-up on New invoice (mocks v16): delivery, place of supply and the invoice discount, kept off the
 * main screen so it fits one laptop screen. It edits the same form; nothing is sent until Save draft or Create.
 * Escape, the × and Done all close it, and focus goes back to the link that opened it.
 */
export function DeliveryDialog({ form, set, buyerIsCash, stateOptions, onClose }: {
  form: Form;
  set: (patch: Partial<Form>) => void;
  buyerIsCash: boolean;
  stateOptions: { value: string; label: string }[];
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>("input, select, button")?.focus();
    return () => opener?.focus?.();
  }, []);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={box}
        className="dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delivery-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <div className="between">
          <h2 id="delivery-title">Delivery and place of supply</h2>
          <button type="button" className="xbtn" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        {buyerIsCash && <Field label="Buyer's address (optional)" value={form.cash_address} onChange={(e) => set({ cash_address: e.target.value })} />}
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
            <div className="f2">
              <Field label="Ship-to name" value={form.ship.name} onChange={(e) => set({ ship: { ...form.ship, name: e.target.value } })} />
              <SelectField label="Ship-to state" options={stateOptions} value={form.ship.state_code} onChange={(e) => set({ ship: { ...form.ship, state_code: e.target.value } })} />
              <Field label="Ship-to address line 1" value={form.ship.line1} onChange={(e) => set({ ship: { ...form.ship, line1: e.target.value } })} />
              <Field label="Ship-to address line 2" value={form.ship.line2} onChange={(e) => set({ ship: { ...form.ship, line2: e.target.value } })} />
              <Field label="Ship-to city" value={form.ship.city} onChange={(e) => set({ ship: { ...form.ship, city: e.target.value } })} />
              <Field label="Ship-to PIN" inputMode="numeric" value={form.ship.pin} onChange={(e) => set({ ship: { ...form.ship, pin: e.target.value } })} />
            </div>
            {!buyerIsCash && (
              <label className="radio">
                <input type="checkbox" checked={form.third_party} onChange={(e) => set({ third_party: e.target.checked })} /> Goods go to a third party, not the buyer
              </label>
            )}
          </>
        )}
        <div className="f2">
          <SelectField
            label="Place of supply (only if it differs)"
            placeholder="Worked out from the buyer"
            options={stateOptions}
            value={form.pos_override}
            onChange={(e) => set({ pos_override: e.target.value })}
          />
          <Field label="Invoice discount (amount)" inputMode="decimal" value={form.invoice_discount} onChange={(e) => set({ invoice_discount: e.target.value })} />
        </div>
        {form.pos_override ? (
          <Field label="Why it differs" value={form.pos_reason} onChange={(e) => set({ pos_reason: e.target.value })} hint="The reason shows on the issued invoice." />
        ) : (
          <p className="hint">If you change the place of supply, say why. The reason shows on the issued invoice.</p>
        )}
        <Button type="button" variant="primary" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  );
}

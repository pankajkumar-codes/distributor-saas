import { useId } from "react";

/**
 * ON-7: the distributor/retail business-type field, shown but not usable. Nothing is read from
 * it or sent for it; Release 2 switches it on. The tag is text, so it doesn't rely on colour.
 */
export function BusinessTypeUpcoming() {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>
        Business type <span className="tag">Upcoming</span>
      </label>
      <select id={id} disabled aria-describedby={`${id}-hint`} defaultValue="">
        <option value="">Distributor or retail business</option>
      </select>
      <p id={`${id}-hint`} className="hint">
        Coming soon. You don't need to choose anything here for now.
      </p>
    </div>
  );
}

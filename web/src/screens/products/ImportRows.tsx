import type { components } from "../../api/schema";

type Row = components["schemas"]["ImportRowOut"];
export type RowStatus = Row["status"];

export const STATUS_LABEL: Record<RowStatus, string> = {
  new: "New",
  changed: "Changed",
  unchanged: "Unchanged",
  invalid: "Has errors",
  conflict: "Repeated code",
};
const FIELD: Record<string, string> = {
  code: "Product code",
  name: "Name",
  hsn: "HSN",
  unit: "Unit",
  sale_rate: "Sale rate",
  gst_rate: "GST rate",
  gst_rate_valid_from: "Rate from",
  barcode: "Barcode",
  tax_category: "GST treatment",
  has_cess: "Cess",
  status: "Status",
};
const OUTCOME: Record<string, string> = {
  applied: "Imported",
  skipped: "Not imported",
  stale: "Not imported: the product or the GST rate list changed after the preview",
};

const label = (field: string | undefined) => (field ? (FIELD[field] ?? field) : "");
const shown = (v: unknown) => (v === null || v === undefined || v === "" ? "(blank)" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
const text = (v: unknown) => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));

/** One line per file row, in the server's words: the web adds no check of its own. */
function Details({ row }: { row: Row }) {
  if (row.errors?.length && !row.outcome) {
    return (
      <ul className="list">
        {row.errors.map((e, i) => (
          <li key={i}>
            {e.field ? <strong>{label(e.field)}: </strong> : null}
            {e.message}
          </li>
        ))}
      </ul>
    );
  }
  if (row.status === "conflict") return <>This code is on more than one row, so none of them will be imported.</>;
  if (row.diff?.length) {
    return (
      <ul className="list">
        {row.diff.map((d, i) => (
          <li key={i}>
            <strong>{label(text(d.field))}: </strong>
            {shown(d.saved)} → {shown(d.file)}
          </li>
        ))}
      </ul>
    );
  }
  if (row.status === "unchanged") return <>Same as saved.</>;
  const v = row.values;
  return <>{[v.gst_rate && `GST ${text(v.gst_rate)}%`, v.sale_rate && `sale rate ${text(v.sale_rate)}`, v.unit && text(v.unit)].filter(Boolean).join(", ")}</>;
}

export function ImportRows({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return <p>No rows to show.</p>;
  const outcomes = rows.some((r) => r.outcome);
  return (
    <table className="products">
      <thead>
        <tr>
          <th scope="col">Row</th>
          <th scope="col">Product</th>
          <th scope="col">Check</th>
          <th scope="col">Details</th>
          {outcomes && <th scope="col">Result</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.row_number}>
            <td data-label="Row">{r.row_number}</td>
            <td data-label="Product">
              <strong>{text(r.values.name) || "(no name)"}</strong> <span className="hint">{text(r.values.code)}</span>
            </td>
            <td data-label="Check">
              <span className={r.status === "invalid" || r.status === "conflict" ? "chip chip-warn" : "chip"}>{STATUS_LABEL[r.status]}</span>
            </td>
            <td data-label="Details">
              <Details row={r} />
            </td>
            {outcomes && (
              <td data-label="Result">
                {r.outcome ? OUTCOME[r.outcome] : ""}
                {r.outcome === "stale" && r.errors?.[0]?.message && <p className="hint">{r.errors[0].message}</p>}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

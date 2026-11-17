// Row names of the GSTR-3B form as the server prints them (utility V5.8). Text only, no numbers. The seller types the
// amounts; the field names `<table>.<row>.<head>` are the server's. Rows marked `copy` take the central tax once and the
// state/UT tax is the same amount (the utility does the same).

export type Head = "taxable_value" | "igst" | "cgst" | "sgst" | "cess" | "inter" | "intra";
export type Row = { key: string; label: string; heads: Head[]; copy?: boolean };
export type Table = { id: string; title: string; hint?: string; rows: Row[] };

export const HEAD_NAME: Record<Head, string> = {
  taxable_value: "Taxable value",
  igst: "Integrated Tax",
  cgst: "Central Tax",
  sgst: "State/UT Tax",
  cess: "Cess",
  inter: "Inter-state supplies",
  intra: "Intra-state supplies",
};
const TAX: Head[] = ["igst", "cgst", "sgst", "cess"];

export const TABLES: Table[] = [
  { id: "t3_1", title: "3.1(d) Inward supplies liable to reverse charge", hint: "Type these yourself. We do not work them out.", rows: [{ key: "d", label: "(d) Inward supplies (liable to reverse charge)", heads: ["taxable_value", ...TAX], copy: true }] },
  {
    id: "t4a",
    title: "4(A) ITC available",
    hint: "From your GSTR-2B on the GST portal.",
    rows: [
      { key: "import_goods", label: "(1) Import of goods", heads: ["igst", "cess"] },
      { key: "import_services", label: "(2) Import of services", heads: ["igst", "cess"] },
      { key: "rcm_inward", label: "(3) Inward supplies liable to reverse charge (other than 1 & 2 above)", heads: TAX, copy: true },
      { key: "isd", label: "(4) Inward supplies from ISD", heads: TAX, copy: true },
      { key: "other", label: "(5) All other ITC", heads: TAX, copy: true },
    ],
  },
  {
    id: "t4b",
    title: "4(B) ITC reversed",
    rows: [
      { key: "rev_rules", label: "(1) As per rules 38, 42 & 43 of CGST Rules and section 17(5)", heads: TAX, copy: true },
      { key: "rev_other", label: "(2) Others", heads: TAX },
    ],
  },
  {
    id: "t4d",
    title: "4(D) Other details",
    rows: [
      { key: "reclaimed", label: "(1) ITC reclaimed which was reversed under Table 4(B)(2) in earlier tax period", heads: TAX, copy: true },
      { key: "ineligible", label: "(2) Ineligible ITC under section 16(4) & ITC restricted due to PoS rules", heads: TAX, copy: true },
    ],
  },
  {
    id: "t5",
    title: "5 Exempt, nil-rated and non-GST inward supplies",
    rows: [
      { key: "composition_exempt_nil", label: "From a supplier under composition scheme, Exempt and Nil rated supply", heads: ["inter", "intra"] },
      { key: "non_gst", label: "Non GST supply", heads: ["inter", "intra"] },
    ],
  },
  { id: "t5_1", title: "5.1 Interest", hint: "Type it if the portal shows any. We never work out interest or late fee.", rows: [{ key: "interest", label: "Interest", heads: TAX }] },
];

/** The heads the seller types: central tax once, and no state/UT column, on a `copy` row. */
export const typedHeads = (row: Row): Head[] => (row.copy ? row.heads.filter((h) => h !== "sgst") : row.heads);

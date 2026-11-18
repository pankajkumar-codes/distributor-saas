import type { components } from "../../api/schema";

export type Upload = components["schemas"]["app__modules__imports__api__UploadOut"];
export type Section = components["schemas"]["UploadStartIn"]["section"];

const PLATFORM_TYPES = [".csv", ".xlsx", ".zip"];

/**
 * The sections offered in M3, with the file types each one takes (the server's `ALLOWED` list;
 * the server's answer is still the one that counts). The PDF section arrives with the PDF reader
 * (R1-M6, decision D2).
 */
export const SECTIONS: { id: Section; label: string; hint: string; types: string[]; typeWords: string }[] = [
  { id: "amazon", label: "Amazon", hint: "Your monthly Merchant Tax Report files, B2C and B2B (CSV, or a zip of them).", types: PLATFORM_TYPES, typeWords: "a CSV, Excel or zip file" },
  { id: "flipkart", label: "Flipkart", hint: "Your Sales Report workbook for the month (Excel).", types: PLATFORM_TYPES, typeWords: "a CSV, Excel or zip file" },
  { id: "meesho", label: "Meesho", hint: "Your monthly GST report (the zip from the Supplier Panel, or the Excel files in it).", types: PLATFORM_TYPES, typeWords: "a CSV, Excel or zip file" },
  { id: "own_invoices_excel", label: "Your own sales invoices", hint: "An Excel sheet of the invoices you issued, the invoice PDFs, or both. You can add several files at once.", types: [".csv", ".xlsx", ".pdf"], typeWords: "a CSV, Excel or PDF file" },
];

/** The own-invoices card takes both kinds; each file goes to the reader for its type. A zip of PDFs waits for the server. */
export const OWN_INVOICE_TYPES = [".csv", ".xlsx", ".pdf"];
export const ownInvoiceSection = (name: string): Section => (name.toLowerCase().endsWith(".pdf") ? "own_invoices_pdf" : "own_invoices_excel");
export function ownInvoiceProblem(file: File): string | undefined {
  if (!OWN_INVOICE_TYPES.some((ext) => file.name.toLowerCase().endsWith(ext))) return "Choose a CSV, Excel or PDF file.";
  return file.size === 0 ? "That file is empty." : undefined;
}

type Choice = (typeof SECTIONS)[number];

/** Which answer at setup ("Where you sell") each section belongs to. */
const CHANNEL_OF = { amazon: "amazon", flipkart: "flipkart", meesho: "meesho", own_invoices_excel: "own_invoices" } as const;

/** The sections for the places the business said it sells; a platform it didn't choose is not offered. */
export const sectionsFor = (channels: Record<(typeof CHANNEL_OF)[keyof typeof CHANNEL_OF], boolean>) =>
  SECTIONS.filter((s) => s.id in CHANNEL_OF && channels[CHANNEL_OF[s.id as keyof typeof CHANNEL_OF]]);

// What the file picker offers. The server decides what it accepts and says why when it doesn't,
// so this only spares a pointless round trip. Size is left to the server: its limit is data.
export const acceptFor = (section: Choice) => section.types.join(",");

export function wrongType(section: Choice, name: string): boolean {
  const lower = name.toLowerCase();
  return !section.types.some((ext) => lower.endsWith(ext));
}

/** An upload stops changing once it is one of these; the parse job settles every upload into one. */
const SETTLED = new Set<Upload["status"]>(["parsed", "rejected", "stored", "expired"]);
export const settled = (upload: Upload | undefined) => Boolean(upload && SETTLED.has(upload.status));

/** What a seller reads for each state. A rejection shows the server's own words. */
export function statusText(u: Upload): string {
  switch (u.status) {
    case "pending":
      return "Waiting for the file to arrive.";
    case "received":
    case "parsing":
      return "Reading your file. You can leave this page; it keeps going.";
    case "parsed":
      return "Read.";
    case "stored":
      return "Saved, not read yet.";
    case "expired":
      return "This upload expired before it finished. Choose the file again.";
    case "rejected":
      return u.reject_message || "We couldn't read this file.";
    default:
      return "";
  }
}

/** The short chip beside a section's name (mock v13): the state of its latest upload, in the server's own status. */
export function statusChip(u: Upload | undefined): { label: string; tone: string } {
  if (!u) return { label: "Nothing uploaded yet", tone: "" };
  switch (u.status) {
    case "parsed":
      return { label: "Read", tone: "chip-ok" };
    case "stored":
      return { label: "Saved", tone: "chip-info" };
    case "rejected":
      return { label: "Not read", tone: "chip-bad" };
    case "expired":
      return { label: "Expired", tone: "chip-warn" };
    default:
      return { label: "Reading", tone: "chip-info" };
  }
}

import { isDemo } from "../demo";

// The platform error shape {error: {code, message, field?, fix?}} (LLD-0 §3.2), turned
// into what a screen shows (LLD-1 §11.4).

export type ApiError = {
  status: number;
  code: string;
  message: string;
  field?: string;
  fix?: string;
  unmet?: string[]; // password_weak: the ids of the password rules not met
  retryAfter?: number; // seconds, from Retry-After on a 429
  challenge?: string; // totp_not_accepted: the provider's next challenge (LLD-1 §5.4)
  detail?: string; // which request failed and how, for the person to read out to support ("GET /api/v1/… no answer in 30 s")
};

type Body = {
  error?: { code?: string; message?: string; field?: string; fix?: string; unmet?: string[] };
  challenge?: string;
};

/**
 * The API's request checks (the framework's own validation, before the app's rules run) answer in programmer text:
 * "String should match pattern '^[0-9]{6}$'", "Input should be 'taxable' or ...". A person must never read that.
 * This turns each kind into a plain sentence, by the field it names, in one place for every form. Any message that
 * is already plain (the app's own rules write those) passes through untouched.
 */
const BY_FIELD: Record<string, { pattern?: string; choice?: string }> = {
  pin: { pattern: "A PIN code is 6 digits and doesn't start with 0." },
  email: { pattern: "Enter a valid email address, like name@business.in." },
  rate: { pattern: "Choose a GST rate.", choice: "Choose a GST rate." },
  tax_category: { choice: "Choose how GST applies." },
  sale_rate: { pattern: "Enter the rate as a number, like 45 or 45.50." },
  gstin: { pattern: "Check the GSTIN: it is 15 letters and numbers." },
};
export function plainValidation(message: string, field?: string): string {
  const key = (field ?? "").split(".").pop() ?? "";
  const hit = BY_FIELD[key];
  // A rule of ours wrapped by the framework ("Value error, Enter a name"): its sentence is already plain; keep it, drop the prefix.
  const wrapped = /^Value error,\s*(.+)$/is.exec(message);
  if (wrapped) return wrapped[1].trim();
  // Number and date checks first, so a field's own wording below never hides what is actually wrong with the number.
  const places = /^Decimal input should have no more than (\d+) decimal places?/i.exec(message);
  if (places) return `Use at most ${places[1]} decimal place${places[1] === "1" ? "" : "s"}.`;
  if (/^Input should be (greater|less)( than)?|^Input should be (greater|less) than or equal/i.test(message)) return "That number is outside the allowed range.";
  if (/^Input should be a valid (decimal|number|integer)|^Input should be a finite number|^Decimal (input|scale)/i.test(message)) return "Enter a number, like 45 or 45.50.";
  if (/^Input should be a valid (date|datetime)|^Input should be a valid date/i.test(message)) return "Enter a valid date.";
  if (/^String should match pattern/i.test(message)) return hit?.pattern ?? "That isn't in the format we expect. Check it and try again.";
  if (/^Input should be '/i.test(message) || /^value is not a valid/i.test(message)) return hit?.choice ?? "Choose one of the options.";
  if (/^Input should be/i.test(message)) return "Check this and try again.";
  if (/^String should have at most/i.test(message)) return "That is too long. Make it shorter.";
  if (/^String should have at least/i.test(message)) return "That is too short.";
  if (/^Field required/i.test(message)) return "This is required.";
  if (message === "that isn't a GST state code") return "Choose a state from the list.";
  if (/^(List|Set|Tuple) should have/i.test(message)) return "Check the number of items.";
  return message;
}

export function toApiError(response: Response | undefined, body: unknown, detail?: string): ApiError {
  if (!response) return { status: 0, code: "network", message: "", ...(detail ? { detail } : {}) };
  const error = (body as Body | undefined)?.error ?? {};
  const challenge = (body as Body | undefined)?.challenge;
  const retry = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
  return {
    status: response.status,
    code: error.code ?? "unknown",
    message: plainValidation(error.message ?? "", error.field),
    field: error.field,
    fix: error.fix,
    unmet: error.unmet,
    retryAfter: Number.isFinite(retry) ? retry : undefined,
    ...(challenge ? { challenge } : {}),
    ...(detail ? { detail } : {}),
  };
}

const BY_CODE: Record<string, string> = {
  // Catalog: a record that has been on an invoice is kept for the invoice's sake
  customer_in_use: "This customer is on invoices, so it can be archived but not deleted.",
  product_in_use: "This product is on invoices, so it can be archived but not deleted.",
  // Invoicing (R2)
  invoice_plan_required: "You have used your free invoices. Choose the invoicing plan to keep creating invoices.",
  code_not_accepted: "That code didn't work. Check it, or send a new code.",
  email_invalid: "Enter a valid email address, like name@business.in.",
  password_weak: "Choose a stronger password.",
  signin_not_accepted: "The email or password is wrong.",
  signin_expired: "That took too long. Sign in again.",
  totp_not_accepted: "That code didn't work. Enter the current code from your authenticator app.",
  // Preparing and filing a GST return (R1-M8)
  not_ready: "This return is not ready yet. Look at the items above and try again.",
  download_not_available: "Downloading the file is not available on your plan yet.",
  period_gate_closed: "This period is not ready to file yet. Check the two confirmations and try again.",
  gate_item_invalid: "Choose one of the two confirmations.",
  period_not_ended: "That period has not ended yet. Come back after it has.",
  period_too_large: "This period has more rows than one file can hold. Choose a shorter one, or contact support.",
  quarter_not_for_monthly_filer: "Quarter files are for businesses that file quarterly.",
  gstin_required: "Add your GSTIN in your business details first.",
  nothing_to_file: "There is nothing in this return to put in a file.",
  not_renderable: "We can't make a file for this kind of return yet.",
  file_too_large: "The file came out too large for the portal. Contact support.",
  changed_during_export: "The return changed while the file was being made. Check it and try again.",
  not_allowed: "Your role can't do this.",
  worksheet_blocked: "Fix the items in your GSTR-1 first, then build the worksheet again.",
  worksheet_not_built: "Build the worksheet first.",
  worksheet_changed: "This worksheet was saved by someone else while you were typing.",
  cannot_accept: "This can't be accepted. It has to be fixed.",
  period_not_open: "This return is already marked filed.",
  changed_since_export: "This return has changed since the file you took.",
  arn_invalid: "Enter the ARN the portal gave you.",
  filed_on_future: "The filing date can't be in the future.",
  filed_on_before_period: "The filing date can't be before the period ends.",
  reason_required: "Write a reason.",
  not_locked: "This return is not marked filed.",
  quarter_locked: "Unlock the quarterly GSTR-1 first.",
  no_file: "No file was kept for this return.",
};

export const SLOW_SERVER = "The server is taking too long to answer. Try again in a moment.";

/** The sentence a screen shows for an error, inline under `field` when there is one. */
export function errorText(error: ApiError): string {
  if (error.status === 429) {
    const minutes = Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60));
    return `Too many tries. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`;
  }
  if (error.code === "session_invalid")
    return isDemo()
      ? "The server did not accept the address this page is open at. Open the app from the link your setup printed and try again."
      : "Your session has ended. Sign in again.";
  // The browser cannot tell a slow server from an unreachable one, but it does know it gave up waiting: say that.
  if (error.code === "timeout") return SLOW_SERVER;
  if (error.status === 0) return "We couldn't reach the server. Check your connection and try again.";
  if (error.status >= 500) return "Something went wrong on our side. Nothing was lost; try again.";
  return error.fix ?? BY_CODE[error.code] ?? "That didn't work. Try again.";
}

/** The server or the network failed, so the same request may work if tried again. */
export function transient(error: unknown): boolean {
  const { status, code } = (error as ApiError | undefined) ?? {};
  if (code === "timeout") return false; // already waited the full limit once; the screen offers Try again
  return status === 0 || (typeof status === "number" && status >= 500);
}

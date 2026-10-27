// The platform error shape {error: {code, message, field?, fix?}} (LLD-0 §3.2), turned
// into what a screen shows (LLD-1 §11.4).

export type ApiError = {
  status: number;
  code: string;
  message: string;
  field?: string;
  fix?: string;
  retryAfter?: number; // seconds, from Retry-After on a 429
};

type Body = { error?: { code?: string; message?: string; field?: string; fix?: string } };

export function toApiError(response: Response | undefined, body: unknown): ApiError {
  if (!response) return { status: 0, code: "network", message: "" };
  const error = (body as Body | undefined)?.error ?? {};
  const retry = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
  return {
    status: response.status,
    code: error.code ?? "unknown",
    message: error.message ?? "",
    field: error.field,
    fix: error.fix,
    retryAfter: Number.isFinite(retry) ? retry : undefined,
  };
}

const BY_CODE: Record<string, string> = {
  code_not_accepted: "That code didn't work. Check it, or send a new code.",
  email_invalid: "Enter a valid email address, like name@business.in.",
  password_weak: "Choose a stronger password.",
};

/** The sentence a screen shows for an error, inline under `field` when there is one. */
export function errorText(error: ApiError): string {
  if (error.status === 429) {
    const minutes = Math.max(1, Math.ceil((error.retryAfter ?? 60) / 60));
    return `Too many tries. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`;
  }
  if (error.status === 0) return "We couldn't reach the server. Check your connection and try again.";
  if (error.status >= 500) return "Something went wrong on our side. Nothing was lost; try again.";
  return error.fix ?? BY_CODE[error.code] ?? "That didn't work. Try again.";
}

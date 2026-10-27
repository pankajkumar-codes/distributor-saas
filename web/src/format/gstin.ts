// A port of app/src/app/modules/business/gstin.py for the as-you-type hint only. The
// server stays the judge; tests/unit/gstin.test.ts runs the server's shared cases here.
// It proves the string is well formed, never that the GSTIN is registered or active.

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const SHAPE = /^[0-9]{2}[0-9A-Z]{10}[1-9A-Z][0-9A-Z][0-9A-Z]$/;
const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const TAN = /^[A-Z]{4}[0-9]{5}[A-Z]$/;

export type GstinCheck = {
  normalised: string;
  ok: boolean;
  stateCode: string | null;
  errors: string[];
  warnings: string[];
};

export function normaliseGstin(value: string): string {
  return (value ?? "").replace(/\s+/g, "").toUpperCase();
}

export function checkCharacter(first14: string): string {
  let total = 0;
  for (let i = 0; i < first14.length; i++) {
    const v = ALPHABET.indexOf(first14[i]) * (i % 2 ? 2 : 1);
    total += Math.floor(v / 36) + (v % 36);
  }
  return ALPHABET[(36 - (total % 36)) % 36];
}

export function checkGstin(value: string, { own = true } = {}): GstinCheck {
  const g = normaliseGstin(value);
  if (g.length !== 15) return { normalised: g, ok: false, stateCode: null, errors: ["gstin_length"], warnings: [] };
  if (!SHAPE.test(g)) return { normalised: g, ok: false, stateCode: null, errors: ["gstin_shape"], warnings: [] };
  const errors: string[] = [];
  const warnings: string[] = [];
  if (checkCharacter(g.slice(0, 14)) !== g[14]) errors.push("gstin_check_char");
  const pan = g.slice(2, 12);
  if (!(PAN.test(pan) || TAN.test(pan))) warnings.push("pan_shape");
  if (own && g[13] !== "Z") warnings.push("gstin_not_z");
  return { normalised: g, ok: errors.length === 0, stateCode: g.slice(0, 2), errors, warnings };
}

const MESSAGES: Record<string, (n: number) => string> = {
  gstin_length: (n) => `GSTIN has ${n} characters; it needs 15.`,
  gstin_shape: () => "GSTIN can only be digits and capital letters in the GSTIN pattern; please re-check the number.",
  gstin_check_char: () => "GSTIN check character doesn't match; please re-check the number.",
  gstin_state: () => "The first two digits of a GSTIN must be a state code.",
  pan_shape: () => "Characters 3 to 12 don't look like a PAN; please re-check the number.",
  gstin_not_z: () => "The 14th character of a GSTIN is usually Z; please re-check the number.",
};

export function gstinMessage(code: string, value = ""): string {
  const words = MESSAGES[code];
  return words ? words(normaliseGstin(value).length) : code;
}

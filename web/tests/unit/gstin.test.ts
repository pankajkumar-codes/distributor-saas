import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { checkGstin, gstinMessage } from "../../src/format/gstin";

// The same rows app/src/app/modules/business/tests/test_gstin.py checks against the server.
const FIXTURE = resolve(__dirname, "../../../app/src/app/modules/business/tests/gstin_cases.json");
type Case = {
  input: string;
  own: boolean;
  why: string;
  ok: boolean;
  normalised: string;
  state_code: string | null;
  errors: string[];
  warnings: string[];
};
const cases: Case[] = JSON.parse(readFileSync(FIXTURE, "utf8")).cases;

describe("checkGstin matches the server on every shared case", () => {
  it("has cases to check", () => expect(cases.length).toBeGreaterThan(10));

  it.each(cases.map((c) => [c.why, c] as const))("%s", (_why, c) => {
    expect(checkGstin(c.input, { own: c.own })).toEqual({
      normalised: c.normalised,
      ok: c.ok,
      stateCode: c.state_code,
      errors: c.errors,
      warnings: c.warnings,
    });
  });
});

it("uses the server's words for the errors", () => {
  expect(gstinMessage("gstin_length", "27AAPFU0939F1Z")).toBe("GSTIN has 14 characters; it needs 15.");
  expect(gstinMessage("gstin_check_char", "")).toBe("GSTIN check character doesn't match; please re-check the number.");
});

import { describe, expect, it } from "vitest";

import { errorText, plainValidation, toApiError } from "../../src/api/errors";

const response = (status: number, headers: Record<string, string> = {}) => new Response(null, { status, headers });

describe("toApiError", () => {
  it("reads the platform error shape, with field and fix", () => {
    const body = { error: { code: "password_weak", message: "weak", field: "password", fix: "Use at least 10 characters." } };
    expect(toApiError(response(422), body)).toEqual({
      status: 422,
      code: "password_weak",
      message: "weak",
      field: "password",
      fix: "Use at least 10 characters.",
      retryAfter: undefined,
    });
  });

  it("reads Retry-After on a 429", () => {
    expect(toApiError(response(429, { "Retry-After": "125" }), {}).retryAfter).toBe(125);
  });

  it("treats no response as a network error", () => {
    expect(toApiError(undefined, undefined)).toMatchObject({ status: 0, code: "network" });
  });
});

describe("errorText", () => {
  const err = (status: number, extra = {}) => ({ status, code: "x", message: "", ...extra });

  it("prefers the server's fix", () => {
    expect(errorText(err(422, { code: "password_weak", fix: "Use at least 10 characters." }))).toBe(
      "Use at least 10 characters.",
    );
  });

  it("turns Retry-After into whole minutes", () => {
    expect(errorText(err(429, { retryAfter: 125 }))).toBe("Too many tries. Try again in 3 minutes.");
    expect(errorText(err(429, { retryAfter: 30 }))).toBe("Too many tries. Try again in 1 minute.");
  });

  it("maps known codes, server errors and the network", () => {
    expect(errorText(err(400, { code: "code_not_accepted" }))).toMatch(/code didn't work/);
    expect(errorText(err(500))).toMatch(/our side/);
    expect(errorText(err(0))).toMatch(/couldn't reach/);
    expect(errorText(err(0, { code: "timeout" }))).toBe("The server is taking too long to answer. Try again in a moment."); // gave up waiting
    expect(errorText(err(400, { code: "something_new" }))).toBe("That didn't work. Try again.");
  });
});

describe("plainValidation", () => {
  it("turns the framework's checks into plain sentences by the field they name", () => {
    expect(plainValidation("String should match pattern '^[0-9]{6}$'", "address.pin")).toBe("A PIN code is 6 digits and doesn't start with 0.");
    expect(plainValidation("String should match pattern '^\\s*[^@\\s]+@[^@\\s]+$'", "email")).toBe("Enter a valid email address, like name@business.in.");
    expect(plainValidation("Input should be 'taxable', 'exempt', 'nil_rated' or 'non_gst'", "tax_category")).toBe("Choose how GST applies.");
    expect(plainValidation("String should have at most 300 characters", "name")).toBe("That is too long. Make it shorter.");
    expect(plainValidation("Field required", "name")).toBe("This is required.");
    expect(plainValidation("that isn't a GST state code", "cash_buyer.state_code")).toBe("Choose a state from the list.");
  });

  it("keeps the sentence of one of our own rules and only drops the framework's 'Value error' prefix", () => {
    expect(plainValidation("Value error, Enter a name of up to 200 characters", "name")).toBe("Enter a name of up to 200 characters");
  });

  it("words number and date checks as such, even on a field that has its own wording", () => {
    expect(plainValidation("Input should be greater than 0", "rate")).toBe("That number is outside the allowed range.");
    expect(plainValidation("Input should be a valid decimal", "rate")).toBe("Enter a number, like 45 or 45.50.");
    expect(plainValidation("Decimal input should have no more than 2 decimal places", "sale_rate")).toBe("Use at most 2 decimal places.");
    expect(plainValidation("Input should be a valid date or datetime, invalid character in year", "valid_from")).toBe("Enter a valid date.");
    expect(plainValidation("Input should be less than or equal to 100", "quantity")).toBe("That number is outside the allowed range.");
  });

  it("falls back to a plain line for a field it has no wording for, and leaves plain messages alone", () => {
    expect(plainValidation("String should match pattern '^x$'", "other")).toBe("That isn't in the format we expect. Check it and try again.");
    expect(plainValidation("Another product already uses this code", "code")).toBe("Another product already uses this code");
  });

  it("is applied to every API error message", () => {
    const body = { error: { code: "invalid", message: "String should match pattern '^[0-9]{6}$'", field: "pin" } };
    expect(toApiError(response(422), body).message).toBe("A PIN code is 6 digits and doesn't start with 0.");
  });
});

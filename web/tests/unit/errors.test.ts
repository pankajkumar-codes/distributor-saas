import { describe, expect, it } from "vitest";

import { errorText, toApiError } from "../../src/api/errors";

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
    expect(errorText(err(400, { code: "something_new" }))).toBe("That didn't work. Try again.");
  });
});
